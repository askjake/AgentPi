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
from app.agent.agents.search_renderer import render_public_search_output
from .host_context import build_host_context

logger = logging.getLogger(__name__)
SCRATCHPAD_LIMIT = 8_000   # PATCH-05
SUMMARIZER_LIMIT = 16_000  # PATCH-05
_COVERITY_LLM_TYPES = {"coverity-assist", "coverity-assist-tool-enabled"}  # PATCH-06


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
    """Dispatch once; synchronous adapters must not block the ASGI event loop."""
    tool_input = _inject_chat_id_if_needed(tool, tool_input, chat_id)
    name = _tool_name(tool)
    logger.info("TOOL_DISPATCH tool=%s state=started", name)
    try:
        if hasattr(tool, "ainvoke"):
            result = await tool.ainvoke(tool_input)
        elif hasattr(tool, "invoke"):
            result = await asyncio.to_thread(tool.invoke, tool_input)
        elif callable(tool):
            call_args = (tool_input,)
            call_kwargs = {}
            if isinstance(tool_input, dict):
                # Decide the calling convention BEFORE execution. A TypeError
                # raised inside a tool must never cause a second invocation.
                try:
                    inspect.signature(tool).bind(**tool_input)
                except (TypeError, ValueError):
                    pass
                else:
                    call_args, call_kwargs = (), tool_input
            if asyncio.iscoroutinefunction(tool):
                result = await tool(*call_args, **call_kwargs)
            else:
                result = await asyncio.to_thread(tool, *call_args, **call_kwargs)
        else:
            raise TypeError(f"Unsupported tool type: {type(tool)!r}")
    except Exception as exc:
        logger.warning("TOOL_DISPATCH tool=%s state=raised error_type=%s", name, type(exc).__name__)
        raise
    # 'returned' is not 'succeeded': existing tools can return error strings.
    logger.info("TOOL_DISPATCH tool=%s state=returned", name)
    return result


def _content_to_text(content: Any) -> str:
    """Return user-visible textual content while ignoring provider transport metadata."""
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
                elif "cachePoint" in item:
                    # Bedrock/provider cache-point blocks are transport metadata
                    # inserted by aggressive_cachept(). They are not part of the
                    # user's request and must never affect intent matching.
                    continue
                else:
                    out.append(json.dumps(item, ensure_ascii=False))
            else:
                out.append(str(item))
        return "\n".join(x for x in out if x)
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text", ""))
        if "cachePoint" in content:
            return ""
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _extract_last_user_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if getattr(msg, "type", "").lower() in {"human", "user"}:
            text = _content_to_text(getattr(msg, "content", ""))
            if text.strip():
                return text.strip()
    return ""


