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


HTTP_EVIDENCE = '''Request URL https://example.invalid/api/conversations
Request method GET
Status code 200 OK
Remote address 44.255.252.90:443
connection keep-alive
'''


@pytest.mark.parametrize('continuation', ['proceed', 'continue', 'go ahead', 'do it', 'yes', 'yes, continue', 'keep going', 'carry on', 'resume'])
def test_executive_continuation_with_http_evidence(runtime, continuation):
    calls, prompts = [], []
    async def probe(payload):
        calls.append(payload)
        return 'ICMP timeout'
    async def model(messages, config=None):
        prompts.append(messages[0].content)
        return AI(json.dumps({'action': 'final', 'final': 'WebSocket framing remains to be inspected.'}))
    runtime.model.ainvoke = model
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(
        model=runtime.model, tools=[types.SimpleNamespace(name='agent_check_device', ainvoke=probe)],
        messages=[Human('Investigate the voice service and determine how to inject TTS audio.'),
                  AI('Next I need to inspect the WebSocket framing.'), Human(continuation+'\n\n'+HTTP_EVIDENCE)],
        config={'configurable': {'thread_id': 'test-chat'}}))
    assert calls == []
    assert 'WebSocket' in answer.content
    assert 'Continuation' in prompts[0]
    assert 'inject TTS audio' in prompts[0]
    assert 'Supplied evidence' in prompts[0]
    assert HTTP_EVIDENCE.strip() in prompts[0]


def test_executive_explicit_port_probe(runtime):
    calls = []
    async def probe(payload):
        calls.append(payload)
        return 'TCP connection succeeded'
    runtime.model.replies = ['TCP connection succeeded']
    asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='agent_check_device', ainvoke=probe)],
        messages=[Human('check whether 44.255.252.90 port 443 is reachable')]))
    assert calls == [{'ip_address': '44.255.252.90', 'check_type': 'port', 'port': 443}]


@pytest.mark.parametrize('text', [HTTP_EVIDENCE, 'connected to 44.255.252.90', 'connection 44.255.252.90', '44.255.252.90 port 443', '```\nping 44.255.252.90\n```'])
def test_executive_passive_text_is_not_probe(runtime, text):
    assert not runtime.impl._looks_like_device_probe_request(text)


def test_executive_partial_finalization_reads_real_files(runtime):
    runtime.model.replies = [
        json.dumps({'action': 'tool', 'tool': 'agent_run_python', 'input': {
            'chat_id': 'test-chat', 'filename': 'commands.py', 'code': "from pathlib import Path\nPath('command.wav').write_bytes(b'RIFF-test')"}}),
        json.dumps({'action': 'tool', 'tool': 'agent_run_python', 'input': {
            'chat_id': 'test-chat', 'filename': 'verify.py', 'code': "print('observed fixture')"}}),
        '{broken', '{broken']
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=runtime.tools, messages=[Human('generate files containing customer voice commands')],
        config={'configurable': {'thread_id': 'test-chat'}}, max_steps=4))
    assert answer.content.startswith('PLANNER_FINALIZATION_PARTIAL')
    assert 'agent_run_python' in answer.content
    assert 'command.wav' in answer.content
    assert 'ARTIFACT_READBACK_ONLY' in answer.content
    assert 'not a completion certificate' in answer.content
    assert runtime.live.COUNTERS['artifact_readback'] == 1


def test_executive_no_execution_protocol_failure(runtime):
    runtime.model.replies = ['{broken', '{broken']
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        messages=[Human('inspect the voice protocol')], max_steps=2))
    assert answer.content.startswith('PLANNER_PROTOCOL_INVALID')
    assert runtime.live.COUNTERS['artifact_readback'] == 0


def test_executive_secret_execution_and_context_copies(runtime):
    original = {'code': 'password="TEST_SECRET"\n# Authorization: Bearer TEST_REDACT_ME'}
    calls, prompts = [], []
    replies = [json.dumps({'action': 'tool', 'tool': 'agent_run_python', 'input': original}),
               json.dumps({'action': 'final', 'final': 'Tool returned.'})]
    async def model(messages, config=None):
        prompts.append(messages[0].content)
        return AI(replies.pop(0))
    async def execute(payload):
        calls.append(payload)
        return {'access_token': 'TEST_RESULT_SECRET', 'status': 'returned'}
    runtime.model.ainvoke = model
    asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='agent_run_python', ainvoke=execute)],
        messages=[Human('run a Python script')]))
    assert calls == [original]
    assert '[REDACTED]' in prompts[1]
    assert all(secret not in prompts[1] for secret in ['TEST_SECRET', 'TEST_REDACT_ME', 'TEST_RESULT_SECRET'])


