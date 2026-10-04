"""Live entry point shared by chat and Agent Mode.

There used to be a second, stale planner implementation in this file. Keep the
implementation in ONE module and test this import path through its callers.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
import re
from typing import Any
import uuid
import json

from langchain_core.messages import AIMessage

from . import coverity_tool_loop_token_limit as implementation
from .artifact_readback import readback, render

logger = logging.getLogger(__name__)
CONTRACT = 'agentpi-live-planner-v1'
# Captured when imported, NOT reread from a potentially newer checkout per GET.
LOADED_ENTRYPOINT_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
LOADED_IMPLEMENTATION_SHA256 = hashlib.sha256(Path(implementation.__file__).read_bytes()).hexdigest()
MCOP_TOOL_NAMES = (
    'agent_spawn_task',
    'agent_spawn_parallel',
    'agent_check_tasks',
    'agent_read_task_result',
    'agent_read_packet',
)
COUNTERS = {
    'entered': 0,
    'runtime_probe': 0,
    'mcop_description': 0,
    'mcop_demo': 0,
    'artifact_readback': 0,
}


def execution_identity() -> dict:
    return {'contract': CONTRACT, 'entrypoint_module': __name__,
            'implementation_module': implementation.__name__,
            'loaded_entrypoint_sha256': LOADED_ENTRYPOINT_SHA256,
            'loaded_implementation_sha256': LOADED_IMPLEMENTATION_SHA256,
            'mcop': {
                'name': 'Multi-Conversation Orchestration Protocol',
                'contract': 'agentpi-mcop-v1',
                'implemented_in_this_revision': True,
                'expected_tool_names': list(MCOP_TOOL_NAMES),
            },
            'calls_since_import': dict(COUNTERS)}


def _mcop_demo_request(text: str, messages: list) -> bool:
    # Explicit subject: never depend on conversation history.
    if re.search(r'\b(?:test|demonstrate|demo|exhibit|show)\b[^\n]{0,120}\bmcop\b', text, re.I):
        return True

    # Pronoun follow-up ("test/exhibit it") is only MCOP when recent context
    # actually names MCOP. Inspect BOTH assistant and user turns; the preceding
    # MCOP description is normally an assistant message.
    if re.fullmatch(
        r'\s*(?:please\s+)?(?:test|demonstrate|demo|exhibit|show)[\s\w,]*\b(?:it|action)\b[.!?\s]*',
        text,
        re.I,
    ):
        recent: list[str] = []
        skipped_current = False
        for message in reversed(messages):
            content = implementation._content_to_text(getattr(message, 'content', '')).strip()
            if not content:
                continue
            role = getattr(message, 'type', '')
            if not skipped_current and role in {'human', 'user'} and content == text.strip():
                skipped_current = True
                continue
            recent.append(content)
            if len(recent) >= 4:
                break
        return any(re.search(r'\bmcop\b', item, re.I) for item in recent)
    return False


def _mcop_question(text: str, messages: list) -> bool:
    # Implementation/change requests and explicit demonstrations must reach an
    # execution path rather than being answered by the read-only description.
    if re.search(r'\b(?:implement|integrate|build|add|enable|disable)\b', text, re.I):
        return False
    if _mcop_demo_request(text, messages):
        return False
    return bool(re.search(r'\bmcop\b', text, re.I))


def _validate_mcop_demo_result(result_text: str, task_id: str) -> tuple[bool, list[str], dict]:
    """Validate the deterministic MCOP smoke receipt before calling it successful."""
    reasons: list[str] = []
    try:
        payload = json.loads(str(result_text or ""))
    except Exception:
        return False, ["spawn result was not valid JSON"], {}

    if not isinstance(payload, dict):
        return False, ["spawn result was not a JSON object"], {}

    if payload.get("contract") != "agentpi-mcop-v1":
        reasons.append("unexpected or missing MCOP contract")
    if payload.get("task_id") != task_id:
        reasons.append("task_id mismatch")
    if payload.get("status") != "completed":
        reasons.append(f"status={payload.get('status')!r}, expected 'completed'")

    try:
        iterations = int(payload.get("iterations_used") or 0)
    except Exception:
        iterations = 0
    if iterations < 1:
        reasons.append("child did not complete an agent iteration")

    gaps = payload.get("gaps")
    errors = payload.get("errors")
    if gaps not in ([], None):
        reasons.append("child reported evidence gaps")
    if errors not in ([], None):
        reasons.append("child reported errors")

    packet_path = payload.get("packet_path")
    if not isinstance(packet_path, str) or not packet_path.endswith("/tool_evidence_packet.json"):
        reasons.append("durable tool_evidence_packet path missing")

    expected_claim = f"MCOP_SMOKE_EXECUTED:{task_id}"
    facts = payload.get("facts")
    fact_ok = False
    if isinstance(facts, list):
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            if (
                str(fact.get("claim") or "") == expected_claim
                and str(fact.get("confidence") or "").lower() == "high"
                and str(fact.get("source") or "") == "agentpi_mcop_runtime"
            ):
                fact_ok = True
                break
    if not fact_ok:
        reasons.append(f"missing required high-confidence fact {expected_claim!r}")

    return not reasons, reasons, payload


def _completion_review(text: str, messages: list) -> bool:
    if not re.search(r'\b(?:did you finish|is it (?:done|finished|complete)|where (?:are|is) (?:the |my )?(?:files?|app|shortcut)|were the files written)\b', text, re.I):
        return False
    prior = '\n'.join(implementation._content_to_text(getattr(m, 'content', ''))[-4000:] for m in messages[-10:])
    return bool(re.search(r'\b(?:script|app|application|shortcut|files?)\b|\.(?:py|lnk)\b', prior, re.I))


async def _artifact_observation(chat_id: str | None) -> str:
    # Same configured base as the real executor; no model-supplied root path.
    from app.agent_mode.tools import BASE_AGENT_WORKDIR
    COUNTERS['artifact_readback'] += 1
    return render(await asyncio.to_thread(readback, Path(BASE_AGENT_WORKDIR), chat_id))


async def run_coverity_tool_loop(model: Any = None, tools=None, messages=None,
                                  config=None, max_steps=None, **kwargs) -> AIMessage:
    if isinstance(model, list) and tools is None and messages is None:
        tools, model = model, None
    tools = tools or kwargs.get('available_tools') or []
    messages = messages or kwargs.get('state_messages') or []
    text = implementation._extract_last_user_text(messages)
    chat_id = implementation._extract_chat_id(config)
    try:
        is_mcop_child = bool((config or {}).get('configurable', {}).get('mcop_child'))
    except Exception:
        is_mcop_child = False
    COUNTERS['entered'] += 1
    logger.info('LIVE_PLANNER_ENTRY contract=%s implementation=%s', CONTRACT, implementation.__name__)

    if not is_mcop_child and _mcop_demo_request(text, messages):
        COUNTERS['mcop_demo'] += 1
        if not chat_id:
            return AIMessage(content=(
                'MCOP_DEMO_BLOCKED: current chat/workspace identity is missing. '
                'No child conversation was started.'
            ))
        normalized = implementation._normalize_tools(tools)
        tool_map = {tool.name: tool for tool in normalized}
        selected = tool_map.get('agent_spawn_task')
        if selected is None:
            return AIMessage(content=(
                'MCOP_DEMO_BLOCKED: agent_spawn_task is not bound to this conversation. '
                'No child conversation was started.'
            ))
        task_id = 'mcop-demo-' + uuid.uuid4().hex[:8]
        expected_claim = f'MCOP_SMOKE_EXECUTED:{task_id}'
        demo_prompt = (
            'Perform a controlled MCOP smoke test. Do not call any tools. '
            'Return a valid ToolEvidencePacket as your final child evidence. '
            'Set status to completed. Include exactly one high-confidence fact '
            f'whose claim is exactly {expected_claim!r}. '
            'Leave raw_artifacts empty, gaps empty, and errors empty. '
            'Do not claim any external action.'
        )
        try:
            result = await implementation._invoke_tool(
                selected.raw,
                {
                    'chat_id': chat_id,
                    'task_prompt': demo_prompt,
                    'task_id': task_id,
                    'context_files': '[]',
                    'max_iters': 2,
                },
                chat_id=chat_id,
            )
        except Exception as exc:
            return AIMessage(content=(
                'MCOP_DEMO_FAILED: agent_spawn_task raised '
                f'{type(exc).__name__}. No successful child result was returned.'
            ))
        result_text = implementation._content_to_text(result)
        ok, reasons, payload = _validate_mcop_demo_result(result_text, task_id)
        if not ok:
            return AIMessage(content=(
                'MCOP_DEMO_INCOMPLETE: agent_spawn_task returned a real child receipt, '
                'but it did not satisfy the deterministic smoke-test acceptance contract.\n'
                'Reasons: ' + '; '.join(reasons) + '\n\n'
                'Actual agent_spawn_task output:\n' + result_text
            ))
        return AIMessage(content=(
            'MCOP demonstration verified (actual agent_spawn_task output):\n\n'
            + json.dumps(payload, ensure_ascii=False)
        ))

    if not is_mcop_child and _mcop_question(text, messages):
        COUNTERS['mcop_description'] += 1
        names = sorted({implementation._tool_name(t) for t in tools})
        bound_mcop = [name for name in MCOP_TOOL_NAMES if name in names]
        missing_mcop = [name for name in MCOP_TOOL_NAMES if name not in names]
        return AIMessage(content=(
            'MCOP means Multi-Conversation Orchestration Protocol. It is implemented in this AgentPi revision '
            'as bounded depth-one child orchestration with durable task/evidence receipts.\n\n'
            'Bound MCOP tools in this conversation:\n'
            + (', '.join(bound_mcop) if bound_mcop else '[none]') + '\n\n'
            + ('Missing expected MCOP bindings: ' + ', '.join(missing_mcop) + '\n\n'
               if missing_mcop else
               'All expected MCOP parent tools are bound.\n\n')
            + 'This description request did not spawn a child. For an unambiguous live smoke test, say '
            '"test MCOP in action". A contextual follow-up such as "please test and exhibit it in action" '
            'also routes to agent_spawn_task when recent conversation context names MCOP. Binding alone '
            'does not prove provider readiness or successful execution.'
        ))
    if _completion_review(text, messages):
        return AIMessage(content=await _artifact_observation(chat_id))
    if implementation._runtime_probe_payload(text) is not None:
        COUNTERS['runtime_probe'] += 1
    answer = await implementation.run_coverity_tool_loop(
        model=model, tools=tools, messages=messages, config=config, max_steps=max_steps, **kwargs)
    # A local artifact task cannot be certified by an ungrounded completion
    # sentence. Return bounded readback instead, even if a file already exists.
    # Existence alone does not certify creation this turn or functional testing.
    if (implementation._looks_like_local_execution_request(text)
            and implementation._runtime_probe_payload(text) is None
            and re.search(r'\b(?:write|build|create|generate)\b', text, re.I)
            and re.search(r'\b(?:complete|completed|created|written|saved|built|verified|done)\b',
                          implementation._content_to_text(answer.content), re.I)):
        return AIMessage(content=await _artifact_observation(chat_id))
    return answer
