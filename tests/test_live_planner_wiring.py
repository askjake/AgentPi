"""Import the real production CALLERS and dispatch modules.

Only external providers/framework dependencies are stubbed in this portable
suite. The deployed tests_windows suite also exercises the real framework and
registry with a fake model. Never select the implementation by an AST path.
"""
from __future__ import annotations
import asyncio
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'dish-chat/backend'
PROMPT = 'write and run a small Python script that prints the Python executable, Python version, hostname, and current working directory'


class Human:
    type = 'human'
    def __init__(self, content, **kwargs):
        self.content = content
        self.tool_calls = []


class AI(Human):
    type = 'ai'


class System(Human):
    type = 'system'


class Tool(Human):
    type = 'tool'


class Model:
    _llm_type = 'coverity-assist'
    def __init__(self, replies=()):
        self.replies = list(replies)
        self.calls = 0
    def bind_tools(self, tools):
        return self
    async def ainvoke(self, messages, config=None):
        self.calls += 1
        if not self.replies:
            raise AssertionError('Unexpected provider request')
        return AI(self.replies.pop(0))


@pytest.fixture
def runtime(tmp_path):
    monkeypatch = pytest.MonkeyPatch()
    saved = {k: v for k, v in sys.modules.items() if k == 'app' or k.startswith('app.')}
    for key in saved:
        sys.modules.pop(key)
    monkeypatch.syspath_prepend(str(BACKEND))
    inserted = []
    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, m)
        inserted.append(name)
        return m
    messages = dict(BaseMessage=Human, HumanMessage=Human, AIMessage=AI,
                    SystemMessage=System, ToolMessage=Tool)
    mod('langchain_core.messages', **messages)
    mod('langchain_core', __path__=[])
    mod('langgraph', __path__=[])
    mod('langgraph.graph', END='__end__', START='__start__', StateGraph=object, __path__=[])
    mod('langgraph.graph.message', add_messages=lambda a, b: a+b)
    mod('langgraph.prebuilt', ToolNode=object, tools_condition=lambda s: '__end__')
    mod('langgraph.checkpoint', __path__=[])
    mod('langgraph.checkpoint.base', BaseCheckpointSaver=object)
    settings = types.SimpleNamespace(MAX_OUTPUT_COUNT=2048, MAX_CACHEPOINT_CNT=4,
                                     PLLM_PROVIDER='coverity-assist', AGENT_MODE_MODEL=None)
    mod('app.config', get_settings=lambda: settings)
    model = Model()
    async def unexpected(*args, **kwargs):
        raise AssertionError('Unexpected remote path')
    mod('app.core.llm', get_model=lambda **kw: model, invoke_with_retry=unexpected, __path__=[])
    mod('app.core.llm.coverity_assist_chat_model', CoverityAssistChatModel=Model)
    mod('app.core.utils', get_datestr_now=lambda: 'test')
    mod('app.core.prompt_compression', get_prompt_compressor=lambda: types.SimpleNamespace(needs_compression=lambda m: False))
    mod('app.agent.db_utils', get_checkpointer=lambda: None)
    mod('app.agent.utils', aggressive_cachept=lambda m, _: m, cleanup_cachept=lambda m: None,
        set_model_config=lambda *a: None)
    mod('app.agent.methodology_utils', inject_methodology_into_prompt=lambda p, u: p)
    mod('app.agent.agents.utils', get_prompt=lambda _: 'Test system prompt')
    mod('app.agent.agents.host_context', build_host_context=lambda: 'offline fixture')
    spy = types.SimpleNamespace(thought=lambda *a: None, context_update=lambda *a: None, decision=lambda *a, **k: None)
    mod('app.agent_mode.thought_interceptor', interceptor=spy)

    class LocalTool:
        name = 'agent_run_python'
        description = 'Controlled local subprocess fixture'
        async def ainvoke(self, payload):
            workspace = tmp_path / payload['chat_id']
            workspace.mkdir(parents=True, exist_ok=True)
            script = workspace / payload['filename']
            script.write_text(payload['code'], encoding='utf-8')
            done = await asyncio.to_thread(subprocess.run, [sys.executable, str(script)],
                                          cwd=workspace, capture_output=True, text=True, timeout=10)
            return f'return code={done.returncode}\n{done.stdout}{done.stderr}'

    class McopTool:
        name = 'agent_spawn_task'
        description = 'Controlled MCOP child-spawn fixture'
        def __init__(self):
            self.calls = []
        async def ainvoke(self, payload):
            self.calls.append(dict(payload))
            return json.dumps({
                'contract': 'agentpi-mcop-v1',
                'task_id': payload['task_id'],
                'status': 'completed',
                'iterations_used': 1,
                'packet_path': f"_mcop/task_{payload['task_id']}/tool_evidence_packet.json",
                'facts': [{
                    'claim': f"MCOP_SMOKE_EXECUTED:{payload['task_id']}",
                    'confidence': 'high',
                    'source': 'agentpi_mcop_runtime',
                }],
                'gaps': [],
                'errors': [],
                'summary': 'controlled child fixture complete',
            })

    mcop_tool = McopTool()
    tools = [LocalTool(), mcop_tool, types.SimpleNamespace(name='public_web_search', ainvoke=unexpected)]
    mod('app.agent.agents.tools', get_tools_set=lambda kind: tools if kind == 'agent_mode' else [])
    mod('app.agent_mode.tools', BASE_AGENT_WORKDIR=str(tmp_path))
    try:
        # All three paths and their imports resolve from the real source tree.
        rag = importlib.import_module('app.agent.agents.agentic_rag')
        mode = importlib.import_module('app.agent_mode.agent')
        live = importlib.import_module('app.agent.agents.coverity_tool_loop')
        impl = importlib.import_module('app.agent.agents.coverity_tool_loop_token_limit')
        yield types.SimpleNamespace(rag=rag, mode=mode, live=live, impl=impl, model=model,
                                    tools=tools, mcop_tool=mcop_tool, base=tmp_path)
    finally:
        monkeypatch.undo()
        for key in list(sys.modules):
            if key == 'app' or key.startswith('app.'):
                sys.modules.pop(key, None)
        sys.modules.update(saved)


