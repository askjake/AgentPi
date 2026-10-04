"""Native/deployed-dependency qualification for AgentPi MCOP Phase A."""
from __future__ import annotations

import asyncio
import json

from langchain_core.messages import AIMessage, HumanMessage

MCOP_NAMES = {
    "agent_spawn_task",
    "agent_spawn_parallel",
    "agent_check_tasks",
    "agent_read_task_result",
    "agent_read_packet",
}


def test_child_tool_binding_excludes_all_mcop_tools():
    from app.agent_mode import child_conversation as child
    names = {getattr(tool, "name", "") for tool in child._get_child_tools()}
    assert MCOP_NAMES.isdisjoint(names)
    assert "agent_run_python" in names


def test_orchestration_state_round_trip(monkeypatch, tmp_path):
    from app.agent_mode import child_conversation as child

    monkeypatch.setattr(child, "BASE_AGENT_WORKDIR", str(tmp_path))
    result = child.ChildResult(
        task_id="state-test",
        status="completed",
        summary="done",
        facts=[{"claim": "fixture", "confidence": "high"}],
    )
    state = child.OrchestrationState(parent_chat_id="chat-state", tasks={"state-test": result})
    state.save()

    loaded = child.OrchestrationState.load("chat-state")
    assert loaded.tasks["state-test"].status == "completed"
    assert loaded.tasks["state-test"].summary == "done"
    assert (tmp_path / "chat-state" / "_mcop" / "state.json").is_file()


def test_child_persists_valid_packet_without_provider(monkeypatch, tmp_path):
    from app.agent_mode import child_conversation as child

    monkeypatch.setattr(child, "BASE_AGENT_WORKDIR", str(tmp_path))
    packet = {
        "packet_type": "tool_evidence",
        "task_id": "packet-test",
        "worker_role": "tool_worker",
        "status": "completed",
        "tool_families_used": [],
        "tools_called": [],
        "raw_artifacts": [],
        "facts": [{"claim": "fixture packet", "confidence": "high"}],
        "inferences": [],
        "gaps": [],
        "errors": [],
        "next_recommended_step": "",
        "summary": "packet complete",
    }

    class FakeGraph:
        async def ainvoke(self, state, config=None):
            return {
                **state,
                "messages": [*state["messages"], AIMessage(content=json.dumps(packet))],
                "iterations": 1,
            }

    monkeypatch.setattr(child, "_build_child_graph", lambda: FakeGraph())
    result = asyncio.run(child.run_child_conversation(
        parent_chat_id="chat-packet",
        task_id="packet-test",
        prompt="return fixture packet",
    ))
    assert result.status == "completed"
    assert result.summary == "packet complete"
    task_dir = tmp_path / "chat-packet" / "_mcop" / "task_packet-test"
    assert (task_dir / "tool_evidence_packet.json").is_file()
    assert (task_dir / "result.json").is_file()


def test_unparseable_child_response_is_partial(monkeypatch, tmp_path):
    from app.agent_mode import child_conversation as child

    monkeypatch.setattr(child, "BASE_AGENT_WORKDIR", str(tmp_path))

    class FakeGraph:
        async def ainvoke(self, state, config=None):
            return {
                **state,
                "messages": [*state["messages"], AIMessage(content="looks done")],
                "iterations": 1,
            }

    monkeypatch.setattr(child, "_build_child_graph", lambda: FakeGraph())
    result = asyncio.run(child.run_child_conversation(
        parent_chat_id="chat-partial",
        task_id="partial-test",
        prompt="fixture",
    ))
    assert result.status == "partial"
    assert result.gaps
    assert (tmp_path / "chat-partial" / "_mcop" / "task_partial-test" / "unparsed_final_response.txt").is_file()