def test_executive_evidence_scope_rules_reach_model(runtime):
    prompt = runtime.impl._build_planner_prompt('proceed\n'+HTTP_EVIDENCE+'content-type: text/html',
        'User: Determine voice transport; REST /turns persists records, WebSocket framing unknown.', '', [], [], None)
    assert 'ICMP' in prompt and 'observation time' in prompt
    assert 'text/html' in prompt and 'JSON health' in prompt
    assert 'persistence' in prompt and 'transport' in prompt and 'audio framing' in prompt


@pytest.mark.parametrize('value', [
    'Authorization: Bearer TEST_SECRET', 'Bearer TEST_SECRET',
    '"access_token": "TEST_SECRET"', "'id_token': 'TEST_SECRET'",
    'refresh_token=TEST_SECRET', 'password="TEST_SECRET"',
    'passwd=TEST_SECRET', 'secret=TEST_SECRET', 'api_key=TEST_SECRET',
    'api token: TEST_SECRET', 'AWS_SECRET_ACCESS_KEY=TEST_SECRET',
    'Cookie: session=TEST_SECRET; other=TEST_SECRET', 'session_token=TEST_SECRET',
    'ACCESS_TOKEN = "TEST_SECRET"',
])
def test_executive_secret_forms(runtime, value):
    result = runtime.impl.redact_sensitive_text(value)
    assert 'TEST_SECRET' not in result
    assert '[REDACTED]' in result


def test_executive_continuation_context_is_bounded(runtime):
    messages = [Human('old objective must disappear')] + [AI('recent evidence') for _ in range(12)]
    assert 'old objective' not in runtime.impl._render_recent_transcript(messages)
    assert len(runtime.impl._render_recent_transcript([Human('x'*100000)])) < 4100


def test_executive_partial_readback_never_claims_existing_file_created(runtime):
    workspace = runtime.base / 'test-chat'
    workspace.mkdir()
    (workspace / 'old.py').write_text('# old fixture')
    async def error_result(payload):
        return {'error': 'execution refused', 'password': 'TEST_SECRET'}
    runtime.model.replies = [json.dumps({'action': 'tool', 'tool': 'agent_run_python', 'input': {}}), '{bad', '{bad']
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='agent_run_python', ainvoke=error_result)],
        messages=[Human('create a Python script')], config={'configurable': {'thread_id': 'test-chat'}}))
    assert answer.content.startswith('PLANNER_FINALIZATION_PARTIAL')
    assert 'execution refused' in answer.content
    assert 'TEST_SECRET' not in answer.content
    assert 'old.py' not in answer.content
    assert 'Older workspace artifacts omitted: 1' in answer.content
    assert 'does not prove creation this turn' in answer.content


def test_executive_summarizer_redacts_before_truncating(runtime):
    prompts = []
    async def model(messages, config=None):
        prompts.append(messages[0].content)
        return AI('returned')
    runtime.model.ainvoke = model
    asyncio.run(runtime.impl._summarize_tool_result(runtime.model, 'report',
        'password="' + 'TEST_SECRET'*2000 + '"'))
    assert 'TEST_SECRET' not in prompts[0]


def test_executive_evidence_does_not_start_mcop_demo(runtime):
    runtime.model.replies = [json.dumps({'action': 'final', 'final': 'Evidence received.'})]
    asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model, tools=runtime.tools,
        messages=[Human('proceed\n```\ntest MCOP in action\n```')]))
    assert runtime.mcop_tool.calls == []


@pytest.mark.parametrize('instruction', ['login to the voice demo', 'log the response', 'evidence should be checked'])
def test_executive_normal_instruction_not_header_prefix(runtime, instruction):
    assert runtime.impl.split_instruction_and_evidence(instruction).instruction_text == instruction


@pytest.mark.parametrize('text', ['proceed', 'proceed\n```\nStatus code 200 OK\n```'])
def test_executive_plain_continuation_uses_bounded_prior_objective(runtime, text):
    prompts = []
    async def model(messages, config=None):
        prompts.append(messages[0].content)
        return AI('{"action":"final","final":"Inspect protocol next."}')
    runtime.model.ainvoke = model
    asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        messages=[Human('Investigate voice audio framing'), AI('Next inspect the WebSocket handshake'), Human(text)]))
    assert 'Investigate voice audio framing' in prompts[0]
    assert 'Next inspect the WebSocket handshake' in prompts[0]
    assert 'Continuation:' in prompts[0]