def run_chat(rt, prompt, prior=None):
    return asyncio.run(rt.rag.call_model(
        {'messages': [*(prior or []), Human(prompt)], 'model_config': {}},
        {'configurable': {'thread_id': 'test-chat'}}))['messages'][0].content


def test_chat_import_is_the_live_boundary(runtime):
    assert runtime.rag.run_coverity_tool_loop is runtime.live.run_coverity_tool_loop
    assert runtime.live.implementation is runtime.impl
    assert runtime.mode.run_coverity_tool_loop is runtime.live.run_coverity_tool_loop


def test_real_chat_node_runs_probe_without_web_or_llm(runtime):
    out = run_chat(runtime, PROMPT)
    assert 'Local agent_run_python result' in out
    assert 'return code=0' in out
    assert sys.executable in out
    assert socket.gethostname() in out
    assert str(runtime.base / 'test-chat') in out
    assert (runtime.base / 'test-chat/runtime_probe.py').is_file()
    assert runtime.model.calls == 0


def test_real_agent_mode_node_uses_same_planner(runtime):
    answer = asyncio.run(runtime.mode.agent_mode_node(
        {'messages': [Human(PROMPT)], 'chat_id': 'mode-chat', 'iterations': 0}, config=None))
    assert 'return code=0' in answer['messages'][0].content
    assert (runtime.base / 'mode-chat/runtime_probe.py').is_file()
    assert runtime.model.calls == 0


