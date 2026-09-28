from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import ssl
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

import httpx
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from typing_extensions import Annotated

from app.analytics.service import save_web_search
from app.agent_mode.thought_interceptor import interceptor
from app.config import get_settings
from app.tools.query_sanitizer import sanitize_query, should_block_query

logger = logging.getLogger(__name__)
settings = get_settings()
_LOADED_SEARCH_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_SEARCH_CONTRACT = "agentpi-public-search-v2"

_DDG_BACKENDS = (
    ("ddg-html", "https://html.duckduckgo.com/html/"),
    ("ddg-lite", "https://lite.duckduckgo.com/lite/"),
)
_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AgentPi/1.0; +local-public-search)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.8",
}


class _DuckDuckGoParser(HTMLParser):
    """Extract title/link/snippet tuples from DDG HTML and Lite pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.snippets: list[str] = []
        self._capture: str | None = None
        self._capture_tag: str | None = None
        self._href = ""
        self._parts: list[str] = []

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        values = dict(attrs).get("class") or ""
        return {part.strip() for part in values.split() if part.strip()}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = self._classes(attrs)
        attrs_dict = dict(attrs)
        if (
            tag == "a"
            and self._capture is None
            and ("result__a" in classes or "result-link" in classes)
        ):
            self._capture = "title"
            self._capture_tag = tag
            self._href = attrs_dict.get("href") or ""
            self._parts = []
            return

        if (
            self._capture is None
            and ("result__snippet" in classes or "result-snippet" in classes)
        ):
            self._capture = "snippet"
            self._capture_tag = tag
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture is None or tag != self._capture_tag:
            return
        text = " ".join("".join(self._parts).split())
        if self._capture == "title" and self._href and text:
            self.links.append((self._href, text))
        elif self._capture == "snippet" and text:
            self.snippets.append(text)
        self._capture = None
        self._capture_tag = None
        self._href = ""
        self._parts = []


def _normalize_result_url(href: str) -> str:
    value = html.unescape((href or "").strip())
    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = urljoin("https://duckduckgo.com", value)

    try:
        parsed = urlparse(value)
        params = parse_qs(parsed.query)
        if params.get("uddg"):
            return unquote(params["uddg"][0])
    except Exception:
        pass
    return value


def _parse_duckduckgo_results(page: str, max_results: int) -> list[dict[str, str]]:
    parser = _DuckDuckGoParser()
    parser.feed(page)

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, (href, title) in enumerate(parser.links):
        url = _normalize_result_url(href)
        if not url or url in seen:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        seen.add(url)
        snippet = parser.snippets[index] if index < len(parser.snippets) else ""
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
            }
        )
        if len(results) >= max_results:
            break
    return results


def _configured_search_mode() -> str:
    return str(getattr(settings, "PUBLIC_WEB_SEARCH_MODE", "auto")).strip().lower()


def _effective_search_mode() -> str:
    mode = _configured_search_mode()
    if mode in {"direct", "gateway"}:
        return mode
    return "direct" if bool(getattr(settings, "LOCAL", False)) else "gateway"


def search_runtime_status() -> dict[str, Any]:
    gateway = str(getattr(settings, "COVERITY_GATEWAY_URL", "") or "").rstrip("/")
    return {
        "status": "configured",
        "contract": _SEARCH_CONTRACT,
        "loaded_search_source_sha256": _LOADED_SEARCH_SOURCE_SHA256,
        "configured_mode": _configured_search_mode(),
        "effective_mode": _effective_search_mode(),
        "local_runtime": bool(getattr(settings, "LOCAL", False)),
        "direct_backends": [name for name, _ in _DDG_BACKENDS],
        "tls_preference": (
            "windows-cryptoapi-truststore"
            if sys.platform == "win32"
            else "python-default-openssl"
        ),
        "gateway_url": gateway,
        "note": (
            "Local installs use direct DuckDuckGo HTML/Lite search in auto mode."
            if _effective_search_mode() == "direct"
            else "Gateway mode posts to COVERITY_GATEWAY_URL/web-search."
        ),
    }


def _build_direct_ssl_context():
    """Build a verified TLS context appropriate for the local host.

    On Windows prefer truststore/Windows CryptoAPI so enterprise-managed root
    certificates use the same native trust policy as other Windows software.
    Certificate verification and hostname verification remain enabled.
    """
    if sys.platform == "win32":
        try:
            import truststore

            context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            return context, "windows-cryptoapi-truststore"
        except Exception as exc:
            logger.warning(
                "Windows truststore TLS context unavailable; falling back to "
                "Python default verification: %s",
                type(exc).__name__,
            )

    context = ssl.create_default_context()
    return context, "python-default-openssl"


def _fetch_direct_page(url: str, query: str, region: str, timeout: float) -> tuple[str, str]:
    """Fetch through urllib with a verified native/system TLS context."""
    target = f"{url}?{urlencode({'q': query, 'kl': region})}"
    request = Request(target, headers=_DEFAULT_HEADERS, method="GET")
    context, tls_backend = _build_direct_ssl_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        # Search result pages should be small; bound the read to avoid accidental
        # unbounded downloads from a changed or intercepted endpoint.
        body = response.read(2_000_000)
    return body.decode(charset, errors="replace"), tls_backend


async def _direct_search(query: str, max_results: int) -> dict[str, Any]:
    timeout = float(getattr(settings, "PUBLIC_WEB_SEARCH_TIMEOUT_SECONDS", 20.0))
    region = str(getattr(settings, "PUBLIC_WEB_SEARCH_REGION", "us-en"))
    attempts: list[dict[str, str]] = []

    for source, url in _DDG_BACKENDS:
        try:
            page, tls_backend = await asyncio.to_thread(
                _fetch_direct_page,
                url,
                query,
                region,
                timeout,
            )
            results = _parse_duckduckgo_results(page, max_results)
            attempts.append(
                {
                    "backend": source,
                    "status": "ok" if results else "empty",
                    "tls_backend": tls_backend,
                }
            )
            if results:
                return {
                    "query": query,
                    "results": results,
                    "source": source,
                    "backend": "direct",
                    "tls_backend": tls_backend,
                    "attempts": attempts,
                }
        except Exception as exc:
            attempts.append(
                {
                    "backend": source,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:240],
                }
            )

    return {
        "error": "Search failed",
        "message": "Direct public search returned no usable results.",
        "query": query,
        "backend": "direct",
        "attempts": attempts,
    }


async def _gateway_search(query: str, max_results: int) -> dict[str, Any]:
    timeout = float(getattr(settings, "PUBLIC_WEB_SEARCH_TIMEOUT_SECONDS", 20.0))
    gateway = str(getattr(settings, "COVERITY_GATEWAY_URL", "") or "").rstrip("/")
    if not gateway:
        return {
            "error": "Search failed",
            "message": "Gateway mode selected but COVERITY_GATEWAY_URL is empty.",
            "query": query,
            "backend": "gateway",
        }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{gateway}/web-search",
                json={"query": query, "max_results": max_results},
            )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
            payload = payload["response"]
        if not isinstance(payload, dict):
            raise ValueError("Gateway returned a non-object JSON payload")
        payload.setdefault("query", query)
        payload.setdefault("backend", "gateway")
        payload.setdefault("source", "coverity-gateway")
        return payload
    except Exception as exc:
        return {
            "error": "Search failed",
            "message": str(exc),
            "error_type": type(exc).__name__,
            "query": query,
            "backend": "gateway",
            "gateway_url": gateway,
        }


async def _perform_search(query: str, max_results: int) -> dict[str, Any]:
    if _effective_search_mode() == "direct":
        return await _direct_search(query, max_results)
    return await _gateway_search(query, max_results)


async def probe_public_search() -> dict[str, Any]:
    """Perform repeated non-sensitive runtime searches to test more than one request."""
    status = search_runtime_status()
    checks = []
    for query in ("OpenAI", "Python documentation"):
        result = await _perform_search(query, 1)
        check = {
            "query": query,
            "ok": bool(result.get("results")),
            "backend": result.get("backend"),
            "source": result.get("source"),
            "result_count": len(result.get("results") or []),
        }
        if not check["ok"]:
            check["error"] = result.get("message") or result.get("error")
            check["attempts"] = result.get("attempts", [])
        checks.append(check)

    status["probes"] = checks
    status["probe"] = checks[0]  # Backward-compatible summary.
    status["status"] = "healthy" if all(item["ok"] for item in checks) else "unhealthy"
    return status


@tool("public_web_search_status")
async def public_web_search_status(probe: bool = True) -> str:
    """Diagnose the configured public web-search backend.

    With probe=True, performs a generic non-sensitive one-result search and
    reports the actual backend/source used. No user query is sent.
    """
    data = await probe_public_search() if probe else search_runtime_status()
    return json.dumps(data, indent=2)


@tool("public_web_search")
async def public_web_search(
    query: str,
    max_results: int = 6,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Perform a privacy-conscious public internet search.

    Local AgentPi/DishChat installs search directly through DuckDuckGo's
    non-JavaScript HTML/Lite surfaces. Server deployments may select the legacy
    Coverity gateway explicitly.

    Never include proprietary company information, internal system names,
    employee data, credentials, or private IP addresses in a public query.
    """
    max_results = max(1, min(int(max_results), 10))
    interceptor.tool_call(
        "public_web_search",
        params={"query": query[:100], "max_results": max_results},
    )
    interceptor.thought(f"Searching web for: {query[:50]}", "tool")

    chat_id = None
    if config and "configurable" in config:
        chat_id = config["configurable"].get("thread_id")

    should_block, block_reason = should_block_query(query)
    if should_block:
        logger.error("Blocked sensitive public-search query: %s", block_reason)
        return json.dumps(
            {
                "error": "Query blocked for security reasons",
                "reason": block_reason,
                "suggestion": (
                    "Rephrase using generic public terms or use internal_search "
                    "for company/private information."
                ),
            },
            indent=2,
        )

    sanitized_query, was_modified, violations = sanitize_query(query)
    if was_modified:
        logger.warning(
            "Potentially sensitive public-search query in chat %s; violations=%s",
            chat_id,
            violations,
        )

    logger.info(
        "PUBLIC_WEB_SEARCH backend=%s query_chars=%d chat_present=%s",
        _effective_search_mode(),
        len(sanitized_query),
        bool(chat_id),
    )

    data = await _perform_search(sanitized_query, max_results)

    if data.get("results"):
        try:
            await save_web_search(chat_id, query, data)
        except Exception as exc:
            logger.warning("Failed to log web search analytics: %s", exc)
        interceptor.tool_call(
            "public_web_search",
            result=(
                f"Found {len(data.get('results') or [])} results "
                f"via {data.get('source') or data.get('backend')}"
            ),
        )
    else:
        logger.warning(
            "PUBLIC_WEB_SEARCH_FAILED backend=%s detail=%s",
            data.get("backend"),
            data.get("message") or data.get("error"),
        )

    return json.dumps(data, indent=2)
