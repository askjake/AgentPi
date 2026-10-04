"""Structured evidence contracts for AgentPi MCOP child conversations."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any

PACKET_TYPE = "tool_evidence"
TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "blocked", "cancelled"})
_CONFIDENCE = frozenset({"high", "medium", "low"})


@dataclass
class ToolEvidencePacket:
    packet_type: str = PACKET_TYPE
    task_id: str = ""
    worker_role: str = "tool_worker"
    status: str = "partial"
    tool_families_used: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    raw_artifacts: list[str] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    inferences: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    next_recommended_step: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _list_of_strings(value: Any, *, limit: int = 100) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:4000] for item in value[:limit]]


def _list_of_dicts(value: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value[:limit] if isinstance(item, dict)]


def packet_from_mapping(data: dict[str, Any], task_id: str) -> ToolEvidencePacket | None:
    if not isinstance(data, dict):
        return None
    if data.get("packet_type") != PACKET_TYPE:
        return None
    incoming_task_id = str(data.get("task_id") or task_id)
    if incoming_task_id != task_id:
        return None
    status = str(data.get("status") or "").strip().lower()
    if status not in TERMINAL_STATUSES:
        return None

    facts = _list_of_dicts(data.get("facts"))
    inferences = _list_of_dicts(data.get("inferences"))
    for item in [*facts, *inferences]:
        confidence = item.get("confidence")
        if confidence is not None and str(confidence).lower() not in _CONFIDENCE:
            item["confidence"] = "low"

    return ToolEvidencePacket(
        task_id=task_id,
        worker_role=str(data.get("worker_role") or "tool_worker")[:128],
        status=status,
        tool_families_used=_list_of_strings(data.get("tool_families_used")),
        tools_called=_list_of_strings(data.get("tools_called")),
        raw_artifacts=_list_of_strings(data.get("raw_artifacts")),
        facts=facts,
        inferences=inferences,
        gaps=_list_of_strings(data.get("gaps")),
        errors=_list_of_strings(data.get("errors")),
        next_recommended_step=str(data.get("next_recommended_step") or "")[:8000],
        summary=str(data.get("summary") or "")[:12000],
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    candidate = str(text or "").strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def try_parse_tool_evidence_packet(text: str, task_id: str) -> ToolEvidencePacket | None:
    parsed = _extract_json_object(text)
    if parsed is None:
        return None
    return packet_from_mapping(parsed, task_id)


def normalize_worker_packet_from_summary(
    *,
    task_id: str,
    summary: str,
    status: str = "partial",
    artifacts: list[str] | None = None,
) -> ToolEvidencePacket:
    normalized_status = status if status in TERMINAL_STATUSES else "partial"
    return ToolEvidencePacket(
        task_id=task_id,
        status=normalized_status,
        raw_artifacts=list(artifacts or []),
        gaps=["Child response was not a valid ToolEvidencePacket; raw response requires parent review."],
        summary=str(summary or "")[:12000],
    )