def test_mcop_description_is_read_only_and_reports_implementation(runtime):
    out = run_chat(runtime, 'describe your MCOP backend functionality.')
    assert 'Multi-Conversation Orchestration Protocol' in out
    assert 'implemented in this AgentPi revision' in out
    assert 'agent_spawn_task' in out
    assert 'This description request did not spawn a child' in out
    assert 'Multi-Channel' not in out
    assert runtime.mcop_tool.calls == []
    assert runtime.model.calls == 0


def test_mcop_demo_followup_dispatches_exactly_one_spawn(runtime):
    # Exact live UI shape: the immediately preceding assistant turn names
    # MCOP; the pronoun follow-up itself does not.
    out = run_chat(runtime, 'please test and exhibit it in action',
                   [AI('MCOP means Multi-Conversation Orchestration Protocol. It is implemented.')])
    assert out.startswith('MCOP demonstration verified (actual agent_spawn_task output)')
    assert 'MCOP_SMOKE_EXECUTED:' in out
    assert len(runtime.mcop_tool.calls) == 1
    call = runtime.mcop_tool.calls[0]
    assert call['chat_id'] == 'test-chat'
    assert call['task_id'].startswith('mcop-demo-')
    assert call['context_files'] == '[]'
    assert call['max_iters'] == 2
    assert 'controlled MCOP smoke test' in call['task_prompt']
    assert runtime.model.calls == 0


def test_explicit_mcop_demo_needs_no_history(runtime):
    out = run_chat(runtime, 'test MCOP in action')
    assert out.startswith('MCOP demonstration verified (actual agent_spawn_task output)')
    assert len(runtime.mcop_tool.calls) == 1
    assert runtime.model.calls == 0


def test_mcop_demo_rejects_completed_receipt_without_required_fact(runtime):
    original = runtime.mcop_tool.ainvoke

    async def incomplete(payload):
        runtime.mcop_tool.calls.append(dict(payload))
        return json.dumps({
            'contract': 'agentpi-mcop-v1',
            'task_id': payload['task_id'],
            'status': 'completed',
            'iterations_used': 1,
            'packet_path': f"_mcop/task_{payload['task_id']}/tool_evidence_packet.json",
            'facts': [],
            'gaps': [],
            'errors': [],
            'summary': 'looks complete but lacks the deterministic proof fact',
        })

    runtime.mcop_tool.ainvoke = incomplete
    try:
        out = run_chat(runtime, 'test MCOP in action')
    finally:
        runtime.mcop_tool.ainvoke = original
    assert out.startswith('MCOP_DEMO_INCOMPLETE:')
    assert 'missing required high-confidence fact' in out
    assert len(runtime.mcop_tool.calls) == 1


def test_mcop_demo_rejects_model_authored_high_fact_without_runtime_source(runtime):
    original = runtime.mcop_tool.ainvoke

    async def spoofed(payload):
        runtime.mcop_tool.calls.append(dict(payload))
        return json.dumps({
            'contract': 'agentpi-mcop-v1',
            'task_id': payload['task_id'],
            'status': 'completed',
            'iterations_used': 1,
            'packet_path': f"_mcop/task_{payload['task_id']}/tool_evidence_packet.json",
            'facts': [{
                'claim': f"MCOP_SMOKE_EXECUTED:{payload['task_id']}",
                'confidence': 'high',
                'source': 'model_claim',
            }],
            'gaps': [],
            'errors': [],
            'summary': 'model tried to assert verification',
        })

    runtime.mcop_tool.ainvoke = spoofed
    try:
        out = run_chat(runtime, 'test MCOP in action')
    finally:
        runtime.mcop_tool.ainvoke = original
    assert out.startswith('MCOP_DEMO_INCOMPLETE:')
    assert 'missing required high-confidence fact' in out


def test_generic_demo_without_mcop_context_is_not_hijacked(runtime):
    runtime.model.replies = [json.dumps({'action': 'final', 'final': 'ordinary test response'})]
    out = run_chat(runtime, 'please test and exhibit it in action',
                   [AI('Here is the Python application I just described.')])
    assert out == 'ordinary test response'
    assert runtime.mcop_tool.calls == []
    assert runtime.model.calls == 1