def test_full_child_shared_planner_unwraps_and_persists_packet(monkeypatch, tmp_path):
    from app.agent_mode import child_conversation as child

    monkeypatch.setattr(child, "BASE_AGENT_WORKDIR", str(tmp_path))
    monkeypatch.setattr(child, "set_model_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(child.settings, "PLLM_PROVIDER", "coverity-assist")

    packet = {
        "packet_type": "tool_evidence",
        "task_id": "planner-e2e",
        "worker_role": "tool_worker",
        "status": "completed",
        "tool_families_used": [],
        "tools_called": [],
        "raw_artifacts": [],
        "facts": [{"claim": "shared planner child completed", "confidence": "high"}],
        "inferences": [],
        "gaps": [],
        "errors": [],
        "next_recommended_step": "",
        "summary": "shared planner packet complete",
    }
    planner_wrapper = json.dumps({
        "action": "final",
        "final": json.dumps(packet),
    })

    class FakeModel:
        _llm_type = "fixture"
        def bind_tools(self, tools):
            return self
        async def ainvoke(self, messages, config=None):
            prompt = str(getattr(messages[-1], "content", ""))
            assert "MCOP child finalization contract:" in prompt
            assert "final field must be a STRING" in prompt
            return AIMessage(content=planner_wrapper)

    def strict_get_model(*args, **kwargs):
        assert args == ()
        assert kwargs == {}
        return FakeModel()

    monkeypatch.setattr(child, "get_model", strict_get_model)

    result = asyncio.run(child.run_child_conversation(
        parent_chat_id="planner-parent",
        task_id="planner-e2e",
        prompt="Return the controlled smoke-test evidence packet without tools.",
        max_iters=2,
    ))

    assert result.status == "completed"
    assert result.iterations_used == 1
    assert result.summary == "shared planner packet complete"
    assert result.facts[0]["claim"] == "shared planner child completed"
    assert result.packet_path == "_mcop/task_planner-e2e/tool_evidence_packet.json"
    packet_path = tmp_path / "planner-parent" / "_mcop" / "task_planner-e2e" / "tool_evidence_packet.json"
    assert packet_path.is_file()
    persisted = json.loads(packet_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "completed"
    assert persisted["task_id"] == "planner-e2e"


def test_coverity_child_calls_shared_live_planner_with_parent_workspace(monkeypatch):
    from app.agent_mode import child_conversation as child
    from app.agent.agents import coverity_tool_loop as live

    calls = {}

    class FakeModel:
        _llm_type = "coverity-assist"
        def bind_tools(self, tools):
            raise AssertionError("coverity child must use shared planner")

    async def fake_loop(*, model, tools, messages, config, max_steps, **kwargs):
        calls["tools"] = tools
        calls["thread_id"] = config["configurable"]["thread_id"]
        calls["mcop_child"] = config["configurable"].get("mcop_child")
        calls["max_steps"] = max_steps
        return AIMessage(content=json.dumps({
            "packet_type": "tool_evidence",
            "task_id": "shared-planner",
            "worker_role": "tool_worker",
            "status": "completed",
            "tool_families_used": [],
            "tools_called": [],
            "raw_artifacts": [],
            "facts": [],
            "inferences": [],
            "gaps": [],
            "errors": [],
            "next_recommended_step": "",
            "summary": "ok",
        }))

    def strict_get_model(*args, **kwargs):
        assert args == ()
        assert kwargs == {}
        return FakeModel()

    monkeypatch.setattr(child, "get_model", strict_get_model)
    monkeypatch.setattr(child, "set_model_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(live, "run_coverity_tool_loop", fake_loop)
    monkeypatch.setattr(child.settings, "PLLM_PROVIDER", "coverity-assist")

    state = {
        "messages": [HumanMessage(content="fixture")],
        "chat_id": "parent-chat",
        "task_id": "shared-planner",
        "iterations": 0,
        "max_iters": 3,
    }
    answer = asyncio.run(child._child_agent_node(
        state,
        {"configurable": {"thread_id": "ephemeral-child-thread"}},
    ))
    assert calls["thread_id"] == "parent-chat"
    assert calls["mcop_child"] is True
    assert calls["max_steps"] == 3
    assert MCOP_NAMES.isdisjoint({getattr(tool, "name", "") for tool in calls["tools"]})
    assert answer["iterations"] == 1