def test_turn_recovery_excludes_historical_workspace(runtime):
    ws = runtime.base / 'test-chat'; ws.mkdir()
    for name in ['old_cart_file.py', 'old_rtr_file.py', 'old_voice_file.mp3']:
        (ws / name).write_text('old')
    runtime.model.replies = [json.dumps({'action': 'tool', 'tool': 'agent_run_python', 'input': {
        'chat_id': 'test-chat', 'filename': name, 'code': 'print("inspected")'}})
        for name in ['find_ws_voice.py', 'read_voice_transport.py']] + ['{invalid', '{invalid']
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model, tools=runtime.tools,
        messages=[Human('Investigate the voice-demo Andromeda transport')],
        config={'configurable': {'thread_id': 'test-chat'}}, max_steps=4))
    assert answer.content.startswith('PLANNER_FINALIZATION_PARTIAL')
    assert 'find_ws_voice.py' in answer.content and 'read_voice_transport.py' in answer.content
    assert 'created_this_turn' in answer.content
    assert all(name not in answer.content for name in ['old_cart_file.py', 'old_rtr_file.py', 'old_voice_file.mp3'])
    assert 'Older workspace artifacts omitted: 3' in answer.content


def test_turn_snapshot_detects_modified_with_preserved_metadata(runtime):
    reader = importlib.import_module('app.agent.agents.artifact_readback')
    ws = runtime.base / 'test-chat'; ws.mkdir()
    path = ws / 'analysis.txt'; path.write_text('before')
    stat = path.stat()
    before = reader.readback(runtime.base, 'test-chat')
    path.write_text('after!')
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    delta = reader.turn_changes(before, reader.readback(runtime.base, 'test-chat'))
    assert len(delta['artifacts']) == 1
    assert delta['artifacts'][0]['change'] == 'modified_this_turn'


def test_turn_snapshot_unchanged_and_render_bounds(runtime):
    reader = importlib.import_module('app.agent.agents.artifact_readback')
    ws = runtime.base / 'test-chat'; ws.mkdir()
    for index in range(300):
        (ws / f'old_{index:03}.py').write_text('before')
    before = reader.readback(runtime.base, 'test-chat')
    empty = reader.turn_changes(before, reader.readback(runtime.base, 'test-chat'))
    assert empty['artifacts'] == []
    assert 'old_000.py' not in reader.render_turn(empty)
    for path in ws.iterdir():
        path.write_text('changed')
    delta = reader.turn_changes(before, reader.readback(runtime.base, 'test-chat'), preferred_paths=['old_299.py'])
    assert len(delta['artifacts']) <= reader._MAX_TURN_ARTIFACTS
    assert delta['artifacts'][0]['path'].endswith('old_299.py')
    assert len(reader.render_turn(delta)) <= reader._MAX_TURN_OUTPUT_CHARS
    assert delta['omitted_changes'] > 0


def test_turn_snapshot_incomplete_baseline_does_not_invent_creation(runtime):
    reader = importlib.import_module('app.agent.agents.artifact_readback')
    ws = runtime.base / 'test-chat'; ws.mkdir()
    (ws / 'existing.py').write_text('old')
    after = reader.readback(runtime.base, 'test-chat')
    before = {**after, 'artifacts': [], 'complete_scan': False, 'inventory_complete': False}
    delta = reader.turn_changes(before, after)
    assert delta['artifacts'] == []
    assert not delta['complete_scan']
    assert 'incomplete' in reader.render_turn(delta).lower()


def test_turn_target_identity_survives_local_reference_and_continuation(runtime):
    prompts = []
    replies = [json.dumps({'action': 'tool', 'tool': 'agent_run_python', 'input': {'code': 'print("local reference")'}}),
               json.dumps({'action': 'final', 'final': 'Local audio/webm is a reference hypothesis only.'})]
    async def model(messages, config=None):
        prompts.append(messages[0].content)
        return AI(replies.pop(0))
    async def local(payload):
        return 'AgentPi/dish-chat/frontend/enhanced/static/js/dashboard.js uses MediaRecorder(audio/webm)'
    runtime.model.ainvoke = model
    asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='agent_run_python', ainvoke=local)],
        messages=[Human('Investigate how https://voice-target.example sends audio to wss://andromeda.example/ws'),
                  AI('Inspect the target bundle next.'), Human('proceed')]))
    assert 'Requested target/objective:' in prompts[1]
    assert 'https://voice-target.example' in prompts[1]
    assert 'LOCAL_IMPLEMENTATION' in prompts[1] and 'REFERENCE_SOURCE' in prompts[1]
    assert 'cannot prove' in prompts[1]
    assert 'dashboard.js' in prompts[1]