def test_missing_file_followup_reads_disk_not_assistant_claims(runtime):
    out = run_chat(runtime, 'did you finish?',
                   [Human('create a desktop app'), AI('home_manager.py written, 26347 bytes; shortcut created')])
    assert 'ARTIFACT_READBACK_ONLY' in out
    assert 'workspace_not_found' in out
    assert 'No syntax test' in out
    assert not (runtime.base / 'test-chat').exists()
    assert runtime.model.calls == 0


def test_existing_file_not_certified_as_complete(runtime):
    workspace = runtime.base / 'test-chat'; workspace.mkdir()
    f = workspace/'home_manager.py'; f.write_text('not valid python\n', encoding='utf-8')
    out = run_chat(runtime, 'did you finish?', [Human('write a GUI app')])
    assert str(f) in out
    assert hashlib.sha256(f.read_bytes()).hexdigest() in out
    assert 'No syntax test' in out
    assert runtime.model.calls == 0


def test_model_cannot_certify_missing_local_artifact(runtime):
    runtime.model.replies = [json.dumps({'action':'final', 'final':'COMPLETE: home_manager.py written. Shortcut created.'})]
    out = run_chat(runtime, 'build a desktop application')
    assert 'ARTIFACT_READBACK_ONLY' in out
    assert 'workspace_not_found' in out
    assert 'COMPLETE:' not in out


def test_contract_identifies_loaded_implementation(runtime):
    info = runtime.live.execution_identity()
    assert info['contract'] == 'agentpi-live-planner-v1'
    assert info['mcop']['implemented_in_this_revision'] is True
    assert info['mcop']['contract'] == 'agentpi-mcop-v1'
    assert info['loaded_implementation_sha256'] == hashlib.sha256(Path(runtime.impl.__file__).read_bytes()).hexdigest()
    assert 'bearer' not in json.dumps(info).lower()


@pytest.mark.parametrize('identity', ['../other', '/tmp', 'x/y', 'x\\y', '', None], ids=['traversal','absolute','slash','backslash','empty','none'])
def test_readback_cannot_cross_workspace_boundary(runtime, identity):
    module = importlib.import_module('app.agent.agents.artifact_readback')
    report = module.readback(runtime.base, identity)
    assert report['status'] == 'invalid_workspace_identity'
    assert not report['complete_scan']


def test_readback_skips_secret_files_and_venvs(runtime):
    module = importlib.import_module('app.agent.agents.artifact_readback')
    ws=runtime.base/'test-chat';ws.mkdir()
    (ws/'.env').write_text('PASSWORD=do-not-output')
    (ws/'app.py').write_text('print(1)')
    (ws/'.venv').mkdir();(ws/'.venv/dependency.py').write_text('do-not-scan')
    report=module.readback(runtime.base,'test-chat')
    assert len(report['artifacts'])==1
    assert 'do-not-output' not in json.dumps(report)
    assert report['artifacts'][0]['path']==str(ws/'app.py')


def test_readback_rejects_symlink_workspace(runtime):
    module=importlib.import_module('app.agent.agents.artifact_readback')
    other=runtime.base/'other';other.mkdir()
    try:
        (runtime.base/'test-chat').symlink_to(other, target_is_directory=True)
    except OSError:
        pytest.skip('host does not permit symlinks')
    assert module.readback(runtime.base,'test-chat')['status']=='workspace_link_rejected'


def test_readback_bounded_large_file(runtime):
    module=importlib.import_module('app.agent.agents.artifact_readback')
    ws=runtime.base/'test-chat';ws.mkdir()
    with (ws/'huge.py').open('wb') as handle:
        handle.truncate(module._MAX_BYTES+1)
    report=module.readback(runtime.base,'test-chat')
    assert report['artifacts'][0]['sha256'] is None
    assert not report['complete_scan']


