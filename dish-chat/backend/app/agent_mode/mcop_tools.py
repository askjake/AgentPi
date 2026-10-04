"""Parent-facing tools for AgentPi Multi-Conversation Orchestration Protocol."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any
import uuid

from langchain.tools import tool

from app.agent_mode.child_conversation import (
    MCOP_CHILD_MAX_ITERS,
    MCOP_CONTRACT,
    MCOP_MAX_CHILDREN,
    MCOP_PARALLEL_LIMIT,
    MCOP_RESULT_MAX_CHARS,
    ChildResult,
    OrchestrationState,
    _get_task_dir,
    _workspace_path,
    run_child_conversation,
    run_parallel_tasks,
)
from app.agent_mode.orchestration_packets import TERMINAL_STATUSES
from app.agent_mode.thought_interceptor import interceptor

IMPLEMENTATION_CONTRACT = MCOP_CONTRACT
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DEFAULT_PAGE_SIZE = 10
_MAX_PAGE_SIZE = 50
_MAX_READ_CHARS = 12_000
_MAX_LIST_ITEMS = 20


def _task_id(value: str) -> str:
    value = str(value or "")
    if not _TASK_ID_RE.fullmatch(value):
        raise ValueError("invalid task_id")
    return value


def _terminal(result: ChildResult) -> bool:
    return str(result.status or "").lower() in TERMINAL_STATUSES


def _capacity(state: OrchestrationState) -> dict[str, Any]:
    active = [task_id for task_id, result in state.tasks.items() if not _terminal(result)]
    return {
        "max_active_children": MCOP_MAX_CHILDREN,
        "active_task_count": len(active),
        "terminal_task_count": len(state.tasks) - len(active),
        "available_slots": max(0, MCOP_MAX_CHILDREN - len(active)),
        "active_task_ids": active,
    }


def _parse_string_list(value: str | list[str] | None, *, limit: int = 20) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value[:limit]]
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed[:limit]]
    except Exception:
        pass
    return [part.strip() for part in str(value).split(",") if part.strip()][:limit]


def _preview(value: str, limit: int = 2000) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + f"\n[TRUNCATED {len(text) - limit} CHARS]"


def _bounded_list(value: list[Any], limit: int = _MAX_LIST_ITEMS) -> list[Any]:
    output = []
    for item in value[:limit]:
        if isinstance(item, str):
            output.append(_preview(item, 1000))
        elif isinstance(item, dict):
            output.append({
                str(k)[:128]: (_preview(v, 1000) if isinstance(v, str) else v)
                for k, v in list(item.items())[:30]
            })
        else:
            output.append(item)
    return output


def _result_payload(result: ChildResult, *, summary_chars: int = 2000) -> dict[str, Any]:
    payload = {
        "contract": IMPLEMENTATION_CONTRACT,
        "task_id": result.task_id,
        "status": result.status,
        "iterations_used": result.iterations_used,
        "tokens_used": result.tokens_used,
        "artifacts": _bounded_list(result.artifacts),
        "raw_artifacts": _bounded_list(result.raw_artifacts),
        "facts": _bounded_list(result.facts),
        "inferences": _bounded_list(result.inferences),
        "gaps": _bounded_list(result.gaps),
        "errors": _bounded_list(result.errors),
        "next_recommended_step": _preview(result.next_recommended_step, 2000),
        "packet_path": result.packet_path,
        "summary": _preview(result.summary, summary_chars),
        "started_at": result.started_at,
        "finished_at": result.finished_at,
    }
    if result.error:
        payload["error"] = _preview(result.error, 2000)
    return payload


def _json(payload: Any) -> str:
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if len(text) <= MCOP_RESULT_MAX_CHARS:
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return json.dumps({
        "contract": IMPLEMENTATION_CONTRACT,
        "status": "partial",
        "message": "Parent-facing MCOP response exceeded the bounded response limit.",
        "sha256": digest,
        "full_result_available_via": "agent_read_task_result / agent_read_packet",
    }, indent=2)


@tool("agent_spawn_task")
async def agent_spawn_task(
    chat_id: str,
    task_prompt: str,
    task_id: str = "",
    context_files: str = "[]",
    max_iters: int = 5,
) -> str:
    """Run one bounded MCOP child conversation in a fresh context."""
    try:
        task_id = _task_id(task_id or f"t{uuid.uuid4().hex[:8]}")
        files = _parse_string_list(context_files)
        state = OrchestrationState.load(chat_id)
        capacity = _capacity(state)
        if task_id in state.tasks:
            return _json({
                "contract": IMPLEMENTATION_CONTRACT,
                "status": "blocked",
                "result_code": "BLOCKED_DUPLICATE_TASK_ID",
                "task_id": task_id,
                "existing": _result_payload(state.tasks[task_id], summary_chars=500),
            })
        if capacity["available_slots"] <= 0:
            return _json({
                "contract": IMPLEMENTATION_CONTRACT,
                "status": "blocked",
                "result_code": "BLOCKED_CHILD_CAPACITY",
                **capacity,
            })
        if not str(task_prompt or "").strip():
            return _json({
                "contract": IMPLEMENTATION_CONTRACT,
                "status": "blocked",
                "result_code": "BLOCKED_EMPTY_TASK",
            })
        interceptor.thought(f"MCOP parent spawning task {task_id}", "orchestrator")
        result = await run_child_conversation(
            parent_chat_id=chat_id,
            task_id=task_id,
            prompt=str(task_prompt),
            context_files=files,
            max_iters=max(1, min(int(max_iters), MCOP_CHILD_MAX_ITERS)),
        )
        return _json(_result_payload(result))
    except Exception as exc:
        return _json({
            "contract": IMPLEMENTATION_CONTRACT,
            "status": "failed",
            "result_code": "MCOP_SPAWN_FAILED",
            "error": f"{type(exc).__name__}: {exc}",
        })


@tool("agent_spawn_parallel")
async def agent_spawn_parallel(chat_id: str, tasks_json: str) -> str:
    """Run independent MCOP child tasks concurrently with bounded parallelism."""
    try:
        tasks = json.loads(tasks_json)
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("tasks_json must be a non-empty JSON array")
        state = OrchestrationState.load(chat_id)
        capacity = _capacity(state)
        if len(tasks) > capacity["available_slots"]:
            return _json({
                "contract": IMPLEMENTATION_CONTRACT,
                "status": "blocked",
                "result_code": "BLOCKED_CHILD_CAPACITY",
                "requested": len(tasks),
                **capacity,
            })

        normalized: list[dict[str, Any]] = []
        seen = set(state.tasks)
        for index, raw in enumerate(tasks):
            if not isinstance(raw, dict):
                raise ValueError(f"task {index} is not an object")
            tid = _task_id(str(raw.get("task_id") or f"t{uuid.uuid4().hex[:8]}"))
            if tid in seen:
                raise ValueError(f"duplicate task_id: {tid}")
            seen.add(tid)
            prompt = str(raw.get("prompt") or "").strip()
            if not prompt:
                raise ValueError(f"task {tid} has empty prompt")
            normalized.append({
                "task_id": tid,
                "prompt": prompt,
                "context_files": _parse_string_list(raw.get("context_files")),
                "max_iters": max(1, min(int(raw.get("max_iters") or MCOP_CHILD_MAX_ITERS), MCOP_CHILD_MAX_ITERS)),
            })

        interceptor.thought(
            f"MCOP parent spawning {len(normalized)} parallel tasks (limit {MCOP_PARALLEL_LIMIT})",
            "orchestrator",
        )
        results = await run_parallel_tasks(chat_id, normalized)
        return _json({
            "contract": IMPLEMENTATION_CONTRACT,
            "status": "completed" if all(r.status == "completed" for r in results) else "partial",
            "parallel_limit": MCOP_PARALLEL_LIMIT,
            "results": [_result_payload(result, summary_chars=750) for result in results],
        })
    except Exception as exc:
        return _json({
            "contract": IMPLEMENTATION_CONTRACT,
            "status": "failed",
            "result_code": "MCOP_PARALLEL_FAILED",
            "error": f"{type(exc).__name__}: {exc}",
        })


@tool("agent_check_tasks")
def agent_check_tasks(
    chat_id: str,
    status: str = "all",
    offset: int = 0,
    limit: int = _DEFAULT_PAGE_SIZE,
) -> str:
    """List bounded MCOP task status for the current chat workspace."""
    try:
        state = OrchestrationState.load(chat_id)
        status = str(status or "all").lower()
        if status not in {"all", "active", "terminal"}:
            raise ValueError("status must be all, active, or terminal")
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), _MAX_PAGE_SIZE))
        items = []
        for tid, result in sorted(state.tasks.items()):
            is_terminal = _terminal(result)
            if status == "active" and is_terminal:
                continue
            if status == "terminal" and not is_terminal:
                continue
            items.append(_result_payload(result, summary_chars=300))
        page = items[offset: offset + limit]
        return _json({
            "contract": IMPLEMENTATION_CONTRACT,
            "parent_chat_id": state.parent_chat_id,
            "capacity": _capacity(state),
            "total_matching": len(items),
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < len(items),
            "tasks": page,
        })
    except Exception as exc:
        return _json({
            "contract": IMPLEMENTATION_CONTRACT,
            "status": "failed",
            "result_code": "MCOP_STATUS_FAILED",
            "error": f"{type(exc).__name__}: {exc}",
        })


@tool("agent_read_task_result")
def agent_read_task_result(chat_id: str, task_id: str) -> str:
    """Read a bounded persisted MCOP task result."""
    try:
        task_id = _task_id(task_id)
        state = OrchestrationState.load(chat_id)
        result = state.tasks.get(task_id)
        if result is None:
            return _json({
                "contract": IMPLEMENTATION_CONTRACT,
                "status": "missing",
                "task_id": task_id,
            })
        return _json(_result_payload(result, summary_chars=6000))
    except Exception as exc:
        return _json({
            "contract": IMPLEMENTATION_CONTRACT,
            "status": "failed",
            "result_code": "MCOP_READ_RESULT_FAILED",
            "error": f"{type(exc).__name__}: {exc}",
        })


@tool("agent_read_packet")
def agent_read_packet(
    chat_id: str,
    task_id: str,
    offset: int = 0,
    max_chars: int = 6000,
) -> str:
    """Read a chunk of the durable structured evidence packet for one child."""
    try:
        task_id = _task_id(task_id)
        task_dir = _get_task_dir(chat_id, task_id, create=False)
        packet = task_dir / "tool_evidence_packet.json"
        if not packet.is_file():
            return _json({
                "contract": IMPLEMENTATION_CONTRACT,
                "status": "missing",
                "task_id": task_id,
                "packet_path": str(packet),
            })
        workspace = _workspace_path(chat_id, create=False).resolve()
        resolved = packet.resolve()
        resolved.relative_to(workspace)
        text = packet.read_text(encoding="utf-8", errors="replace")
        offset = max(0, int(offset))
        max_chars = max(1, min(int(max_chars), _MAX_READ_CHARS))
        chunk = text[offset: offset + max_chars]
        return _json({
            "contract": IMPLEMENTATION_CONTRACT,
            "status": "ok",
            "task_id": task_id,
            "packet_path": str(packet.relative_to(_workspace_path(chat_id, create=False))),
            "offset": offset,
            "returned_chars": len(chunk),
            "total_chars": len(text),
            "has_more": offset + len(chunk) < len(text),
            "next_offset": offset + len(chunk) if offset + len(chunk) < len(text) else None,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "content": chunk,
        })
    except Exception as exc:
        return _json({
            "contract": IMPLEMENTATION_CONTRACT,
            "status": "failed",
            "result_code": "MCOP_READ_PACKET_FAILED",
            "error": f"{type(exc).__name__}: {exc}",
        })