def _extract_previous_user_text(messages: list[BaseMessage]) -> str:
    """Return the user turn immediately before the current/latest user turn."""
    seen_latest = False
    for msg in reversed(messages):
        if getattr(msg, "type", "").lower() not in {"human", "user"}:
            continue
        text = _content_to_text(getattr(msg, "content", "")).strip()
        if not text:
            continue
        if not seen_latest:
            seen_latest = True
            continue
        return text
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
    """Decode one complete top-level object; never salvage nested code fragments."""
    text = text.strip()
    if not text or len(text) > 65_536:
        return []

    def unique_keys(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj

    def reject_constant(value):
        raise ValueError("non-finite JSON constant")

    start = text.find("{")
    if start < 0 or text[:start].rstrip().endswith("["):
        return []
    try:
        obj, end = json.JSONDecoder(object_pairs_hook=unique_keys, parse_constant=reject_constant).raw_decode(text, start)
    except (ValueError, RecursionError):
        return []
    # More than one object/array after the plan is ambiguous. Do not choose one.
    suffix = text[end:].strip()
    if any(char in suffix for char in "{}[]") or not isinstance(obj, dict):
        return []
    return [obj]


def _pick_action_payload(text: str) -> Optional[dict[str, Any]]:
    candidates = _extract_json_objects(text)
    if len(candidates) != 1:
        return None
    obj = candidates[0]
    action = obj.get("action")
    if action == "tool":
        if not isinstance(obj.get("tool"), str) or not obj["tool"].strip():
            return None
        if "input" not in obj or not isinstance(obj["input"], (dict, str)):
            return None
    elif action == "final":
        if not isinstance(obj.get("final"), str) or not obj["final"].strip():
            return None
        if any(part.get("action") == "tool" for part in _extract_json_objects(obj["final"])):
            return None  # A tool directive is not a user-facing final answer.
    else:
        return None
    return obj


def _render_tool_catalog(tools: list[NormalizedTool]) -> str:
    return "\n".join(f"- {tool.name}: {tool.description}" for tool in tools)


def _planner_model(model: Any) -> Any:
    """Use a smaller completion budget for the planner/summarizer loop."""
    try:
        if getattr(model, "_llm_type", "") in {"coverity-assist", "coverity-assist-tool-enabled"}:  # PATCH-06
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


def _looks_like_local_execution_request(user_text: str) -> bool:
    """Identify execution/artifact intent before matching generic words like current."""
    t = user_text.lower()
    if re.search(r"\b(?:working directory|cwd|sys\.executable|socket\.gethostname)\b", t):
        return True
    return bool(
        re.search(r"\b(?:write|build|create|generate|run|execute|implement|test)\b", t)
        and re.search(r"\b(?:python|script|code|app|application|gui|shortcut)\b", t)
    )


def _runtime_probe_payload(user_text: str) -> Optional[dict[str, Any]]:
    """A narrow, finite local diagnostic; broader code requests go to the planner."""
    t = " ".join(user_text.lower().split()).rstrip(".!?")
    pattern = (
        r"(?:please )?(?:write and )?(?:run|execute) (?:a )?(?:small )?python script "
        r"(?:that prints|to print) (?:the )?python executable, (?:the )?python version, "
        r"(?:the )?hostname,? and (?:the )?current working directory"
    )
    if not re.fullmatch(pattern, t):
        return None
    return {
        "filename": "runtime_probe.py",
        "use_venv": False,
        "code": (
            "import os, socket, sys\n"
            "print('Python executable:', sys.executable)\n"
            "print('Python version:', sys.version)\n"
            "print('Hostname:', socket.gethostname())\n"
            "print('Working directory:', os.getcwd())\n"
        ),
    }


def _looks_like_search_retry_request(user_text: str) -> bool:
    t = " ".join(user_text.lower().split()).strip(" .!?")
    return t in {
        "try again",
        "retry",
        "retry search",
        "search again",
        "try the search again",
        "try web search again",
    }


def _looks_like_fresh_info_request(user_text: str) -> bool:
    if _looks_like_local_execution_request(user_text):
        return False
    # 'current' alone is not evidence of a request for public information.
    return bool(re.search(
        r"\b(?:who won|what happened|today|latest|news|superbowl|super bowl|score|winner)\b"
        r"|\bcurrent\s+(?:events|news|weather|prices?|president|ceo|release)\b",
        user_text, re.I,
    ))


def _looks_like_network_request(user_text: str) -> bool:
    t = user_text.lower()
    explicit = any(phrase in t for phrase in [
        "network devices", "local network", "network scan", "scan my network",
        "scan the network", "map my network", "map the network", "network map",
        "list devices on the network", "discover devices", "find devices",
        "show neighbors", "arp", "ip neigh",
    ])
    intent = ("network" in t or "lan" in t) and any(
        word in t for word in ["scan", "map", "discover", "find", "device", "host", "neighbor"]
    )
    return explicit or intent



def _is_mdns_specific(user_text: str) -> bool:
    """PATCH-02: True when user explicitly wants mDNS — route to bridge, not shell."""
    t = user_text.lower()
    return any(p in t for p in [
        "mdns", "avahi", "bonjour", ".local", "zeroconf",
        "agentpi_discover", "discover_devices",
    ])

def _extract_ipv4_address(user_text: str) -> Optional[str]:
    match = re.search(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)", user_text)
    if not match:
        return None
    candidate = match.group(0)
    try:
        if all(0 <= int(part) <= 255 for part in candidate.split(".")):
            return candidate
    except ValueError:
        return None
    return None


def _extract_requested_port(user_text: str) -> Optional[int]:
    patterns = [
        r"\bport\s*[:=#-]?\s*(\d{1,5})\b",
        r"(?<!\d):(\d{1,5})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, user_text, re.I)
        if match:
            port = int(match.group(1))
            if 1 <= port <= 65535:
                return port
    return None


def _looks_like_device_probe_request(user_text: str) -> bool:
    t = user_text.lower()
    return _extract_ipv4_address(user_text) is not None and any(
        phrase in t for phrase in [
            "probe", "check", "test", "connect", "connectivity",
            "port", "is it open", "reachable", "ping",
        ]
    )


def _looks_like_genealogy_context(user_text: str, recent_transcript: str = "") -> bool:
    corpus = (user_text + "\n" + recent_transcript).lower()
    return any(term in corpus for term in [
        "gedcom", ".ged", "genealogy", "ancestry", "family tree",
        "family branch", "lineage", "ancestor", "ancestors",
    ])


def _looks_like_genealogy_identity_request(user_text: str, recent_transcript: str = "") -> bool:
    """Require identity continuity for person-specific genealogy work and short follow-ups."""
    if not _looks_like_genealogy_context(user_text, recent_transcript):
        return False

    t = " ".join(user_text.lower().split()).strip(" .!?")
    person_terms = [
        "deep dive", "investigate", "figure out if", "who is", "who was",
        "parents", "father", "mother", "spouse", "husband", "wife",
        "children", "born", "birth", "died", "death", "same person",
        "connect", "connection", "belongs",
    ]
    if any(term in t for term in person_terms):
        return True

    if (
        re.search(r"\b(?:dig deeper|look into|research|trace|verify|resolve|identify)\b", user_text, re.I)
        and re.search(r"\b[A-Z][a-z]+(?:\s+(?:[A-Z]\.|[A-Z][A-Za-z.\-']+)){1,3}\b", user_text)
    ):
        return True

    # Follow-ups such as "do it", "go on", or "continue" inherit the genealogy
    # identity requirement from the recent transcript.
    if t in {"do it", "go on", "continue", "keep going", "proceed", "yes", "yes do it"}:
        rt = recent_transcript.lower()
        return bool(
            re.search(r"\b(?:born|birth|died|death|parents?|spouse|children|individual|record)\b", rt)
            and re.search(r"\b[A-Z][a-z]+(?:\s+[A-Z][A-Za-z.\-']+){1,3}\b", recent_transcript)
        )
    return False


def _genealogy_identity_payload(result: Any) -> dict[str, Any] | None:
    if isinstance(result, dict):
        payload = result
    else:
        text = _content_to_text(result).strip()
        start = text.find("{")
        if start < 0:
            return None
        try:
            payload = json.loads(text[start:])
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    if not isinstance(payload, dict):
        return None
    if payload.get("contract") != "agentpi-genealogy-identity-v1":
        return None
    return payload


def _render_genealogy_identity_block(payload: dict[str, Any]) -> str:
    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    target_name = str(target.get("name") or "requested person")
    status = str(payload.get("status") or "error")
    lines = [
        f"GENEALOGY_IDENTITY_CONTINUITY_{status.upper()}",
        "",
        f"Target: {target_name}",
        (
            "The GEDCOM identity check did not establish a safe one-person match. "
            "These identities must remain separate until the conflicting or missing evidence is resolved."
        ),
    ]
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        lines.extend(["", "Candidate evidence:"])
        for candidate in candidates[:5]:
            if not isinstance(candidate, dict):
                continue
            name = candidate.get("name") or candidate.get("id") or "unknown"
            years = []
            if candidate.get("birth_year") is not None:
                years.append(f"b. {candidate.get('birth_year')}")
            if candidate.get("death_year") is not None:
                years.append(f"d. {candidate.get('death_year')}")
            detail = ", ".join(years)
            line = f"- {name}"
            if detail:
                line += f" ({detail})"
            if candidate.get("id"):
                line += f" [{candidate.get('id')}]"
            lines.append(line)
            conflicts = candidate.get("conflicts")
            if isinstance(conflicts, list):
                for conflict in conflicts[:6]:
                    lines.append(f"  - conflict: {conflict}")
    lines.extend([
        "",
        "No candidate was merged into the target identity. Continue by resolving the cited conflicts, "
        "or rerun the identity check with better dates/places/source evidence.",
    ])
    return "\n".join(lines)


def _looks_like_search_diagnostic_request(user_text: str) -> bool:
    t = " ".join(user_text.lower().split())
    phrases = [
        "diagnose your search tool",
        "diagnose the search tool",
        "test your search tool",
        "test the search tool",
        "search tool diagnosis",
        "why is web search not working",
        "why isn't web search working",
        "web search not working",
        "web search is not working",
        "check your web search",
    ]
    return any(phrase in t for phrase in phrases)


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


async def _search_harder(query: str, tool: Any, chat_id: Optional[str],
                          fallback_tool: Any = None) -> str:  # PATCH-03
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
    seen: set = set()
    network_dead = False
    last_tool_text = ""

    for qx in queries:
        qx = qx.strip()
        if not qx or qx in seen:
            continue
        seen.add(qx)
        if network_dead:  # PATCH-03: skip remaining variants on dead network
            break
        try:
            result = await _invoke_tool(tool, qx, chat_id=chat_id)
        except Exception as exc:
            err = str(exc).lower()
            if any(k in err for k in ["connection", "timeout", "network", "unreachable", "refused", "name or service"]):
                network_dead = True
                logger.warning("[SEARCH] network dead, short-circuiting after 1 attempt: %s", exc)
                break
            return f"Query: {qx}\nError: {exc}"
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        last_tool_text = text
        if re.search(r'("results"\s*:\s*\[[^\]]+\]|https?://|winner|won|score|date)', text, re.I):
            return f"Query: {qx}\n{text}"

    # PATCH-03: fallback to internal_search before giving up
    if network_dead and fallback_tool is not None:
        try:
            fb = await _invoke_tool(fallback_tool, query, chat_id=chat_id)
            fb_text = fb if isinstance(fb, str) else json.dumps(fb, ensure_ascii=False, default=str)
            if fb_text.strip():
                return f"[Web search unavailable — using internal search]\n\n{fb_text}"
        except Exception as fb_e:
            logger.warning("[SEARCH] internal_search fallback failed: %s", fb_e)

    if network_dead:
        return ("Web search unavailable — this host cannot reach the internet from this network. "
                "Try internal_search or check connectivity.")

    # Preserve the last structured tool payload (including failure attempts)
    # so deterministic rendering can show real evidence instead of replacing it
    # with a generic planner-side sentence.
    if last_tool_text:
        return last_tool_text
    return "No search results found after all query variants."


async def _maybe_handle_obvious_direct_task(user_text: str, tool_map: dict[str, NormalizedTool], chat_id: Optional[str]) -> Optional[str]:
    # A Python/GUI task mentioning "current", "camera", or "working directory"
    # is not permission to send it to web search or a Linux shell template.
    if _looks_like_local_execution_request(user_text):
        return None
    if _looks_like_device_probe_request(user_text) and "agent_check_device" in tool_map:
        ip_address = _extract_ipv4_address(user_text)
        port = _extract_requested_port(user_text)
        payload = {
            "ip_address": ip_address,
            "check_type": "port" if port else "ping",
        }
        if port:
            payload["port"] = port
        logger.info("[FAST-PATH] specific device probe -> agent_check_device %s", payload)
        return await _invoke_tool(
            tool_map["agent_check_device"].raw,
            payload,
            chat_id=chat_id,
        )
    if _looks_like_repo_or_path_request(user_text) and "agent_run_shell" in tool_map:
        path = _extract_path(user_text)
        if path:
            return await _invoke_tool(tool_map["agent_run_shell"].raw, {"command": _shell_cmd_for_path(path), "cwd": "/tmp", "timeout_seconds": 180}, chat_id=chat_id)
    if _looks_like_video_request(user_text) and "agent_run_shell" in tool_map:
        return await _invoke_tool(tool_map["agent_run_shell"].raw, {"command": _shell_cmd_for_video(), "cwd": "/tmp", "timeout_seconds": 240}, chat_id=chat_id)
    if _looks_like_fresh_info_request(user_text) and "public_web_search" in tool_map:
        return await _search_harder(
            user_text, tool_map["public_web_search"].raw, chat_id,
            fallback_tool=tool_map["internal_search"].raw if "internal_search" in tool_map else None,
        )  # PATCH-03
    if _looks_like_network_request(user_text):
        # Network discovery is a first-class AgentPi capability. Prefer it on
        # every OS instead of translating the request into platform-specific
        # shell commands (nmap/ip/ipconfig/etc.).
        if "agentpi_discover_devices" in tool_map:
            logger.info("[FAST-PATH] network mapping -> AgentPi active ARP + mDNS")
            discovered = await _invoke_tool(
                tool_map["agentpi_discover_devices"].raw,
                {
                    "arp": True,
                    "mdns": True,
                    "mdns_timeout": 3.0,
                    "active": True,
                    "active_max_hosts": 768,
                },
                chat_id=chat_id,
            )
            parts = ["Active AgentPi discovery:\n" + str(discovered)]
            if "agentpi_list_devices" in tool_map:
                inventory = await _invoke_tool(
                    tool_map["agentpi_list_devices"].raw,
                    {},
                    chat_id=chat_id,
                )
                parts.append("Persisted AgentPi inventory:\n" + str(inventory))
            return "\n\n".join(parts)

        # Last resort for older deployments where the AgentPi bridge is absent.
        if "agent_run_shell" in tool_map:
            return await _invoke_tool(
                tool_map["agent_run_shell"].raw,
                {"command": _shell_cmd_for_network(), "cwd": "/tmp", "timeout_seconds": 120},
                chat_id=chat_id,
            )
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
        "1. For local/LAN network discovery or mapping, ALWAYS prefer agentpi_discover_devices and agentpi_list_devices. Do not use nmap/ip/ipconfig/arp shell commands unless the AgentPi bridge is unavailable.",
        "2. For a specific IP address, reachability check, or TCP port probe, use agent_check_device. It is cross-platform and does not require nc/netcat.",
        "3. For Python code/scripts, use agent_run_python. The backend already has a working Python interpreter; never waste steps probing python/py/python3/where or claim Python is not installed because a PATH alias failed.",
        "4. For host files, processes, VLC, capture cards, cameras, peripherals, or an explicitly requested shell command, use agent_run_shell with commands appropriate for the detected OS.",
        "5. For a literal path like /mnt/c/... inspect THAT path directly with shell tools instead of cloning anything.",
        "6. For fresh/current facts, use public_web_search. For search-tool diagnosis, use public_web_search_status before inferring a host or gateway outage.",
        "7. Use the recent transcript for follow-ups like 'do it again'.",
        "8. If a tool is needed, respond with one complete JSON object ONLY. A printed tool directive is not execution.",
        "9. Build large artifacts in small verified chunks. Do not put an entire GUI into one tool call; inspect actual API schemas first, then write, parse/compile, and smoke-test files separately.",
        "10. Do not run a persistent GUI mainloop in a bounded Python execution call. Preparing an app, testing it, creating a shortcut, and launching it are distinct operations.",
        "11. For person-specific genealogy/GEDCOM work, call agent_genealogy_identity_check before identifying a same/similar-name record as the target. Only status=match permits identity continuity. Treat ambiguous/conflict/not_found as separate identities and do not merge them.",
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
        f"Tool output:\n{result_text[:SUMMARIZER_LIMIT]}"
    )
    logger.info("Planner summary prompt chars=%d", len(prompt))
    response = await model.ainvoke([HumanMessage(content=prompt)], config=config)
    return _content_to_text(getattr(response, "content", response)).strip()


async def run_coverity_tool_loop(model: Any = None, tools: Optional[list[Any]] = None, messages: Optional[list[BaseMessage]] = None, config: Any = None, max_steps: Optional[int] = None, **kwargs: Any) -> AIMessage:
    if model is not None and isinstance(model, list) and tools is None and messages is None:
        tools = model
        model = None
    model = model or kwargs.get("model_with_tools") or kwargs.get("llm")
    tools = tools or kwargs.get("available_tools") or []
    messages = messages or kwargs.get("state_messages") or []

    normalized_tools = _normalize_tools(tools)
    tool_map = {tool.name: tool for tool in normalized_tools}

    user_text = _extract_last_user_text(messages)
    recent_transcript = _render_recent_transcript(messages, limit=10)
    system_text = _extract_system_text(messages)
    chat_id = _extract_chat_id(config)
    genealogy_identity_required = _looks_like_genealogy_identity_request(
        user_text,
        recent_transcript,
    )

    if (
        _looks_like_search_diagnostic_request(user_text)
        and "public_web_search_status" in tool_map
    ):
        logger.info("LOCAL_ROUTE intent=search_diagnostic tool=public_web_search_status")
        try:
            result = await _invoke_tool(
                tool_map["public_web_search_status"].raw,
                {"probe": False},
                chat_id=chat_id,
            )
        except Exception as exc:
            return AIMessage(
                content=(
                    "Public web search diagnostic raised "
                    f"{type(exc).__name__}; check the backend search log."
                )
            )
        return AIMessage(
            content=(
                "Public web search diagnostics (actual runtime output):\n\n"
                + _content_to_text(result)
            )
        )

    search_query = None
    if _looks_like_fresh_info_request(user_text):
        search_query = user_text
    elif _looks_like_search_retry_request(user_text):
        previous_user_text = _extract_previous_user_text(messages)
        if _looks_like_fresh_info_request(previous_user_text):
            search_query = previous_user_text

    if search_query and "public_web_search" in tool_map:
        logger.info("LOCAL_ROUTE intent=public_web_search query_chars=%d", len(search_query))
        result = await _search_harder(
            search_query,
            tool_map["public_web_search"].raw,
            chat_id,
            fallback_tool=(
                tool_map["internal_search"].raw
                if "internal_search" in tool_map
                else None
            ),
        )
        return AIMessage(
            content=render_public_search_output(
                result,
                requested_query=search_query,
            )
        )

    probe = _runtime_probe_payload(user_text)
    if probe is not None:
        # Already-defined finite diagnostic: no web, AgentPi HTTP request, or
        # summarizer is necessary. Report the real local executor result.
        if not chat_id:
            return AIMessage(content="LOCAL_EXECUTION_BLOCKED: current chat/workspace identity is missing. No script was run.")
        if "agent_run_python" not in tool_map:
            return AIMessage(content="LOCAL_EXECUTION_BLOCKED: agent_run_python is not bound to this conversation. No script was run.")
        probe["chat_id"] = chat_id
        logger.info("LOCAL_ROUTE intent=runtime_probe tool=agent_run_python")
        try:
            result = await _invoke_tool(tool_map["agent_run_python"].raw, probe, chat_id=chat_id)
        except Exception as exc:
            return AIMessage(content=f"agent_run_python raised {type(exc).__name__}. No execution output was returned; check the backend tool-dispatch log.")
        return AIMessage(content="Local agent_run_python result (actual executor output):\n\n" + _content_to_text(result))

    model = model or get_model()
    planner_model = _planner_model(model)
    direct_tool_result = await _maybe_handle_obvious_direct_task(user_text, tool_map, chat_id)
    if direct_tool_result is not None:
        final_text = await _summarize_tool_result(model, user_text, str(direct_tool_result), config=config)
        return AIMessage(content=final_text)

    planner_steps = max_steps or int(os.getenv("COVERITY_ASSIST_TOOL_MAX_STEPS", "6"))
    scratchpad: list[str] = []
    last_text = ""
    protocol_failures = 0
    returned_tools: list[str] = []
    genealogy_identity_checked = False

    for _ in range(planner_steps):
        planner_prompt = _build_planner_prompt(user_text, recent_transcript, system_text, normalized_tools, scratchpad, chat_id)
        logger.info("Planner loop prompt chars=%d, steps=%d", len(planner_prompt), planner_steps)
        response = await planner_model.ainvoke([HumanMessage(content=planner_prompt)], config=config)
        last_text = _content_to_text(getattr(response, "content", response)).strip()

        payload = _pick_action_payload(last_text)
        if not payload:
            protocol_failures += 1
            logger.warning("PLANNER_PROTOCOL_REJECTED attempt=%d response_chars=%d", protocol_failures, len(last_text))
            if protocol_failures >= 2:
                returned = ", ".join(returned_tools) or "none"
                return AIMessage(content=(
                    "PLANNER_PROTOCOL_INVALID: the planner did not return a complete, valid action after two attempts. "
                    "The rejected directives were not executed. Tools that previously returned in this turn: "
                    + returned + ". No artifact or shortcut completion is inferred."
                ))
            scratchpad.append(
                "PROTOCOL ERROR: previous response was not dispatched. Return exactly one complete JSON tool/final object. "
                "Use small code chunks, not a whole application. Do not repeat previously completed actions."
            )
            continue
        action = str(payload.get("action", "")).lower().strip()
        if action == "final":
            if genealogy_identity_required and not genealogy_identity_checked:
                if "agent_genealogy_identity_check" not in tool_map:
                    return AIMessage(content=(
                        "GENEALOGY_IDENTITY_CHECK_REQUIRED: person-specific genealogy conclusions are blocked "
                        "because agent_genealogy_identity_check is not bound to this conversation. "
                        "No same/similar-name record was merged into the target identity."
                    ))
                scratchpad.append(
                    "IDENTITY CONTINUITY GATE: before a final genealogy conclusion, call "
                    "agent_genealogy_identity_check for the person under research. Include known birth/death "
                    "years when available. Only status=match permits identity continuity."
                )
                continue
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
            returned_tools.append(selected.name)
        except Exception as exc:
            result = f"Tool {selected.name} failed: {exc}"

        if selected.name == "agent_genealogy_identity_check":
            identity_payload = _genealogy_identity_payload(result)
            if identity_payload is None:
                return AIMessage(content=(
                    "GENEALOGY_IDENTITY_CHECK_INVALID: the identity tool did not return its expected "
                    "agentpi-genealogy-identity-v1 contract. No genealogy identity conclusion is permitted."
                ))
            genealogy_identity_checked = True
            identity_status = str(identity_payload.get("status") or "error")
            if identity_status != "match":
                return AIMessage(content=_render_genealogy_identity_block(identity_payload))

        if not isinstance(result, str):
            try:
                result = json.dumps(result, ensure_ascii=False, default=str)
            except Exception:
                result = str(result)
        # PATCH-05: truncation-aware append
        _ol = len(result)
        _b  = result[:SCRATCHPAD_LIMIT]
        _mk = (f"\n[TRUNCATED: showed {SCRATCHPAD_LIMIT:,} of {_ol:,} chars — use a narrower query for more.]"
               if _ol > SCRATCHPAD_LIMIT else "")
        if _mk:
            logger.warning("[SCRATCHPAD] tool=%s truncated %d->%d chars", selected.name, _ol, SCRATCHPAD_LIMIT)
        scratchpad.append(f"Tool used: {selected.name}\nInput: {tool_input}\nResult: {_b}{_mk}")

    if genealogy_identity_required and not genealogy_identity_checked:
        return AIMessage(content=(
            "GENEALOGY_IDENTITY_CHECK_REQUIRED: the planning budget ended before a deterministic GEDCOM "
            "identity check completed. No same/similar-name person was merged into the target identity."
        ))
    if protocol_failures and not returned_tools:
        return AIMessage(content="PLANNER_PROTOCOL_INVALID: no tool execution result was obtained before the planning budget ended. No completion is claimed.")
    if scratchpad:
        grounded = await _summarize_tool_result(model, user_text, "\n\n".join(scratchpad), config=config)
        return AIMessage(content=grounded)
    return AIMessage(content=last_text or "I couldn't complete the tool workflow.")
