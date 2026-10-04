"""AgentPi Multi-Conversation Orchestration Protocol child runtime.

Children get a fresh LangGraph context, share only the parent's workspace, and
receive the existing AgentPi tool registry with every MCOP tool removed. Coverity
children call the same repaired planner entry point used by ordinary chat and
Agent Mode; MCOP does not introduce a second planner implementation.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Annotated, Any, Optional
import uuid

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from app.config import get_settings
from app.core.llm import get_model
from app.agent.utils import set_model_config
from app.agent_mode.thought_interceptor import interceptor
from app.agent_mode.tools import BASE_AGENT_WORKDIR
from app.agent_mode.orchestration_packets import (
    TERMINAL_STATUSES,
    normalize_worker_packet_from_summary,
    try_parse_tool_evidence_packet,
)

settings = get_settings()
logger = logging.getLogger(__name__)
LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

MCOP_CONTRACT = "agentpi-mcop-v1"
MCOP_MAX_DEPTH = 1
MCOP_MAX_CHILDREN = int(getattr(settings, "MCOP_MAX_CHILDREN", 5))
MCOP_CHILD_MAX_ITERS = int(getattr(settings, "MCOP_CHILD_MAX_ITERS", 5))
MCOP_PARALLEL_LIMIT = int(getattr(settings, "MCOP_PARALLEL_LIMIT", 3))
MCOP_CONTEXT_MAX_CHARS = int(getattr(settings, "MCOP_CONTEXT_MAX_CHARS", 100_000))
MCOP_RESULT_MAX_CHARS = int(getattr(settings, "MCOP_RESULT_MAX_CHARS", 12_000))
MCOP_DIR = "_mcop"

_MCOP_TOOL_NAMES = frozenset({
    "agent_spawn_task",
    "agent_spawn_parallel",
    "agent_check_tasks",
    "agent_read_task_result",
    "agent_read_packet",
})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SENSITIVE_CONTEXT_NAMES = frozenset({
    ".env", ".env.local", ".env.production", "credentials", "credentials.json",
    "secrets.json", "id_rsa", "id_ed25519",
})


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", None) or getattr(tool, "__name__", "") or "")


def _filter_child_tools(tools: list[Any]) -> list[Any]:
    """MCOP is depth-one: children can never see orchestration tools."""
    return [tool for tool in tools if _tool_name(tool) and _tool_name(tool) not in _MCOP_TOOL_NAMES]


def _get_child_tools() -> list[Any]:
    # Lazy import prevents registry -> mcop_tools -> child_conversation -> registry cycles.
    from app.agent.agents.tools import get_tools_set
    return _filter_child_tools(get_tools_set("agent_mode"))


def _validate_identity(value: str, label: str) -> str:
    value = str(value or "")
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def _workspace_path(chat_id: str, *, create: bool = False) -> Path:
    chat_id = _validate_identity(chat_id, "chat_id")
    root = Path(BASE_AGENT_WORKDIR)
    path = root / chat_id
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _get_mcop_dir(chat_id: str, *, create: bool = True) -> Path:
    path = _workspace_path(chat_id, create=create) / MCOP_DIR
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _get_task_dir(chat_id: str, task_id: str, *, create: bool = True) -> Path:
    task_id = _validate_identity(task_id, "task_id")
    path = _get_mcop_dir(chat_id, create=create) / f"task_{task_id}"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


@dataclass
class ChildResult:
    task_id: str
    status: str
    artifacts: list[str] = field(default_factory=list)
    summary: str = ""
    tokens_used: int = 0
    iterations_used: int = 0
    error: Optional[str] = None
    facts: list[dict[str, Any]] = field(default_factory=list)
    inferences: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw_artifacts: list[str] = field(default_factory=list)
    next_recommended_step: str = ""
    packet_path: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "ChildResult":
        allowed = {name for name in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrchestrationState:
    parent_chat_id: str
    tasks: dict[str, ChildResult] = field(default_factory=dict)
    total_tokens: int = 0
    updated_at: Optional[str] = None

    @classmethod
    def load(cls, parent_chat_id: str) -> "OrchestrationState":
        _validate_identity(parent_chat_id, "chat_id")
        state_file = _get_mcop_dir(parent_chat_id, create=False) / "state.json"
        if not state_file.is_file():
            return cls(parent_chat_id=parent_chat_id)
        try:
            raw = json.loads(state_file.read_text(encoding="utf-8"))
            tasks = {
                str(task_id): ChildResult.from_mapping(value)
                for task_id, value in (raw.get("tasks") or {}).items()
                if isinstance(value, dict)
            }
            return cls(
                parent_chat_id=parent_chat_id,
                tasks=tasks,
                total_tokens=int(raw.get("total_tokens") or 0),
                updated_at=raw.get("updated_at"),
            )
        except Exception:
            logger.exception("Failed to load MCOP state for chat %s", parent_chat_id)
            return cls(parent_chat_id=parent_chat_id)

    def save(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "contract": MCOP_CONTRACT,
            "parent_chat_id": self.parent_chat_id,
            "tasks": {task_id: result.to_dict() for task_id, result in self.tasks.items()},
            "total_tokens": self.total_tokens,
            "updated_at": self.updated_at,
        }
        _atomic_write_json(_get_mcop_dir(self.parent_chat_id) / "state.json", payload)


class ChildState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    chat_id: str
    task_id: str
    iterations: int
    max_iters: int


def _child_system_prompt(parent_chat_id: str, task_id: str) -> str:
    return f"""You are an MCOP tool worker executing one bounded sub-task.