def test_turn_target_bundle_and_user_evidence_remain_usable(runtime):
    prompt = runtime.impl._build_planner_prompt(
        'Investigate https://voice-target.example\nRequest URL https://voice-target.example/assets/app.js\n'
        'WebSocket URL wss://andromeda.example/ws\nnew MediaRecorder(...) audio/webm', '', '', [], [], None)
    assert 'TARGET_SOURCE' in prompt and 'USER_SUPPLIED_EVIDENCE' in prompt
    assert 'https://voice-target.example/assets/app.js' in prompt
    assert 'may support target-specific claims' in prompt
    assert 'INFERENCE' in prompt


def test_turn_windows_file_inspection_guidance(runtime, monkeypatch):
    monkeypatch.setattr(runtime.impl, 'build_host_context', lambda: 'You are running natively on Windows.')
    prompt = runtime.impl._build_planner_prompt('Recursively inspect the target source files', '', '', [], [], None)
    assert 'dir' in prompt and 'powershell' in prompt
    assert 'bounded filesystem search' in prompt and 'agent_run_python' in prompt


def test_turn_windows_rejected_search_uses_python_without_shell_dispatch(runtime, monkeypatch):
    monkeypatch.setattr(runtime.impl, 'build_host_context', lambda: 'You are running natively on Windows.')
    calls = []
    async def shell(payload):
        calls.append(payload)
        raise AssertionError('unsupported file-search binary must not be dispatched')
    runtime.model.replies = [
        json.dumps({'action': 'tool', 'tool': 'agent_run_shell', 'input': {'command': 'dir /s /b source'}}),
        json.dumps({'action': 'tool', 'tool': 'agent_run_shell', 'input': {'command': 'powershell -Command Get-ChildItem -Recurse'}}),
        json.dumps({'action': 'tool', 'tool': 'agent_run_python', 'input': {
            'chat_id': 'test-chat', 'filename': 'inspect_source.py',
            'code': "from pathlib import Path\nprint([p.name for p in list(Path('.').iterdir())[:10]])"}}),
        json.dumps({'action': 'final', 'final': 'Inspected the bounded local directory.'})]
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[*runtime.tools, types.SimpleNamespace(name='agent_run_shell', ainvoke=shell)],
        messages=[Human('Recursively inspect local source for reference')],
        config={'configurable': {'thread_id': 'test-chat'}}, max_steps=4))
    assert calls == []
    assert (runtime.base / 'test-chat' / 'inspect_source.py').exists()
    assert 'Inspected' in answer.content


def test_turn_snapshot_failure_does_not_dump_historical_files(runtime, monkeypatch):
    ws = runtime.base / 'test-chat'; ws.mkdir()
    (ws / 'old_cart_file.py').write_text('old')
    original = runtime.live._artifact_snapshot
    count = 0
    async def snapshot(chat_id):
        nonlocal count
        count += 1
        if count == 1:
            raise OSError('baseline unavailable')
        return await original(chat_id)
    monkeypatch.setattr(runtime.live, '_artifact_snapshot', snapshot)
    runtime.model.replies = [json.dumps({'action': 'tool', 'tool': 'agent_run_python', 'input': {
        'chat_id': 'test-chat', 'filename': 'inspect.py', 'code': 'print("observed")'}}), '{invalid', '{invalid']
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model, tools=runtime.tools,
        messages=[Human('Investigate voice transport')], config={'configurable': {'thread_id': 'test-chat'}}))
    assert 'baseline_unavailable' in answer.content
    assert 'old_cart_file.py' not in answer.content
    assert 'created_this_turn' not in answer.content


def test_turn_snapshot_touch_is_not_material_edit(runtime):
    reader = importlib.import_module('app.agent.agents.artifact_readback')
    ws = runtime.base / 'test-chat'; ws.mkdir()
    path = ws / 'old.py'; path.write_text('unchanged')
    before = reader.readback(runtime.base, 'test-chat')
    stat = path.stat(); os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
    delta = reader.turn_changes(before, reader.readback(runtime.base, 'test-chat'))
    assert delta['artifacts'] == []
    assert delta['historical_omitted'] == 1


def test_turn_snapshot_large_file_uses_metadata_without_unbounded_hash(runtime):
    reader = importlib.import_module('app.agent.agents.artifact_readback')
    ws = runtime.base / 'test-chat'; ws.mkdir()
    path = ws / 'large.wav'
    with path.open('wb') as handle:
        handle.truncate(reader._MAX_BYTES + 1)
    before = reader.readback(runtime.base, 'test-chat')
    with path.open('ab') as handle:
        handle.write(b'x')
    delta = reader.turn_changes(before, reader.readback(runtime.base, 'test-chat'))
    assert delta['artifacts'][0]['change'] == 'modified_this_turn'
    assert delta['artifacts'][0]['sha256'] is None
    assert 'content not verified' in delta['artifacts'][0]['basis']
    assert not delta['complete_scan']