def test_verifier_rejects_old_runtime_hash(runtime):
    path=ROOT/'deployment/windows/verify-live-planner.py'
    spec=importlib.util.spec_from_file_location('runtime_verify_fixture',path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    report=runtime.live.execution_identity()
    report.update(chat_binding_matches=True, agent_mode_binding_matches=True)
    mcop_root = ROOT/'dish-chat/backend/app/agent_mode'
    report['mcop'].update({
        'registry_binding_matches': True,
        'bound_tool_names': list(runtime.live.MCOP_TOOL_NAMES),
        'max_depth': 1,
        'loaded_child_sha256': hashlib.sha256((mcop_root/'child_conversation.py').read_bytes()).hexdigest(),
        'loaded_tools_sha256': hashlib.sha256((mcop_root/'mcop_tools.py').read_bytes()).hexdigest(),
        'loaded_packets_sha256': hashlib.sha256((mcop_root/'orchestration_packets.py').read_bytes()).hexdigest(),
    })
    module.verify(ROOT,report)
    report['loaded_entrypoint_sha256']='0'*64
    with pytest.raises(ValueError,match='Running process/source mismatch'):
        module.verify(ROOT,report)


def test_mcop_child_planner_protocol_unwraps_tool_evidence_packet(runtime):
    packet = {
        'packet_type': 'tool_evidence',
        'task_id': 'child-protocol',
        'worker_role': 'tool_worker',
        'status': 'completed',
        'tool_families_used': [],
        'tools_called': [],
        'raw_artifacts': [],
        'facts': [{'claim': 'portable child packet', 'confidence': 'high'}],
        'inferences': [],
        'gaps': [],
        'errors': [],
        'next_recommended_step': '',
        'summary': 'portable packet complete',
    }
    runtime.model.replies = [
        json.dumps({'action': 'final', 'final': json.dumps(packet)})
    ]
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(
        model=runtime.model,
        tools=[tool for tool in runtime.tools if tool.name != 'agent_spawn_task'],
        messages=[
            System('Task id: child-protocol'),
            Human('Return a controlled MCOP child evidence packet.'),
        ],
        config={'configurable': {'thread_id': 'child-parent', 'mcop_child': True}},
        max_steps=2,
    ))
    parsed = json.loads(answer.content)
    assert parsed['packet_type'] == 'tool_evidence'
    assert parsed['task_id'] == 'child-protocol'
    assert parsed['status'] == 'completed'
    assert runtime.model.calls == 1


def test_mcop_child_prompt_includes_nested_final_contract(runtime):
    prompt = runtime.impl._build_planner_prompt(
        'child task',
        '',
        'Task id: prompt-contract',
        [],
        [],
        'parent-chat',
        mcop_child=True,
    )
    assert 'MCOP child finalization contract:' in prompt
    assert 'final field must be a STRING' in prompt
    assert 'Do NOT emit ToolEvidencePacket as the top-level planner object' in prompt


def test_mcop_child_context_bypasses_parent_demo_interceptor(runtime):
    runtime.model.replies = [
        json.dumps({'action': 'final', 'final': 'child planner final'})
    ]
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(
        model=runtime.model,
        tools=[tool for tool in runtime.tools if tool.name != 'agent_spawn_task'],
        messages=[Human('Perform a controlled MCOP smoke test and return evidence.')],
        config={'configurable': {'thread_id': 'child-parent', 'mcop_child': True}},
        max_steps=2,
    ))
    assert answer.content == 'child planner final'
    assert runtime.mcop_tool.calls == []
    assert runtime.model.calls == 1


def test_mcop_question_helper_has_no_runtime_scope_dependency(runtime):
    assert runtime.live._mcop_question('describe MCOP', []) is True
    assert runtime.live._mcop_question('test MCOP in action', []) is False
    assert runtime.live._mcop_question('write and run Python', []) is False


def test_mcop_implementation_request_is_not_intercepted(runtime):
    assert not runtime.live._mcop_question('implement MCOP for this agent', [])
