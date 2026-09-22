from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
import logging

from app.core.llm import get_model
from app.core.llm.coverity_assist_chat_model import CoverityAssistChatModel
from .host_context import build_host_context

logger = logging.getLogger(__name__)


@dataclass
class NormalizedTool:
    name: str
    description: str
    raw: Any


def _tool_name(tool: Any) -> str:
    return getattr(tool, "name", None) or getattr(tool, "__name__", None) or tool.__class__.__name__


def _tool_description(tool: Any) -> str:
    return getattr(tool, "description", None) or inspect.getdoc(tool) or f"Tool {_tool_name(tool)}"


def _normalize_tools(tools: Iterable[Any]) -> list[NormalizedTool]:
    return [NormalizedTool(name=_tool_name(t), description=_tool_description(t), raw=t) for t in tools]


def _extract_chat_id(config: Any) -> Optional[str]:
    try:
        if isinstance(config, dict):
            return config.get("configurable", {}).get("thread_id")
        if hasattr(config, "get"):
            return config.get("configurable", {}).get("thread_id")
    except Exception:
        pass
    return None


def _inject_chat_id_if_needed(tool: Any, tool_input: Any, chat_id: Optional[str]) -> Any:
    if not chat_id:
        return tool_input
    try:
        if hasattr(tool, "args_schema") and tool.args_schema is not None:
            fields = getattr(tool.args_schema, "model_fields", None) or getattr(tool.args_schema, "__fields__", {})
            if "chat_id" in fields:
                if isinstance(tool_input, dict):
                    tool_input.setdefault("chat_id", chat_id)
                    return tool_input
                return {"chat_id": chat_id, "input": tool_input}
    except Exception:
        pass
    try:
        sig = inspect.signature(tool if callable(tool) else tool.invoke)
        if "chat_id" in sig.parameters:
            if isinstance(tool_input, dict):
                tool_input.setdefault("chat_id", chat_id)
                return tool_input
            return {"chat_id": chat_id, "input": tool_input}
    except Exception:
        pass
    return tool_input


async def _invoke_tool(tool: Any, tool_input: Any, chat_id: Optional[str] = None) -> Any:
    tool_input = _inject_chat_id_if_needed(tool, tool_input, chat_id)
    if hasattr(tool, "ainvoke"):
        return await tool.ainvoke(tool_input)
    if hasattr(tool, "invoke"):
        return tool.invoke(tool_input)
    if asyncio.iscoroutinefunction(tool):
        if isinstance(tool_input, dict):
            try:
                return await tool(**tool_input)
            except TypeError:
                return await tool(tool_input)
        return await tool(tool_input)
    if callable(tool):
        if isinstance(tool_input, dict):
            try:
                return tool(**tool_input)
            except TypeError:
                return tool(tool_input)
        return tool(tool_input)
    raise TypeError(f"Unsupported tool type: {type(tool)!r}")


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for item in content:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    out.append(str(item.get("text", "")))
                else:
                    out.append(json.dumps(item, ensure_ascii=False))
            else:
                out.append(str(item))
        return "\n".join(x for x in out if x)
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text", ""))
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _extract_last_user_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if getattr(msg, "type", "").lower() in {"human", "user"}:
            text = _content_to_text(getattr(msg, "content", ""))
            if text.strip():
                return text.strip()
    return ""


def _render_recent_transcript(messages: list[BaseMessage], limit: int = 10) -> str:
    trimmed = messages[-limit:]
    lines: list[str] = []
    for msg in trimmed:
        role = getattr(msg, "type", "unknown").lower()
        prefix = "User" if role in {"human", "user"} else "Assistant" if role in {"ai", "assistant"} else "System" if role == "system" else role.title()
        text = _content_to_text(getattr(msg, "content", "")).strip()
        if text:
            lines.append(f"{prefix}: {text}")
    return "\n".join(lines)


def _extract_system_text(messages: list[BaseMessage]) -> str:
    parts: list[str] = []
    for msg in messages:
        if getattr(msg, "type", "").lower() == "system":
            text = _content_to_text(getattr(msg, "content", ""))
            if text.strip():
                parts.append(text.strip())
    return "\n\n".join(parts)


def _extract_json_objects(text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    text = text.strip()
    if not text:
        return candidates
    for candidate in [text]:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                candidates.append(obj)
        except Exception:
            pass
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                candidates.append(obj)
        except Exception:
            pass
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict):
                    candidates.append(obj)
            except Exception:
                pass
    return candidates


def _pick_action_payload(text: str) -> Optional[dict[str, Any]]:
    candidates = _extract_json_objects(text)
    if not candidates:
        return None
    for obj in reversed(candidates):
        if str(obj.get("action", "")).lower() in {"tool", "final"}:
            return obj
    return candidates[-1]


