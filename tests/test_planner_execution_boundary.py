"""Behavioral regression tests: real dispatcher/executor code, fake provider I/O.

No live API, database, external scan, or LLM request is made. The runtime probe
runs the production agent_run_python body in a temporary per-test workspace.
External imports/decorators are isolated so this suite runs in the sidecar venv.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import types
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "dish-chat/backend/app/agent/agents/coverity_tool_loop_token_limit.py"
TOOLS = ROOT / "dish-chat/backend/app/agent_mode/tools.py"
PROMPT = "write and run a small Python script that prints the Python executable, Python version, hostname, and current working directory"


class Message:
    def __init__(self, content, **kwargs):
        self.content = content
        self.type = "human"


class Model:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    async def ainvoke(self, messages, config=None):
        self.calls.append(messages[0].content)
        if not self.responses:
            raise AssertionError("unexpected provider call")
        return Message(self.responses.pop(0))


@pytest.fixture
def planner(monkeypatch):
    # External model imports are replaced, not any routing/parser/tool functions.
    source_path = Path(os.environ.get("AGENTPI_PLANNER_TEST_SOURCE", str(PLANNER)))
    tree = ast.parse(source_path.read_text(encoding="utf-8"), str(source_path))
    excluded = {"langchain_core.messages", "app.core.llm", "app.core.llm.coverity_assist_chat_model", "host_context"}
    tree.body = [n for n in tree.body if not (isinstance(n, ast.ImportFrom) and n.module in excluded)]
    module = types.ModuleType("_agentpi_planner_boundary_under_test")
    module.__file__ = str(source_path)
    monkeypatch.setitem(sys.modules, module.__name__, module)

    def unexpected_provider():
        raise AssertionError("local diagnostic must not construct a provider")

    module.__dict__.update(
        AIMessage=Message, HumanMessage=Message, BaseMessage=Message,
        CoverityAssistChatModel=Model, get_model=unexpected_provider,
        build_host_context=lambda: "Controlled test host context; no external probes.",
    )
    exec(compile(tree, str(source_path), "exec"), module.__dict__)
    return module


@pytest.fixture
def executor(tmp_path):
    # Extract the exact implementation bodies; bypass only LangChain decoration
    # and unrelated module-level telemetry/workspace imports.
    wanted = {"_safe_workspace", "_venv_python", "agent_run_python"}
    original = ast.parse(TOOLS.read_text(encoding="utf-8"), str(TOOLS))
    nodes = [n for n in original.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {n.name for n in nodes} == wanted
    for node in nodes:
        node.decorator_list = []
    namespace = dict(Path=Path, os=os, sys=sys, subprocess=subprocess, Optional=Optional,
                     BASE_AGENT_WORKDIR=str(tmp_path))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(TOOLS), "exec"), namespace)
    return namespace["agent_run_python"]


def tool_map(planner, **handlers):
    return {name: planner.NormalizedTool(name, name, fn) for name, fn in handlers.items()}


def test_exact_runtime_prompt_uses_real_python_without_provider(planner, executor, tmp_path):
    async def forbidden(*args, **kwargs):
        raise AssertionError("must not call a network service")

    tools = [
        types.SimpleNamespace(name="public_web_search", ainvoke=forbidden),
        types.SimpleNamespace(name="agentpi_health", ainvoke=forbidden),
        executor,
    ]
    answer = asyncio.run(planner.run_coverity_tool_loop(
        tools=tools, messages=[Message(PROMPT)],
        config={"configurable": {"thread_id": "probe-test"}},
    ))
    assert "return code=0" in answer.content
    assert sys.executable in answer.content
    assert socket.gethostname() in answer.content
    assert str(tmp_path / "probe-test") in answer.content
    assert (tmp_path / "probe-test/runtime_probe.py").is_file()


@pytest.mark.parametrize("prompt", [
    PROMPT,
    "write and run Python code that prints the current directory",
    "build a desktop GUI for my cameras and current devices",
    "write and run a script that prints the latest local log line",
])
def test_local_execution_never_enters_legacy_network_shortcuts(planner, prompt):
    calls = []
    async def bad(arg):
        calls.append(arg)
        raise AssertionError("unexpected shortcut")
    mapping = tool_map(planner, public_web_search=bad, agent_run_shell=bad,
                       agentpi_discover_devices=bad)
    assert asyncio.run(planner._maybe_handle_obvious_direct_task(prompt, mapping, "chat")) is None
    assert calls == []
    assert not planner._looks_like_fresh_info_request(prompt)


@pytest.mark.parametrize("prompt", ["latest Python release", "current weather in Denver", "who won the game today"])
def test_public_information_still_classified_as_public(planner, prompt):
    assert planner._looks_like_fresh_info_request(prompt)


@pytest.mark.parametrize("prompt", [
    "explain this Python script without executing it",
    PROMPT + " and delete the temporary directory",
    "what is the latest Python version?",
])
def test_narrow_probe_does_not_execute_other_requests(planner, prompt):
    assert planner._runtime_probe_payload(prompt) is None


@pytest.mark.parametrize("config,tools,reason", [
    ({}, [], "identity"),
    ({"configurable": {"thread_id": "chat"}}, [], "not bound"),
])
def test_missing_capability_is_not_replaced_by_web_search(planner, config, tools, reason):
    answer = asyncio.run(planner.run_coverity_tool_loop(tools=tools, messages=[Message(PROMPT)], config=config))
    assert "LOCAL_EXECUTION_BLOCKED" in answer.content
    assert reason in answer.content


def test_prefixed_multiline_json_dispatches_once(planner):
    calls = []
    async def probe(**kwargs):
        calls.append(kwargs)
        return "ran once"
    plan = json.dumps({"action": "tool", "tool": "custom_tool", "input": {"value": "a {brace} in a string"}}, indent=2)
    model = Model(["Phase 1: Write the full application file\n" + plan,
                   json.dumps({"action": "final", "final": "Observed one result."})])
    answer = asyncio.run(planner.run_coverity_tool_loop(
        model=model, tools=[types.SimpleNamespace(name="custom_tool", ainvoke=lambda data: probe(**data))],
        messages=[Message("perform a controlled custom task")], max_steps=3,
    ))
    assert answer.content == "Observed one result."
    assert calls == [{"value": "a {brace} in a string"}]


@pytest.mark.parametrize("text", [
    '{"action":"tool","tool":"agent_run_python","input":{"code":"unfinished',
    '{"action":"tool","action":"final","final":"bad duplicate"}',
    '{"action":"tool","tool":"x","input":null}',
    '{"action":"tool","tool":"x"}',
    '{"action":"final","final":""}',
    '[{"action":"tool","tool":"x","input":{}}]',
    '{"action":"tool","tool":"x","input":{}} {"action":"final","final":"also"}',
    '{"wrapper":{"action":"tool","tool":"x","input":{}}}',
    '{"action":"tool","tool":"x","input":{"code":"' + ('x' * 66_000),
], ids=[
    # Pytest includes the node ID in PYTEST_CURRENT_TEST. Keep payloads out of
    # IDs: Windows rejects an environment-variable value above 32,767 chars.
    "truncated-code",
    "duplicate-action",
    "null-input",
    "missing-input",
    "empty-final",
    "top-level-array",
    "multiple-actions",
    "nested-action",
    "oversized-payload",
])
def test_malformed_or_ambiguous_actions_are_not_dispatched(planner, text):
    assert planner._pick_action_payload(text) is None


def test_incomplete_gui_response_retries_then_stops_without_execution(planner):
    calls = []
    async def run_python(arg):
        calls.append(arg)
    incomplete = 'Phase 1: {"action":"tool","tool":"agent_run_python","input":{"code":"unterminated'
    model = Model([incomplete, incomplete])
    answer = asyncio.run(planner.run_coverity_tool_loop(
        model=model, tools=[types.SimpleNamespace(name="agent_run_python", ainvoke=run_python)],
        messages=[Message("build a GUI application")], max_steps=4,
    ))
    assert "PLANNER_PROTOCOL_INVALID" in answer.content
    assert incomplete not in answer.content
    assert not calls
    assert len(model.calls) == 2


def test_repair_after_rejected_plan_does_not_execute_broken_code(planner):
    calls = []
    async def write(arg):
        calls.append(arg)
        return "file created"
    model = Model([
        '{"action":"tool","tool":"writer","input":{"code":"bad',
        json.dumps({"action": "tool", "tool": "writer", "input": {"code": "pass"}}),
        json.dumps({"action": "final", "final": "Received writer result."}),
    ])
    answer = asyncio.run(planner.run_coverity_tool_loop(
        model=model, tools=[types.SimpleNamespace(name="writer", ainvoke=write)],
        messages=[Message("build an app")], max_steps=3,
    ))
    assert answer.content == "Received writer result."
    assert calls == [{"code": "pass"}]


def test_regular_python_work_reaches_planner_then_local_tool(planner):
    called = []
    async def local(arg):
        called.append("local")
        return "actual result"
    async def web(arg):
        called.append("web")
        raise AssertionError("wrong route")
    model = Model([
        json.dumps({"action": "tool", "tool": "agent_run_python", "input": {"code": "print(42)"}}),
        json.dumps({"action": "final", "final": "Observed local result."}),
    ])
    answer = asyncio.run(planner.run_coverity_tool_loop(
        model=model, tools=[types.SimpleNamespace(name="agent_run_python", ainvoke=local),
                            types.SimpleNamespace(name="public_web_search", ainvoke=web)],
        messages=[Message("write and run Python that prints the current process id")], max_steps=3,
    ))
    assert called == ["local"]
    assert "Observed" in answer.content


def test_sync_tool_is_offloaded_from_event_loop(planner):
    main_thread = threading.get_ident()
    def sync_tool(value):
        return threading.get_ident(), value
    thread_id, value = asyncio.run(planner._invoke_tool(sync_tool, {"value": 9}))
    assert thread_id != main_thread
    assert value == 9


def test_internal_typeerror_does_not_trigger_second_execution(planner):
    calls = []
    def failing(*args, **kwargs):
        calls.append((args, kwargs))
        raise TypeError("internal failure after a side effect")
    with pytest.raises(TypeError, match="internal failure"):
        asyncio.run(planner._invoke_tool(failing, {"value": 1}))
    assert len(calls) == 1


def test_dispatch_logs_tool_identity_not_input(planner, caplog):
    async def fixture(value):
        return value
    caplog.set_level("INFO", logger=planner.__name__)
    assert asyncio.run(planner._invoke_tool(fixture, {"value": "private-payload-fixture"})) == "private-payload-fixture"
    assert "TOOL_DISPATCH tool=fixture state=returned" in caplog.text
    assert "private-payload-fixture" not in caplog.text


def test_final_can_contain_data_json_not_tool_directives(planner):
    payload = {"action": "final", "final": '{"devices": [], "status": "partial"}'}
    assert planner._pick_action_payload(json.dumps(payload)) == payload


def test_nonfinite_json_input_is_rejected(planner):
    assert planner._pick_action_payload('{"action":"tool","tool":"x","input":{"value":NaN}}') is None


def test_action_case_ids_are_bounded_without_reducing_payloads():
    """Test data stays large; collection metadata must remain small on Windows."""
    marks = test_malformed_or_ambiguous_actions_are_not_dispatched.pytestmark
    parametrizations = [mark for mark in marks if mark.name == "parametrize"]
    assert len(parametrizations) == 1
    mark = parametrizations[0]
    payloads = mark.args[1]
    ids = mark.kwargs.get("ids", [])
    assert len(ids) == len(payloads) == 9
    assert len(set(ids)) == len(ids)
    assert all(isinstance(case_id, str) and case_id.isascii() and 0 < len(case_id) <= 64 for case_id in ids)
    oversized = payloads[ids.index("oversized-payload")]
    assert oversized == '{"action":"tool","tool":"x","input":{"code":"' + ('x' * 66_000)
    assert len(oversized) > 65_536  # Still exercises the production size guard.


def test_cachepoint_metadata_is_not_user_text(planner):
    content = [
        {"type": "text", "text": PROMPT},
        {"cachePoint": {"type": "default"}},
    ]
    assert planner._content_to_text(content) == PROMPT
    assert planner._extract_last_user_text([Message(content)]) == PROMPT
    assert planner._runtime_probe_payload(planner._content_to_text(content)) is not None


def test_search_diagnostic_uses_status_tool_without_provider(planner):
    calls = []

    async def status_tool(payload):
        calls.append(payload)
        return json.dumps({
            "status": "healthy",
            "configured_mode": "direct",
            "effective_mode": "direct",
            "probe": {"ok": True, "backend": "direct", "source": "ddg-html", "result_count": 1},
        })

    tools = [types.SimpleNamespace(name="public_web_search_status", ainvoke=status_tool)]
    answer = asyncio.run(planner.run_coverity_tool_loop(
        tools=tools,
        messages=[Message("diagnose your search tool first")],
        config={"configurable": {"thread_id": "search-diagnostic"}},
    ))

    assert "Public web search diagnostics (actual runtime output)" in answer.content
    assert '"effective_mode": "direct"' in answer.content
    assert '"source": "ddg-html"' in answer.content
    assert calls == [{"probe": False}]


def test_fresh_search_returns_actual_tool_output_without_model(planner):
    calls = []

    async def search_tool(query):
        calls.append(query)
        return json.dumps({
            "query": query,
            "backend": "direct",
            "source": "ddg-lite",
            "cache": {"hit": False},
            "results": [
                {
                    "title": "Python 3.13 fixture",
                    "url": "https://docs.python.org/3.13/",
                    "snippet": "fixture release notes",
                }
            ],
        })

    tools = [types.SimpleNamespace(name="public_web_search", ainvoke=search_tool)]
    answer = asyncio.run(planner.run_coverity_tool_loop(
        tools=tools,
        messages=[Message("search the web for the latest Python 3.13 release notes and give me the source links")],
        config={"configurable": {"thread_id": "search-grounding"}},
    ))

    assert answer.content.startswith("Public web search result (actual tool output):")
    assert "https://docs.python.org/3.13/" in answer.content
    assert "All connection attempts failed" not in answer.content
    assert calls == ["search the web for the latest Python 3.13 release notes and give me the source links"]


def test_try_again_reuses_previous_fresh_search_without_model(planner):
    calls = []

    async def search_tool(query):
        calls.append(query)
        return json.dumps({
            "query": query,
            "backend": "direct",
            "source": "ddg-lite",
            "cache": {"hit": True},
            "results": [
                {
                    "title": "Retry fixture",
                    "url": "https://python.org/",
                    "snippet": "fixture",
                }
            ],
        })

    prior = "search the web for the latest Python 3.13 release notes and give me the source links"
    tools = [types.SimpleNamespace(name="public_web_search", ainvoke=search_tool)]
    answer = asyncio.run(planner.run_coverity_tool_loop(
        tools=tools,
        messages=[
            Message(prior),
            Message("try again"),
        ],
        config={"configurable": {"thread_id": "search-retry"}},
    ))

    assert answer.content.startswith("Public web search result (actual tool output):")
    assert "https://python.org/" in answer.content
    assert calls == [prior]
