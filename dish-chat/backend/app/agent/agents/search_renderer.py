from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlparse


def _markdown_escape(value: Any) -> str:
    text = " ".join(str(value or "").split())
    for char in ("\\", "[", "]", "*", "_", "`", "<", ">", "#"):
        text = text.replace(char, "\\" + char)
    return text


def _safe_public_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    # Encode Markdown-delimiter characters in the destination while retaining
    # ordinary URL syntax.
    return quote(url, safe=":/?#@!$&'*+,;=%._~-")


def _render_attempts(attempts: Any) -> str | None:
    if not isinstance(attempts, list) or not attempts:
        return None
    rendered: list[str] = []
    for attempt in attempts[:8]:
        if not isinstance(attempt, dict):
            continue
        backend = _markdown_escape(attempt.get("backend") or "unknown")
        status = _markdown_escape(attempt.get("status") or "unknown")
        round_no = attempt.get("round")
        prefix = f"{backend} r{round_no}" if round_no is not None else backend
        rendered.append(f"{prefix}: {status}")
    return " → ".join(rendered) if rendered else None


def render_public_search_payload(payload: dict[str, Any], requested_query: str = "") -> str:
    """Render verified search JSON as deterministic Markdown without an LLM pass."""
    query = _markdown_escape(payload.get("query") or requested_query or "(unspecified)")
    results = payload.get("results")
    results = results if isinstance(results, list) else []

    lines: list[str] = []
    if results:
        lines.extend(["## Web search results", "", f"**Query:** {query}", ""])
        rendered_count = 0
        for item in results[:10]:
            if not isinstance(item, dict):
                continue
            title = _markdown_escape(item.get("title") or "Untitled result")
            snippet = _markdown_escape(item.get("snippet") or "")
            url = _safe_public_url(item.get("url"))
            rendered_count += 1
            if url:
                lines.append(f"### {rendered_count}. [{title}]({url})")
            else:
                lines.append(f"### {rendered_count}. {title}")
            if snippet:
                lines.append(snippet)
            lines.append("")
        if rendered_count == 0:
            lines.extend(["No renderable result records were returned.", ""])
    else:
        lines.extend([
            "## Web search unavailable",
            "",
            f"**Query:** {query}",
            "",
            _markdown_escape(
                payload.get("message")
                or payload.get("error")
                or "No usable search results were returned."
            ),
            "",
        ])

    cache = payload.get("cache") if isinstance(payload.get("cache"), dict) else {}
    cache_text = "hit" if cache.get("hit") else "miss"
    backend = _markdown_escape(payload.get("backend") or "unknown")
    source = _markdown_escape(payload.get("source") or "none")
    tls_backend = _markdown_escape(payload.get("tls_backend") or "unknown")
    attempts = _render_attempts(payload.get("attempts"))

    lines.extend([
        "---",
        f"**Search evidence:** backend=`{backend}` · source=`{source}` · "
        f"TLS=`{tls_backend}` · cache=`{cache_text}` · results=`{len(results)}`",
    ])
    if cache.get("hit") and cache.get("age_seconds") is not None:
        lines.append(
            f"**Cache age:** `{_markdown_escape(cache.get('age_seconds'))}s` "
            f"(TTL `{_markdown_escape(cache.get('ttl_seconds'))}s`)"
        )
    if attempts:
        lines.append(f"**Provider attempts:** {attempts}")
    lines.append("")
    lines.append("_Rendered deterministically from the actual search-tool payload; no LLM summarization was used._")
    return "\n".join(lines)


def render_public_search_output(raw: Any, requested_query: str = "") -> str:
    """Parse a tool result and render it, failing closed if the payload is malformed."""
    if isinstance(raw, dict):
        return render_public_search_payload(raw, requested_query=requested_query)

    text = str(raw or "").strip()
    start = text.find("{")
    if start >= 0:
        try:
            payload = json.loads(text[start:])
        except (json.JSONDecodeError, TypeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            return render_public_search_payload(payload, requested_query=requested_query)

    return "\n".join([
        "## Web search output could not be rendered safely",
        "",
        f"**Query:** {_markdown_escape(requested_query or '(unspecified)')}",
        "",
        "The search tool returned a non-JSON or malformed payload. No result links are inferred.",
        "",
        "---",
        "_No LLM summarization was used._",
    ])
