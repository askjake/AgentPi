"""Deployed-environment gate: real LangGraph, registry, messages and Python tool.

Only model/provider calls and model-specific option application are replaced.
No network scan, provider request, database migration, or persistent GUI occurs.
All executor writes belong to pytest's temporary workspace.
"""
from __future__ import annotations
import asyncio
import hashlib
import importlib
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

import pytest

PROMPT = 'write and run a small Python script that prints the Python executable, Python version, hostname, and current working directory'


@pytest.fixture
def live_graph(monkeypatch, tmp_path):
    monkeypatch.setenv('AGENT_MODE_WORKDIR', str(tmp_path))
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import MemorySaver
    from app.agent.agents import agentic_rag as rag, coverity_tool_loop as live
    from app.agent_mode import agent as mode, child_conversation as child, tools as native

    class NoProvider:
        _llm_type = 'coverity-assist'
        calls = 0
        def bind_tools(self, tools):
            return self
        async def ainvoke(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError('Local diagnostic must not invoke any model')
    provider = NoProvider()
    def strict_get_model(*args, **kwargs):
        assert args == ()
        assert kwargs == {}
        return provider

    monkeypatch.setattr(rag, 'get_model', strict_get_model)
    monkeypatch.setattr(mode, 'get_model', strict_get_model)
    monkeypatch.setattr(rag, 'set_model_config', lambda *a: None)
    monkeypatch.setattr(mode, 'set_model_config', lambda *a: None)
    monkeypatch.setattr(native, 'BASE_AGENT_WORKDIR', str(tmp_path))
    monkeypatch.setattr(child, 'BASE_AGENT_WORKDIR', str(tmp_path))
    monkeypatch.setattr(mode, 'interceptor', SimpleNamespace(
        thought=lambda *a: None, context_update=lambda *a: None, decision=lambda *a, **k: None))
    monkeypatch.setattr(rag.settings, 'PLLM_PROVIDER', 'coverity-assist')
    monkeypatch.setattr(mode.settings, 'PLLM_PROVIDER', 'coverity-assist')
    monkeypatch.setattr(rag, 'get_checkpointer', lambda: MemorySaver())
    # Real registry bindings must include the real local tool, not a surrogate.
    bound = rag.get_tools_set('agent_mode')
    assert any(t is native.agent_run_python for t in bound)
    bound_names = {getattr(t, 'name', '') for t in bound}
    assert set(live.MCOP_TOOL_NAMES).issubset(bound_names)
    # If stale routing accidentally selects an actual search execution tool,
    # fail before any request. Do NOT replace public_web_search_status: the
    # diagnostic-routing test below intentionally invokes that local diagnostic
    # tool with its probe function monkeypatched.
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected search request')
    async def async_forbidden(*args, **kwargs):
        raise AssertionError('Unexpected search request')
    for t in rag.get_tools_set('search'):
        tool_name = getattr(t, 'name', None) or getattr(t, '__name__', None)
        if tool_name not in {'public_web_search', 'internal_search'}:
            continue
        if getattr(t, 'func', None) is not None:
            monkeypatch.setattr(t, 'func', forbidden)
        if getattr(t, 'coroutine', None) is not None:
            monkeypatch.setattr(t, 'coroutine', async_forbidden)
    rag.get_graph.cache_clear()
    yield rag, mode, live, native, provider, HumanMessage, tmp_path
    rag.get_graph.cache_clear()


def test_live_graph_bound_to_shared_entrypoint(live_graph):
    rag, mode, live, *_ = live_graph
    assert rag.run_coverity_tool_loop is live.run_coverity_tool_loop
    assert mode.run_coverity_tool_loop is live.run_coverity_tool_loop
    assert live.execution_identity()['contract'] == 'agentpi-live-planner-v1'


def test_real_compiled_chat_graph_runs_exact_probe(live_graph):
    rag, _, _, _, provider, HumanMessage, workspace = live_graph
    state = asyncio.run(rag.get_graph().ainvoke(
        {'messages': [HumanMessage(content=PROMPT)], 'model_config': {}},
        config={'configurable': {'thread_id': 'live-chat-probe'}}))
    text = state['messages'][-1].content
    assert 'Local agent_run_python result' in text
    assert 'return code=0' in text
    assert sys.executable in text
    assert socket.gethostname() in text
    script = workspace / 'live-chat-probe/runtime_probe.py'
    assert script.is_file()
    assert provider.calls == 0


def test_real_agent_mode_node_runs_exact_probe(live_graph):
    _, mode, _, _, provider, HumanMessage, workspace = live_graph
    state = asyncio.run(mode.agent_mode_node(
        {'messages': [HumanMessage(content=PROMPT)], 'chat_id': 'live-mode-probe', 'iterations': 0}))
    text = state['messages'][-1].content
    assert 'return code=0' in text
    assert sys.executable in text
    assert (workspace / 'live-mode-probe/runtime_probe.py').is_file()
    assert provider.calls == 0


def test_live_mcop_capability_answer_not_model_invention(live_graph):
    rag, _, _, _, provider, HumanMessage, _ = live_graph
    state = asyncio.run(rag.call_model(
        {'messages': [HumanMessage(content='describe your MCOP backend functionality.')], 'model_config': {}},
        config={'configurable': {'thread_id': 'mcop-probe'}}))
    text = state['messages'][-1].content
    assert 'Multi-Conversation Orchestration Protocol' in text
    assert 'implemented in this AgentPi revision' in text
    assert 'All expected MCOP parent tools are bound' in text
    assert 'This description request did not spawn a child' in text
    assert provider.calls == 0


def test_live_mcop_demo_dispatches_one_real_bound_spawn_tool(live_graph, monkeypatch):
    rag, _, _, _, provider, HumanMessage, _ = live_graph
    from app.agent_mode import mcop_tools

    calls = []
    async def fake_spawn(chat_id, task_prompt, task_id='', context_files='[]', max_iters=5):
        calls.append({
            'chat_id': chat_id,
            'task_prompt': task_prompt,
            'task_id': task_id,
            'context_files': context_files,
            'max_iters': max_iters,
        })
        return json.dumps({
            'contract': 'agentpi-mcop-v1',
            'task_id': task_id,
            'status': 'completed',
            'facts': [{'claim': 'native fixture child executed', 'confidence': 'high'}],
            'gaps': [],
            'errors': [],
            'summary': 'native controlled child fixture complete',
        })

    monkeypatch.setattr(mcop_tools.agent_spawn_task, 'coroutine', fake_spawn)
    state = asyncio.run(rag.call_model(
        {'messages': [HumanMessage(content='test MCOP in action')], 'model_config': {}},
        config={'configurable': {'thread_id': 'mcop-live-demo'}}))
    text = state['messages'][-1].content
    assert text.startswith('MCOP demonstration result (actual agent_spawn_task output)')
    assert 'native fixture child executed' in text
    assert len(calls) == 1
    assert calls[0]['chat_id'] == 'mcop-live-demo'
    assert calls[0]['task_id'].startswith('mcop-demo-')
    assert calls[0]['max_iters'] == 2
    assert provider.calls == 0


def test_live_missing_artifact_is_not_reported_complete(live_graph):
    from langchain_core.messages import AIMessage
    rag, _, _, _, provider, HumanMessage, _ = live_graph
    state = asyncio.run(rag.call_model(
        {'messages': [HumanMessage(content='create a desktop GUI app'),
                      AIMessage(content='COMPLETE: home_manager.py written and shortcut created'),
                      HumanMessage(content='did you finish?')], 'model_config': {}},
        config={'configurable': {'thread_id': 'missing-artifact'}}))
    text = state['messages'][-1].content
    assert 'ARTIFACT_READBACK_ONLY' in text
    assert 'workspace_not_found' in text
    assert provider.calls == 0


def test_loaded_identity_matches_both_graph_callers(live_graph):
    rag, mode, live, *_ = live_graph
    from app.health.router import execution_health_check
    report = asyncio.run(execution_health_check())
    assert report['chat_binding_matches']
    assert report['agent_mode_binding_matches']
    assert report['loaded_entrypoint_sha256'] == hashlib.sha256(Path(live.__file__).read_bytes()).hexdigest()
    assert report['mcop']['implemented_in_this_revision'] is True
    assert report['mcop']['registry_binding_matches'] is True
    assert set(report['mcop']['bound_tool_names']) == set(live.MCOP_TOOL_NAMES)
    assert report['mcop']['max_depth'] == 1


def test_cached_human_message_still_matches_exact_probe(live_graph):
    from app.agent.agents import coverity_tool_loop_token_limit as implementation
    _, _, _, _, _, HumanMessage, _ = live_graph
    msg = HumanMessage(content=[
        {"type": "text", "text": PROMPT},
        {"cachePoint": {"type": "default"}},
    ])
    assert implementation._extract_last_user_text([msg]) == PROMPT
    assert implementation._runtime_probe_payload(
        implementation._extract_last_user_text([msg])
    ) is not None


def test_live_search_diagnostic_bypasses_model_and_is_passive(live_graph, monkeypatch):
    rag, _, _, _, provider, HumanMessage, _ = live_graph
    from app.tools import web_search

    async def forbidden_probe():
        raise AssertionError("normal chat diagnosis must not actively probe provider")

    monkeypatch.setattr(web_search, "probe_public_search", forbidden_probe)
    state = asyncio.run(rag.call_model(
        {"messages": [HumanMessage(content="diagnose your search tool first")], "model_config": {}},
        config={"configurable": {"thread_id": "search-diagnostic"}},
    ))
    text = state["messages"][-1].content
    assert "Public web search diagnostics (actual runtime output)" in text
    assert '"diagnostic_mode": "passive_observation"' in text
    assert '"effective_mode": "direct"' in text
    assert provider.calls == 0


def test_search_diagnostic_tool_not_replaced_by_fixture(live_graph):
    rag, *_ = live_graph
    tools = {getattr(t, "name", getattr(t, "__name__", "")): t for t in rag.get_tools_set("search")}
    status = tools["public_web_search_status"]
    assert getattr(status, "coroutine", None) is not None
    assert getattr(status.coroutine, "__name__", "") == "public_web_search_status"


def test_live_fresh_search_returns_tool_output_without_model(live_graph, monkeypatch):
    rag, _, _, _, provider, HumanMessage, _ = live_graph

    tools = {getattr(t, "name", getattr(t, "__name__", "")): t for t in rag.get_tools_set("search")}
    public_search = tools["public_web_search"]

    async def fake_search(query, max_results=6, config=None):
        return (
            '{"query": "' + query.replace('"', '') + '", '
            '"backend": "direct", "source": "ddg-lite", '
            '"results": [{"title": "Python fixture", '
            '"url": "https://docs.python.org/3.13/", "snippet": "fixture"}]}'
        )

    monkeypatch.setattr(public_search, "coroutine", fake_search)

    state = asyncio.run(rag.call_model(
        {
            "messages": [
                HumanMessage(
                    content="search the web for the latest Python 3.13 release notes and give me the source links"
                )
            ],
            "model_config": {},
        },
        config={"configurable": {"thread_id": "live-search-grounding"}},
    ))
    text = state["messages"][-1].content
    assert text.startswith("## Web search results")
    assert "[Python fixture](https://docs.python.org/3.13/)" in text
    assert "backend=`direct`" in text
    assert "source=`ddg-lite`" in text
    assert "no LLM summarization was used" in text
    assert provider.calls == 0