def test_turn_target_new_request_supersedes_previous_target(runtime):
    target = runtime.impl._resolve_target_identity([
        Human('Investigate https://old.example'), AI('Old target protocol remains unknown'),
        Human('Now investigate https://new.example')])
    assert 'new.example' in target and 'old.example' not in target
    unknown = runtime.impl._resolve_target_identity([Human('proceed')])
    assert 'Unresolved' in unknown


def test_turn_source_fidelity_applies_to_summary(runtime):
    prompts = []
    async def model(messages, config=None):
        prompts.append(messages[0].content)
        return AI('Local code is a reference only; target framing is unverified.')
    runtime.model.ainvoke = model
    asyncio.run(runtime.impl._summarize_tool_result(runtime.model, 'proceed',
        'Local AgentPi dashboard.js uses MediaRecorder/audio-webm',
        target_identity='Investigate https://voice-target.example'))
    assert 'Requested target/objective: Investigate https://voice-target.example' in prompts[0]
    assert 'LOCAL_IMPLEMENTATION' in prompts[0] and 'cannot prove' in prompts[0]


def test_turn_target_bundle_is_retained_in_following_planner_context(runtime):
    prompts = []
    replies = [json.dumps({'action': 'tool', 'tool': 'inspect_target', 'input': {'url': 'https://voice-target.example/assets/app.js'}}),
               json.dumps({'action': 'final', 'final': 'The observed target bundle configures audio/webm; live transport remains untested.'})]
    async def inspect_target(payload):
        return {'source_url': payload['url'], 'http_status': 200, 'body': 'new MediaRecorder(stream, {mimeType: "audio/webm"})'}
    async def model(messages, config=None):
        prompts.append(messages[0].content)
        return AI(replies.pop(0))
    runtime.model.ainvoke = model
    asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='inspect_target', ainvoke=inspect_target)],
        messages=[Human('Investigate https://voice-target.example audio framing')]))
    assert 'source_url' in prompts[1] and 'https://voice-target.example/assets/app.js' in prompts[1]
    assert 'audio/webm' in prompts[1] and 'TARGET_SOURCE' in prompts[1]
    assert 'may support target-specific claims' in prompts[1]


def test_turn_target_stream_research_does_not_take_local_video_shortcut(runtime):
    calls = []
    async def shell(payload):
        calls.append(payload)
        return 'unrelated local video devices'
    runtime.model.replies = [json.dumps({'action': 'final', 'final': 'The target bundle and WebSocket framing still need inspection.'})]
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='agent_run_shell', ainvoke=shell)],
        messages=[Human('Investigate how https://voice-target.example streams audio to the Andromeda WebSocket')]))
    assert calls == []
    assert 'target bundle' in answer.content


def test_turn_windows_filesystem_request_reaches_planner(runtime, monkeypatch):
    monkeypatch.setattr(runtime.impl, 'build_host_context', lambda: 'You are running natively on Windows.')
    calls = []
    async def shell(payload):
        calls.append(payload)
        return 'unexpected shell'
    runtime.model.replies = [json.dumps({'action': 'final', 'final': 'Use a bounded Python filesystem inspection.'})]
    asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='agent_run_shell', ainvoke=shell)],
        messages=[Human('list files recursively in the local source directory')]))
    assert calls == []


@pytest.mark.parametrize('wrapped', [
    '```json\n{"action":"final","final":"Target framing is unresolved."}\n```',
    'Result:\n{"action":"final","final":"Target framing is unresolved."}',
])
def test_research_final_wrappers_already_parse(runtime, wrapped):
    assert runtime.impl._pick_action_payload(wrapped)['action'] == 'final'


@pytest.mark.parametrize('bad', [
    '{"action":"final","final":"truncated',
    '{"action":"tool","tool":"agent_run_python","input":',
    '{"action":"final","final":"one"}{"action":"final","final":"two"}',
])
def test_research_incomplete_or_ambiguous_actions_stay_rejected(runtime, bad):
    assert runtime.impl._pick_action_payload(bad) is None