Parent workspace/chat_id: {parent_chat_id}
Task id: {task_id}

Use only the tools bound to this child. You cannot spawn or inspect other MCOP
children. Do not claim a tool action succeeded unless its returned evidence says
so. Keep work bounded to this task.

Your final CHILD EVIDENCE content must be one JSON object with this exact shape:
{{
  "packet_type": "tool_evidence",
  "task_id": "{task_id}",
  "worker_role": "tool_worker",
  "status": "completed|partial|failed|blocked",
  "tool_families_used": [],
  "tools_called": [],
  "raw_artifacts": [],
  "facts": [],
  "inferences": [],
  "gaps": [],
  "errors": [],
  "next_recommended_step": "",
  "summary": ""
}}
Because this child runs through the shared Coverity tool planner, the planner's
TOP-LEVEL response still uses its normal action protocol. When finalizing, place
the serialized ToolEvidencePacket JSON above as the STRING value of the
planner's action=final "final" field. Do not emit the ToolEvidencePacket as the
top-level planner response.

Use workspace-relative paths in raw_artifacts. If evidence is incomplete, use
status=partial and record the gap instead of inventing completion."""


async def _child_agent_node(state: ChildState, config: dict[str, Any] | None = None) -> dict[str, Any]:
    tools = _get_child_tools()
    # AgentPi's model factory resolves the configured provider/model from
    # Settings. It accepts only the optional efficient= flag; older JakeBot
    # model_arn calling conventions are not valid here.
    model = get_model()
    set_model_config(model, {"temperature": 0.2, "reasoning": True})
    system = SystemMessage(content=_child_system_prompt(state["chat_id"], state["task_id"]))
    messages = [system, *state["messages"]]

    provider = getattr(settings, "PLLM_PROVIDER", "")
    llm_type = getattr(model, "_llm_type", "")
    if provider == "coverity-assist" or llm_type in {"coverity-assist", "coverity-assist-tool-enabled"}:
        from app.agent.agents.coverity_tool_loop import run_coverity_tool_loop
        planner_config = dict(config or {})
        planner_config["configurable"] = dict(planner_config.get("configurable", {}))
        planner_config["configurable"]["thread_id"] = state["chat_id"]
        planner_config["configurable"]["mcop_child"] = True
        response = await run_coverity_tool_loop(
            model=model,
            tools=tools,
            messages=messages,
            config=planner_config,
            max_steps=max(1, int(state["max_iters"])),
        )
    else:
        response = await model.bind_tools(tools).ainvoke(messages, config=config)

    return {
        "messages": [response],
        "iterations": int(state.get("iterations", 0)) + 1,
    }


def _child_route(state: ChildState) -> str:
    if int(state.get("iterations", 0)) >= int(state.get("max_iters", MCOP_CHILD_MAX_ITERS)):
        return END
    last = state["messages"][-1]
    return "tools" if bool(getattr(last, "tool_calls", None)) else END


def _build_child_graph():
    tools = _get_child_tools()
    workflow = StateGraph(ChildState)
    workflow.add_node("agent", _child_agent_node)
    workflow.add_node("tools", ToolNode(tools=tools))
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", _child_route, {"tools": "tools", END: END})
    workflow.add_edge("tools", "agent")
    return workflow.compile(checkpointer=MemorySaver())


def _read_context(parent_chat_id: str, context_files: list[str] | None) -> list[str]:
    if not context_files:
        return []
    workspace = _workspace_path(parent_chat_id, create=True).resolve()
    remaining = MCOP_CONTEXT_MAX_CHARS
    output: list[str] = []
    for raw in context_files[:20]:
        if remaining <= 0:
            output.append("[CONTEXT LIMIT REACHED]")
            break
        rel = str(raw or "")
        if not rel or Path(rel).is_absolute():
            output.append(f'<context_file path="{rel}">[INVALID PATH]</context_file>')
            continue
        if Path(rel).name.lower() in _SENSITIVE_CONTEXT_NAMES or Path(rel).suffix.lower() in {".pem", ".key"}:
            output.append(f'<context_file path="{rel}">[SENSITIVE FILE BLOCKED]</context_file>')
            continue
        candidate = (workspace / rel).resolve()
        try:
            candidate.relative_to(workspace)
        except ValueError:
            output.append(f'<context_file path="{rel}">[OUTSIDE WORKSPACE BLOCKED]</context_file>')
            continue
        if not candidate.is_file():
            output.append(f'<context_file path="{rel}">[FILE NOT FOUND]</context_file>')
            continue
        text = candidate.read_text(encoding="utf-8", errors="replace")
        text = text[:remaining]
        remaining -= len(text)
        output.append(f'<context_file path="{rel}">\n{text}\n</context_file>')
    return output


def _validate_artifact_refs(parent_chat_id: str, refs: list[str]) -> tuple[list[str], list[str]]:
    workspace = _workspace_path(parent_chat_id, create=True).resolve()
    valid: list[str] = []
    gaps: list[str] = []
    for raw in refs[:100]:
        rel = str(raw or "")
        if not rel or Path(rel).is_absolute():
            gaps.append(f"Rejected non-relative artifact reference: {rel!r}")
            continue
        candidate = (workspace / rel).resolve()
        try:
            candidate.relative_to(workspace)
        except ValueError:
            gaps.append(f"Rejected artifact outside parent workspace: {rel!r}")
            continue
        if not candidate.exists():
            gaps.append(f"Referenced artifact was not observed on disk: {rel!r}")
            continue
        valid.append(rel)
    return valid, gaps


def _final_text(state: dict[str, Any]) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage) or getattr(message, "type", "") == "ai":
            content = getattr(message, "content", "")
            return content if isinstance(content, str) else str(content)
    return ""


async def run_child_conversation(
    parent_chat_id: str,
    task_id: str,
    prompt: str,
    context_files: Optional[list[str]] = None,
    max_iters: Optional[int] = None,
    *,
    record_state: bool = True,
) -> ChildResult:
    _validate_identity(parent_chat_id, "chat_id")
    _validate_identity(task_id, "task_id")
    effective_max_iters = max(1, min(int(max_iters or MCOP_CHILD_MAX_ITERS), MCOP_CHILD_MAX_ITERS))
    task_dir = _get_task_dir(parent_chat_id, task_id)
    result_file = task_dir / "result.json"
    if result_file.is_file():
        try:
            return ChildResult.from_mapping(json.loads(result_file.read_text(encoding="utf-8")))
        except Exception:
            pass

    started = datetime.now(timezone.utc).isoformat()
    (task_dir / "prompt.txt").write_text(str(prompt), encoding="utf-8")
    context_parts = _read_context(parent_chat_id, context_files)
    context_parts.append(f"<task>\n{prompt}\n</task>")
    full_input = "\n\n".join(context_parts)

    result = ChildResult(task_id=task_id, status="running", started_at=started)
    interceptor.thought(f"MCOP child start: {task_id}", "child_spawn")
    try:
        graph = _build_child_graph()
        graph_config = {
            "configurable": {"thread_id": f"mcop-{task_id}-{uuid.uuid4().hex[:8]}"},
            "recursion_limit": max(10, effective_max_iters * 3 + 5),
        }
        final_state = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=full_input)],
                "chat_id": parent_chat_id,
                "task_id": task_id,
                "iterations": 0,
                "max_iters": effective_max_iters,
            },
            config=graph_config,
        )
        raw_final = _final_text(final_state)
        iterations_used = int(final_state.get("iterations", 0))
        packet = try_parse_tool_evidence_packet(raw_final, task_id)

        if packet is None:
            raw_path = task_dir / "unparsed_final_response.txt"
            raw_path.write_text(raw_final[: max(MCOP_RESULT_MAX_CHARS * 4, 48_000)], encoding="utf-8")
            raw_rel = raw_path.relative_to(_workspace_path(parent_chat_id, create=True)).as_posix()
            packet = normalize_worker_packet_from_summary(
                task_id=task_id,
                summary=raw_final[:MCOP_RESULT_MAX_CHARS],
                status="partial",
                artifacts=[raw_rel],
            )

        artifacts, artifact_gaps = _validate_artifact_refs(parent_chat_id, packet.raw_artifacts)
        if artifact_gaps:
            packet.gaps.extend(artifact_gaps)
            if packet.status == "completed":
                packet.status = "partial"

        packet.raw_artifacts = artifacts
        packet_file = task_dir / "tool_evidence_packet.json"
        _atomic_write_json(packet_file, packet.to_dict())

        result = ChildResult(
            task_id=task_id,
            status=packet.status,
            artifacts=list(artifacts),
            raw_artifacts=list(artifacts),
            summary=packet.summary[:MCOP_RESULT_MAX_CHARS],
            iterations_used=iterations_used,
            facts=list(packet.facts),
            inferences=list(packet.inferences),
            gaps=list(packet.gaps),
            errors=list(packet.errors),
            next_recommended_step=packet.next_recommended_step,
            packet_path=packet_file.relative_to(_workspace_path(parent_chat_id, create=True)).as_posix(),
            started_at=started,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        logger.exception("MCOP child %s failed", task_id)
        result = ChildResult(
            task_id=task_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            errors=[f"{type(exc).__name__}: {exc}"],
            started_at=started,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

    _atomic_write_json(result_file, result.to_dict())
    if record_state:
        state = OrchestrationState.load(parent_chat_id)
        state.tasks[task_id] = result
        state.total_tokens += max(0, int(result.tokens_used))
        state.save()
    interceptor.thought(
        f"MCOP child finished: {task_id} status={result.status} iterations={result.iterations_used}",
        "child_complete",
    )
    return result


async def run_parallel_tasks(parent_chat_id: str, tasks: list[dict[str, Any]]) -> list[ChildResult]:
    semaphore = asyncio.Semaphore(max(1, MCOP_PARALLEL_LIMIT))

    async def run_one(task: dict[str, Any]) -> ChildResult:
        async with semaphore:
            return await run_child_conversation(
                parent_chat_id=parent_chat_id,
                task_id=str(task["task_id"]),
                prompt=str(task["prompt"]),
                context_files=list(task.get("context_files") or []),
                max_iters=int(task.get("max_iters") or MCOP_CHILD_MAX_ITERS),
                record_state=False,
            )

    results = await asyncio.gather(*(run_one(task) for task in tasks))
    state = OrchestrationState.load(parent_chat_id)
    for result in results:
        state.tasks[result.task_id] = result
        state.total_tokens += max(0, int(result.tokens_used))
    state.save()
    return list(results)
