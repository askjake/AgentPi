"""Portable source/contract tests for the AgentPi MCOP port."""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dish-chat" / "backend"
AGENT_MODE = BACKEND / "app" / "agent_mode"


def _load_packets():
    path = AGENT_MODE / "orchestration_packets.py"
    spec = importlib.util.spec_from_file_location("agentpi_mcop_packets_portable", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_mcop_sources_parse_and_exist():
    required = [
        AGENT_MODE / "orchestration_packets.py",
        AGENT_MODE / "child_conversation.py",
        AGENT_MODE / "mcop_tools.py",
    ]
    for path in required:
        assert path.is_file(), path
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_packet_contract_accepts_only_matching_terminal_packet():
    packets = _load_packets()
    good = {
        "packet_type": "tool_evidence",
        "task_id": "t1",
        "worker_role": "tool_worker",
        "status": "completed",
        "facts": [{"claim": "observed", "confidence": "high"}],
        "inferences": [],
        "gaps": [],
        "errors": [],
        "raw_artifacts": [],
    }
    packet = packets.try_parse_tool_evidence_packet(json.dumps(good), "t1")
    assert packet is not None
    assert packet.status == "completed"
    assert packet.task_id == "t1"
    assert packets.try_parse_tool_evidence_packet(json.dumps({**good, "task_id": "other"}), "t1") is None
    assert packets.try_parse_tool_evidence_packet("not json", "t1") is None


def test_invalid_child_output_normalizes_to_partial_not_complete():
    packets = _load_packets()
    fallback = packets.normalize_worker_packet_from_summary(
        task_id="t2", summary="unparsed", status="partial"
    )
    assert fallback.status == "partial"
    assert fallback.gaps


def test_child_source_uses_shared_live_planner_and_forbids_recursive_mcop():
    source = (AGENT_MODE / "child_conversation.py").read_text(encoding="utf-8")
    assert "from app.agent.agents.coverity_tool_loop import run_coverity_tool_loop" in source
    for name in (
        "agent_spawn_task",
        "agent_spawn_parallel",
        "agent_check_tasks",
        "agent_read_task_result",
        "agent_read_packet",
    ):
        assert name in source
    assert 'return _filter_child_tools(get_tools_set("agent_mode"))' in source