def test_research_first_local_scan_is_replaced_with_target_fetch(runtime):
    calls = []
    async def execute(payload):
        calls.append(payload)
        return 'TARGET_ORIGIN_RESULT=' + json.dumps({'source_url': 'https://voice-target.example/',
            'status': 'ok', 'body': 'conversation metadata references wss://andromeda.example/ws; /turns persists text'})
    runtime.model.replies = [json.dumps({'action': 'tool', 'tool': 'agent_run_python', 'input': {
        'filename': 'find_voice.py', 'code': "from pathlib import Path\nprint(list(Path('AgentPi/dish-chat').rglob('*.js')))"}}),
        json.dumps({'action': 'final', 'final': 'Metadata references Andromeda; audio framing remains unresolved. POST /turns is persistence.'})]
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='agent_run_python', ainvoke=execute)],
        messages=[Human('Investigate how https://voice-target.example/ sends audio to wss://andromeda.example/ws')],
        config={'configurable': {'thread_id': 'test-chat'}}))
    assert len(calls) == 1
    assert 'urlopen' in calls[0]['code'] or '.open(' in calls[0]['code']
    assert 'https://voice-target.example/' in calls[0]['code']
    assert 'rglob' not in calls[0]['code']
    assert 'framing remains unresolved' in answer.content
    assert 'PLANNER_FINALIZATION_PARTIAL' not in answer.content


def test_research_retry_after_tools_requests_final_only(runtime):
    prompts = []
    replies = [json.dumps({'action': 'tool', 'tool': 'inspect_target', 'input': {}}),
               'The observed transport framing remains unresolved.',
               json.dumps({'action': 'final', 'final': 'Transport framing remains unresolved.'})]
    async def model(messages, config=None):
        prompts.append(messages[0].content)
        return AI(replies.pop(0))
    async def inspect(payload): return 'target protocol evidence'
    runtime.model.ainvoke = model
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='inspect_target', ainvoke=inspect)],
        messages=[Human('Investigate target audio framing')]))
    assert 'Return exactly one valid final action object' in prompts[-1]
    assert 'Do not repeat completed discovery' in prompts[-1]
    assert answer.content == 'Transport framing remains unresolved.'


def test_research_protocol_diagnostics_are_metadata_only(runtime, caplog):
    runtime.model.replies = ['{"action":"final","final":"password=TEST_SECRET', 'bare Bearer TEST_TOKEN']
    asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        messages=[Human('Explain the observed protocol')], max_steps=2))
    assert 'shape=' in caplog.text and 'parse_error=' in caplog.text
    assert 'TEST_SECRET' not in caplog.text and 'TEST_TOKEN' not in caplog.text


def test_research_known_bundle_bypasses_ddg(runtime):
    calls = []
    async def execute(payload):
        calls.append(payload)
        return 'TARGET_ORIGIN_RESULT=' + json.dumps({'source_url': 'https://voice-target.example/assets/app.js', 'status': 'ok', 'body': 'ws.send(audio)'})
    async def search(payload): raise AssertionError('known URL must not require DDG')
    runtime.model.replies = [json.dumps({'action': 'tool', 'tool': 'public_web_search', 'input': 'voice target latest bundle'}),
                            json.dumps({'action': 'final', 'final': 'The target bundle contains ws.send; encoding remains unresolved.'})]
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='agent_run_python', ainvoke=execute), types.SimpleNamespace(name='public_web_search', ainvoke=search)],
        messages=[Human('Investigate the latest https://voice-target.example/assets/app.js')],
        config={'configurable': {'thread_id': 'test-chat'}}))
    assert len(calls) == 1 and 'https://voice-target.example/assets/app.js' in calls[0]['code']
    assert 'PLANNER_FINALIZATION_PARTIAL' not in answer.content


def test_research_blocked_target_limits_local_fallback(runtime):
    calls, prompts = [], []
    replies = [json.dumps({'action': 'tool', 'tool': 'agent_run_python', 'input': {'code': "print(list(Path('AgentPi').rglob('*')))"}})] * 4
    replies += [json.dumps({'action': 'final', 'final': 'Target access failed with HTTP 403. Local audio/webm code is reference only; target framing remains unverified.'})]
    async def execute(payload):
        calls.append(payload)
        if len(calls) == 1:
            return 'TARGET_ORIGIN_RESULT=' + json.dumps({'source_url': 'https://voice-target.example', 'status': 'blocked', 'http_status': 403})
        return 'Local AgentPi dashboard.js uses MediaRecorder/audio-webm'
    async def model(messages, config=None):
        prompts.append(messages[0].content)
        return AI(replies.pop(0))
    runtime.model.ainvoke = model
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='agent_run_python', ainvoke=execute)],
        messages=[Human('Investigate https://voice-target.example audio framing')],
        config={'configurable': {'thread_id': 'test-chat'}}, max_steps=6))
    assert len(calls) == 3  # one target read, two bounded local references
    assert 'REFERENCE LIMIT' in prompts[-1]
    assert 'Target access failed' in answer.content and 'reference only' in answer.content
    assert not answer.content.startswith('PLANNER_FINALIZATION_PARTIAL')