def _render_tool_catalog(tools: list[NormalizedTool]) -> str:
    return "\n".join(f"- {tool.name}: {tool.description}" for tool in tools)


def _planner_model(model: Any) -> Any:
    """Use a smaller completion budget for the planner/summarizer loop."""
    try:
        if getattr(model, "_llm_type", "") == "coverity-assist":
            cap = int(str(os.getenv("COVERITY_ASSIST_PLANNER_MAX_TOKENS", "2048")).replace("_", ""))
            return CoverityAssistChatModel(
                endpoint_url=getattr(model, "endpoint_url"),
                bearer_token=getattr(model, "bearer_token"),
                max_tokens=max(256, min(int(getattr(model, "max_tokens", cap)), cap)),
                request_timeout=getattr(model, "request_timeout", 600),
                verify_ssl=getattr(model, "verify_ssl", True),
                use_top_level_system=getattr(model, "use_top_level_system", False),
                inference_profile_arn=getattr(model, "inference_profile_arn", None),
                include_system_prompt=getattr(model, "include_system_prompt", True),
            )
    except Exception:
        logger.exception("Failed to create dedicated planner model; falling back to original model.")
    return model


def _looks_like_fresh_info_request(user_text: str) -> bool:
    t = user_text.lower()
    return any(phrase in t for phrase in ["who won", "what happened", "today", "latest", "current", "news", "superbowl", "super bowl", "score", "winner"])


def _looks_like_network_request(user_text: str) -> bool:
    t = user_text.lower()
    return any(phrase in t for phrase in ["network devices", "local network", "list devices on the network", "show neighbors", "arp", "ip neigh"])


def _looks_like_host_health_request(user_text: str) -> bool:
    t = user_text.lower()
    return any(phrase in t for phrase in ["host machine", "diagnose its overall health", "diagnose host", "system health", "machine health", "server health"])


def _looks_like_file_request(user_text: str) -> bool:
    t = user_text.lower()
    return any(phrase in t for phrase in ["host files", "list files", "show files", "filesystem", "working directory"])


def _looks_like_video_request(user_text: str) -> bool:
    t = user_text.lower()
    return any(phrase in t for phrase in ["video device", "snapshot", "camera", "pro capture", "magewell", "vlc", "stream", "hdmi 00-0", "0-00"])


def _looks_like_repo_or_path_request(user_text: str) -> bool:
    return bool(re.search(r"(/mnt/[^\s]+|[A-Za-z]:\\\\[^\n]+)", user_text)) or "analyze it in your sandbox" in user_text.lower()


def _extract_path(user_text: str) -> Optional[str]:
    m = re.search(r"(/mnt/[^\s]+)", user_text)
    if m:
        return m.group(1)
    return None


def _shell_cmd_for_path(path: str) -> str:
    return f"""bash -lc 'target="{path}"; echo "TARGET:$target"; if [ -e "$target" ]; then echo "=== ls -la ==="; ls -la "$target"; echo; echo "=== shallow tree ==="; find "$target" -maxdepth 3 -printf "%y %p\n" | head -n 400; else echo "PATH_NOT_FOUND"; fi'"""


def _shell_cmd_for_video() -> str:
    return """bash -lc 'echo "=== WSL / host context ==="; uname -a; echo; cat /proc/version 2>/dev/null; echo; echo "=== Video nodes ==="; ls -l /dev/video* 2>/dev/null || true; echo; echo "=== v4l by-path ==="; ls -l /dev/v4l/by-path 2>/dev/null || true; echo; echo "=== v4l2-ctl ==="; v4l2-ctl --list-devices 2>/dev/null || true; echo; echo "=== lsusb (video/capture) ==="; lsusb 2>/dev/null | egrep -i "magewell|camera|video|capture|hdmi" || true; echo; echo "=== Linux VLC/ffmpeg processes ==="; ps aux | egrep -i "vlc|ffmpeg|obs|magewell" | grep -v grep || true; echo; echo "=== Windows VLC processes ==="; powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object {$_.Name -match ''vlc|obs|ffmpeg''} | Select-Object Name,ProcessId,CommandLine | Format-List" 2>/dev/null || true; echo; echo "=== Listening sockets ==="; ss -tulpn 2>/dev/null | head -n 80 || true'"""


def _shell_cmd_for_network() -> str:
    return """bash -lc 'echo "Hostname:"; hostname; echo; echo "Interfaces:"; (ip -br addr 2>/dev/null || ifconfig -a 2>/dev/null || cat /proc/net/dev); echo; echo "Neighbors / ARP:"; (ip neigh 2>/dev/null || arp -a 2>/dev/null || true)'"""


