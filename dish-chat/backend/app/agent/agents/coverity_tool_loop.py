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

from langchain_core.messages import AIMessage

from . import coverity_tool_loop_token_limit as implementation
from .artifact_readback import readback, render

logger = logging.getLogger(__name__)
CONTRACT = 'agentpi-live-planner-v1'
# Captured when imported, NOT reread from a potentially newer checkout per GET.
LOADED_ENTRYPOINT_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
LOADED_IMPLEMENTATION_SHA256 = hashlib.sha256(Path(implementation.__file__).read_bytes()).hexdigest()
COUNTERS = {'entered': 0, 'runtime_probe': 0, 'mcop_description': 0, 'artifact_readback': 0}


def execution_identity() -> dict:
    return {'contract': CONTRACT, 'entrypoint_module': __name__,
            'implementation_module': implementation.__name__,
            'loaded_entrypoint_sha256': LOADED_ENTRYPOINT_SHA256,
            'loaded_implementation_sha256': LOADED_IMPLEMENTATION_SHA256,
            'mcop': {'name': 'Multi-Conversation Orchestration Protocol',
                     'implemented_in_this_revision': False},
            'calls_since_import': dict(COUNTERS)}


def _mcop_question(text: str, messages: list) -> bool:
    # Do not intercept requests to actually implement or change MCOP.
    if re.search(r'\b(?:implement|integrate|build|add|enable|disable)\b', text, re.I):
        return False
    if re.search(r'\bmcop\b', text, re.I):
        return True
    if re.fullmatch(r'\s*(?:please\s+)?(?:test|demonstrate|exhibit)[\s\w,]*\b(?:it|action)\b[.!?\s]*', text, re.I):
        previous = [implementation._content_to_text(getattr(m, 'content', ''))
                    for m in messages if getattr(m, 'type', '') in {'human', 'user'}]
        return len(previous) >= 2 and bool(re.search(r'\bmcop\b', previous[-2], re.I))
    return False


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
    COUNTERS['entered'] += 1
    logger.info('LIVE_PLANNER_ENTRY contract=%s implementation=%s', CONTRACT, implementation.__name__)

    if _mcop_question(text, messages):
        COUNTERS['mcop_description'] += 1
        names = sorted({implementation._tool_name(t) for t in tools})
        return AIMessage(content=(
            'MCOP means Multi-Conversation Orchestration Protocol. It is NOT implemented in this AgentPi revision. '
            'The repository contains an integration plan, not an operational MCOP worker system. '
            'No child conversation, parallel worker, or MCOP demonstration was started by this request.\n\n'
            'Bound tool names for this conversation (binding is not a health or execution test):\n'
            + ', '.join(names) + '\n\n'
            'Ordinary Python, network, and inventory tool calls are not evidence of MCOP. '
            'Shell allowlisting is not an OS security sandbox; optional tools may use remote services. '
            'The provider/model version and service health are not inferred from this inventory.'
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