def test_research_accessible_target_rejects_unexplained_local_pivot(runtime):
    calls, prompts = [], []
    replies = [json.dumps({'action': 'tool', 'tool': 'agent_run_python', 'input': {'code': "print(list(Path('AgentPi').rglob('*')))"}})] * 2
    replies += [json.dumps({'action': 'final', 'final': 'Target HTML is available; bundle framing remains unresolved.'})]
    async def execute(payload):
        calls.append(payload)
        return 'TARGET_ORIGIN_RESULT=' + json.dumps({'source_url': 'https://voice-target.example', 'status': 'ok', 'body': '<script src="/app.js"></script>'})
    async def model(messages, config=None):
        prompts.append(messages[0].content); return AI(replies.pop(0))
    runtime.model.ainvoke = model
    asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='agent_run_python', ainvoke=execute)],
        messages=[Human('Investigate https://voice-target.example')], config={'configurable': {'thread_id': 'test-chat'}}))
    assert len(calls) == 1
    assert 'local reference directive not dispatched' in prompts[-1]


def test_research_captured_source_requires_receipt(runtime):
    target = runtime.impl.ResearchTarget('https://voice-target.example', 'url', 'https://voice-target.example')
    assert runtime.impl._captured_target_path(target, [Human('voice_demo.js')]) is None
    receipt = Human(json.dumps({'source_url': 'https://voice-target.example/assets/app.js', 'path': 'captured.js'}))
    assert runtime.impl._captured_target_path(target, [receipt]) == 'captured.js'
    assert runtime.impl._captured_target_path(target, [AI(receipt.content)]) is None
    assert runtime.impl._captured_target_path(target, [Human(json.dumps({'source_url': 'https://other.example/app.js', 'path': 'captured.js'}))]) is None
    payload = runtime.impl._target_read_payload(target, 'test-chat', 'captured.js')
    assert "CAPTURE = 'captured.js'" in payload['code']


def test_research_target_is_not_replaced_by_continuation_headers(runtime):
    messages = [Human('Investigate https://voice-target.example audio framing'), AI('Next inspect the target bundle'),
                Human('proceed\nRequest URL https://example.invalid/api/conversations\nRemote address 44.255.252.90:443')]
    assert runtime.impl._research_target(messages).raw_target == 'https://voice-target.example'


def test_research_three_tool_evidence_reaches_normal_final(runtime):
    calls = []
    async def inspect(payload):
        calls.append(payload); return ['target HTML', 'target JS', 'protocol evidence'][len(calls)-1]
    runtime.model.replies = [json.dumps({'action': 'tool', 'tool': 'inspect_target', 'input': {'part': n}}) for n in range(3)]
    runtime.model.replies += ['```json\n{"action":"final","final":"Metadata references Andromeda; binary framing remains unresolved. POST /turns persists text."}\n```']
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='inspect_target', ainvoke=inspect)],
        messages=[Human('Investigate how https://voice-target.example sends audio to wss://andromeda.example/ws')], max_steps=4))
    assert len(calls) == 3
    assert 'binary framing remains unresolved' in answer.content
    assert runtime.live.COUNTERS['artifact_readback'] == 0
    assert 'PLANNER_FINALIZATION_PARTIAL' not in answer.content


def test_research_finalization_repair_cannot_repeat_tool(runtime):
    calls = []
    async def inspect(payload): calls.append(payload); return 'target evidence'
    runtime.model.replies = [json.dumps({'action': 'tool', 'tool': 'inspect_target', 'input': {}}),
                            'bare final answer', json.dumps({'action': 'tool', 'tool': 'inspect_target', 'input': {}})]
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='inspect_target', ainvoke=inspect)],
        messages=[Human('Investigate the target')], max_steps=5))
    assert len(calls) == 1
    assert answer.content.startswith('PLANNER_FINALIZATION_PARTIAL')


def test_research_malformed_tool_stays_nonexecutable(runtime):
    calls = []
    async def execute(payload): calls.append(payload)
    runtime.model.replies = ['{"action":"tool","tool":"agent_run_python","input":'] * 2
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='agent_run_python', ainvoke=execute)],
        messages=[Human('Investigate https://voice-target.example')], config={'configurable': {'thread_id': 'test-chat'}}))
    assert calls == [] and answer.content.startswith('PLANNER_PROTOCOL_INVALID')