def _shell_cmd_for_host_health() -> str:
    return """bash -lc 'echo "Hostname:"; hostname; echo; echo "Uptime:"; uptime; echo; echo "Kernel:"; uname -a; echo; echo "Disk:"; df -h; echo; echo "Memory:"; (free -h 2>/dev/null || cat /proc/meminfo | head -n 20); echo; echo "CPU/Load:"; cat /proc/loadavg 2>/dev/null; echo; echo "Top processes:"; ps aux --sort=-%mem | head -n 15; echo; echo "Sockets:"; ss -tulpn 2>/dev/null | head -n 50'"""


def _shell_cmd_for_files() -> str:
    return """bash -lc 'echo "PWD:"; pwd; echo; echo "Top-level files in /:"; ls -la /; echo; echo "Current dir listing:"; ls -la; echo; echo "Windows Desktop candidates:"; ls -la /mnt/c/Users/*/Desktop 2>/dev/null | head -n 200 || true'"""


async def _search_harder(query: str, tool: Any, chat_id: Optional[str]) -> str:
    queries = [query.strip()]
    q = query.lower().strip()
    if "super bowl" in q or "superbowl" in q:
        queries.extend([
            "2026 super bowl winner",
            "super bowl lx winner",
            "2026 nfl championship winner",
        ])
    elif "who won" in q:
        queries.append(re.sub(r"\bwho won\b", "winner", query, flags=re.I))
    elif "today" in q or "latest" in q or "current" in q:
        queries.append(query + " latest")
    seen = set()
    outputs = []
    for qx in queries:
        qx = qx.strip()
        if not qx or qx in seen:
            continue
        seen.add(qx)
        try:
            result = await _invoke_tool(tool, qx, chat_id=chat_id)
        except Exception as exc:
            outputs.append(f"Query: {qx}\nError: {exc}")
            continue
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        outputs.append(f"Query: {qx}\n{text}")
        if re.search(r'("results"\s*:\s*\[[^\]]+\]|https?://|winner|won|score|date)', text, re.I):
            break
    return "\n\n".join(outputs)


async def _maybe_handle_obvious_direct_task(user_text: str, tool_map: dict[str, NormalizedTool], chat_id: Optional[str]) -> Optional[str]:
    if _looks_like_repo_or_path_request(user_text) and "agent_run_shell" in tool_map:
        path = _extract_path(user_text)
        if path:
            return await _invoke_tool(tool_map["agent_run_shell"].raw, {"command": _shell_cmd_for_path(path), "cwd": "/tmp", "timeout_seconds": 180}, chat_id=chat_id)
    if _looks_like_video_request(user_text) and "agent_run_shell" in tool_map:
        return await _invoke_tool(tool_map["agent_run_shell"].raw, {"command": _shell_cmd_for_video(), "cwd": "/tmp", "timeout_seconds": 240}, chat_id=chat_id)
    if _looks_like_fresh_info_request(user_text) and "public_web_search" in tool_map:
        return await _search_harder(user_text, tool_map["public_web_search"].raw, chat_id)
    if _looks_like_network_request(user_text) and "agent_run_shell" in tool_map:
        return await _invoke_tool(tool_map["agent_run_shell"].raw, {"command": _shell_cmd_for_network(), "cwd": "/tmp", "timeout_seconds": 120}, chat_id=chat_id)
    if _looks_like_host_health_request(user_text) and "agent_run_shell" in tool_map:
        return await _invoke_tool(tool_map["agent_run_shell"].raw, {"command": _shell_cmd_for_host_health(), "cwd": "/tmp", "timeout_seconds": 180}, chat_id=chat_id)
    if _looks_like_file_request(user_text) and "agent_run_shell" in tool_map:
        return await _invoke_tool(tool_map["agent_run_shell"].raw, {"command": _shell_cmd_for_files(), "cwd": "/tmp", "timeout_seconds": 120}, chat_id=chat_id)
    return None


def _build_planner_prompt(user_text: str, recent_transcript: str, system_text: str, tools: list[NormalizedTool], scratchpad: list[str], chat_id: Optional[str]) -> str:
    tool_catalog = _render_tool_catalog(tools)
    scratch = "\n\n".join(scratchpad).strip()
    host_context = build_host_context()
    parts = [
        "You are Dish-Agent running in tool-planner mode.",
        "You DO have access to real tools on the host running Dish-Chat.",
        "You must not claim that you lack host access when a listed tool can do the job.",
        "",
        "Trusted environment facts:",
        host_context,
        "",
        "Routing rules:",
        "1. For host files, processes, VLC, capture cards, cameras, peripherals, Windows host questions, and bash commands, prefer agent_run_shell.",
        "2. For a literal path like /mnt/c/... inspect THAT path directly with shell tools instead of cloning anything.",
        "3. For fresh/current facts, use public_web_search and retry with tighter queries before saying you could not find it.",
        "4. Use the recent transcript for follow-ups like 'do it again'.",
        "5. If a tool is needed, respond with JSON ONLY and nothing else.",
        '{"action":"tool","tool":"TOOL_NAME","input":"TEXT_OR_JSON"}',
        '{"action":"final","final":"YOUR FINAL ANSWER"}',
        "",
        "Available tools:",
        tool_catalog,
    ]
    if chat_id:
        parts.extend(["", f"Current chat_id: {chat_id}"])
    if system_text:
        parts.extend(["", "System guidance:", system_text])
    if recent_transcript:
        parts.extend(["", "Recent conversation transcript:", recent_transcript])
    parts.extend(["", "Current user request:", user_text])
    if scratch:
        parts.extend(["", "Tool work so far:", scratch])
    return "\n".join(parts)


async def _summarize_tool_result(model: Any, user_text: str, result_text: str, config: Any = None) -> str:
    prompt = (
        "You are Dish-Agent. Summarize the REAL tool output below for the user. "
        "Do not invent results. If the output is partial or inconclusive, say so. "
        "If the user asked for analysis of a path or repository, infer structure and intended functions only from the provided file listings/output, and state when deeper file reads would be needed.\n\n"
        f"User request:\n{user_text}\n\n"
        f"Tool output:\n{result_text[:16000]}"
    )
    logger.info("Planner summary prompt chars=%d", len(prompt))
    response = await model.ainvoke([HumanMessage(content=prompt)], config=config)
    return _content_to_text(getattr(response, "content", response)).strip()


async def run_coverity_tool_loop(model: Any = None, tools: Optional[list[Any]] = None, messages: Optional[list[BaseMessage]] = None, config: Any = None, max_steps: Optional[int] = None, **kwargs: Any) -> AIMessage:
    if model is not None and isinstance(model, list) and tools is None and messages is None:
        tools = model
        model = None
    model = model or kwargs.get("model_with_tools") or kwargs.get("llm") or get_model()
    planner_model = _planner_model(model)
    tools = tools or kwargs.get("available_tools") or []
    messages = messages or kwargs.get("state_messages") or []

    normalized_tools = _normalize_tools(tools)
    tool_map = {tool.name: tool for tool in normalized_tools}

    user_text = _extract_last_user_text(messages)
    recent_transcript = _render_recent_transcript(messages, limit=10)
    system_text = _extract_system_text(messages)
    chat_id = _extract_chat_id(config)

    direct_tool_result = await _maybe_handle_obvious_direct_task(user_text, tool_map, chat_id)
    if direct_tool_result is not None:
        final_text = await _summarize_tool_result(model, user_text, str(direct_tool_result), config=config)
        return AIMessage(content=final_text)

    planner_steps = max_steps or int(os.getenv("COVERITY_ASSIST_TOOL_MAX_STEPS", "6"))
    scratchpad: list[str] = []
    last_text = ""

    for _ in range(planner_steps):
        planner_prompt = _build_planner_prompt(user_text, recent_transcript, system_text, normalized_tools, scratchpad, chat_id)
        logger.info("Planner loop prompt chars=%d, steps=%d", len(planner_prompt), planner_steps)
        response = await planner_model.ainvoke([HumanMessage(content=planner_prompt)], config=config)
        last_text = _content_to_text(getattr(response, "content", response)).strip()

        payload = _pick_action_payload(last_text)
        if not payload:
            return AIMessage(content=last_text)
        action = str(payload.get("action", "")).lower().strip()
        if action == "final":
            return AIMessage(content=str(payload.get("final", "")).strip())
        if action != "tool":
            return AIMessage(content=last_text)

        tool_name = str(payload.get("tool", "")).strip()
        tool_input = payload.get("input", "")
        if tool_name not in tool_map:
            scratchpad.append(f"Tool error: requested unknown tool '{tool_name}'. Available tools: {', '.join(tool_map.keys())}")
            continue

        selected = tool_map[tool_name]
        try:
            result = await _invoke_tool(selected.raw, tool_input, chat_id=chat_id)
        except Exception as exc:
            result = f"Tool {selected.name} failed: {exc}"

        if not isinstance(result, str):
            try:
                result = json.dumps(result, ensure_ascii=False, default=str)
            except Exception:
                result = str(result)
        scratchpad.append(f"Tool used: {selected.name}\nInput: {tool_input}\nResult: {result[:8000]}")

    if scratchpad:
        grounded = await _summarize_tool_result(model, user_text, "\n\n".join(scratchpad), config=config)
        return AIMessage(content=grounded)
    return AIMessage(content=last_text or "I couldn't complete the tool workflow.")