def test_research_captured_receipt_reads_file_without_network(runtime):
    ws = runtime.base / 'test-chat'; ws.mkdir()
    (ws / 'captured.js').write_text('new MediaRecorder(stream); ws.send(chunk)')
    runtime.model.replies = [json.dumps({'action': 'tool', 'tool': 'agent_run_python', 'input': {
        'filename': 'search_local.py', 'code': 'raise AssertionError("must not execute local sweep")'}}),
        json.dumps({'action': 'final', 'final': 'The supplied target capture uses MediaRecorder and ws.send; encoding details remain unresolved.'})]
    answer = asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model, tools=runtime.tools,
        messages=[Human(json.dumps({'source_url': 'https://voice-target.example/assets/app.js', 'path': 'captured.js'})),
                  Human('Investigate https://voice-target.example audio transport')],
        config={'configurable': {'thread_id': 'test-chat'}}))
    assert 'supplied target capture' in answer.content
    assert not (ws / 'search_local.py').exists()
    assert "CAPTURE = 'captured.js'" in (ws / '_inspect_requested_target.py').read_text()
    assert runtime.live.COUNTERS['artifact_readback'] == 0


@pytest.mark.parametrize('text,kind', [
    ('Investigate wss://andromeda.example/ws', 'websocket'),
    ('Investigate API api.voice.example', 'host'),
    ('Inspect git@github.com:org/repo.git', 'repo'),
    ('Inspect C:\\specific\\repo', 'path'),
    ('Inspect /mnt/c/specific/repo', 'path'),
    ('Inspect uploaded voice_capture.js', 'file'),
])
def test_research_target_kinds(runtime, text, kind):
    assert runtime.impl._research_target([Human(text)]).target_kind == kind


def test_research_generated_get_is_bounded_and_reports_blocked_access(runtime, monkeypatch, capsys):
    import io
    import urllib.request
    class Response(io.BytesIO):
        status = 200
        headers = {'Content-Type': 'application/javascript'}
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, request.get_method(), timeout))
            return Response(b'x' * 40000)
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Opener())
    target = runtime.impl.ResearchTarget('https://voice-target.example/app.js', 'url', 'https://voice-target.example')
    payload = runtime.impl._target_read_payload(target, 'test-chat')
    exec(compile(payload['code'], '<target-probe-fixture>', 'exec'), {})
    output = capsys.readouterr().out
    receipt = json.loads(output.split('TARGET_ORIGIN_RESULT=', 1)[1])
    assert calls == [('https://voice-target.example/app.js', 'GET', 10)]
    assert receipt['bytes_observed'] == 32768 and receipt['truncated']
    assert len(receipt['body']) == 8000
    class Blocked:
        def open(self, request, timeout): raise TimeoutError('password=TEST_SECRET')
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Blocked())
    exec(compile(payload['code'], '<target-probe-fixture>', 'exec'), {})
    output = capsys.readouterr().out
    assert 'TimeoutError' in output and 'TEST_SECRET' not in output


def test_research_protocol_metadata_shapes(runtime):
    assert runtime.impl._protocol_diagnostic('bare final')['shape'] == 'bare_prose'
    d = runtime.impl._protocol_diagnostic('{"action":"final","final":"cut')
    assert d['shape'] == 'final_envelope' and d['parse_error'] == 'JSONDecodeError'
    d = runtime.impl._protocol_diagnostic('{"action":"final","final":"a"}{"action":"final","final":"b"}')
    assert d['json_candidates'] == 0 and d['parse_error'] == 'ambiguous_or_rejected_object'


def test_research_unknown_tool_does_not_trigger_substitute_execution(runtime):
    calls = []
    async def execute(payload): calls.append(payload)
    runtime.model.replies = [json.dumps({'action': 'tool', 'tool': 'nonexistent', 'input': {}}),
                            json.dumps({'action': 'final', 'final': 'No target evidence acquired.'})]
    asyncio.run(runtime.live.run_coverity_tool_loop(model=runtime.model,
        tools=[types.SimpleNamespace(name='agent_run_python', ainvoke=execute)],
        messages=[Human('Investigate https://voice-target.example')], config={'configurable': {'thread_id': 'test-chat'}}))
    assert calls == []


def test_research_target_execution_secret_and_literal_markers_are_preserved(runtime):
    text = 'Investigate https://voice-target.example/__CAPTURE__?access_token=TEST_TOKEN'
    target = runtime.impl._research_target([Human(text)])
    payload = runtime.impl._target_read_payload(target, 'test-chat')
    assert "SOURCE = 'https://voice-target.example/__CAPTURE__?access_token=TEST_TOKEN'" in payload['code']
    compile(payload['code'], '<fixture>', 'exec')
    assert 'TEST_TOKEN' not in runtime.impl._resolve_target_identity([Human(text)])
    assert 'TEST_TOKEN' not in runtime.impl.redact_sensitive_text(payload['code'])
