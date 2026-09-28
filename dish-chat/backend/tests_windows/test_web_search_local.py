from __future__ import annotations

import asyncio
import json

import pytest

from app.tools import web_search


_HTML_RESULT = """
<html><body>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Falpha">
    Example <b>Alpha</b>
  </a>
  <a class="result__snippet">A useful alpha snippet.</a>
</div>
</body></html>
"""

_LITE_RESULT = """
<html><body>
<table>
<tr><td><a class="result-link" href="https://example.org/beta">Example Beta</a></td></tr>
<tr><td class="result-snippet">A useful beta snippet.</td></tr>
</table>
</body></html>
"""


@pytest.fixture(autouse=True)
def _reset_search_state(monkeypatch):
    with web_search._SEARCH_CACHE_LOCK:
        web_search._SEARCH_CACHE.clear()
    web_search._LAST_DIRECT_FETCH_MONOTONIC = 0.0
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_CACHE_TTL_SECONDS", 120.0)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_CACHE_MAX_ENTRIES", 64)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_EMPTY_RETRY_SECONDS", 0.0)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_EMPTY_RETRIES", 1)


def test_duckduckgo_html_parser_decodes_redirect_and_snippet():
    results = web_search._parse_duckduckgo_results(_HTML_RESULT, 6)
    assert results == [{
        "title": "Example Alpha",
        "url": "https://example.com/alpha",
        "snippet": "A useful alpha snippet.",
    }]


def test_duckduckgo_lite_parser():
    results = web_search._parse_duckduckgo_results(_LITE_RESULT, 6)
    assert results == [{
        "title": "Example Beta",
        "url": "https://example.org/beta",
        "snippet": "A useful beta snippet.",
    }]


def test_local_auto_mode_selects_direct(monkeypatch):
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_MODE", "auto")
    monkeypatch.setattr(web_search.settings, "LOCAL", True)
    status = web_search.search_runtime_status()
    assert status["configured_mode"] == "auto"
    assert status["effective_mode"] == "direct"
    assert status["direct_backends"] == ["ddg-html", "ddg-lite"]


def test_direct_search_falls_back_from_html_to_lite(monkeypatch):
    pages = iter(["<html><body>No results fixture</body></html>", _LITE_RESULT])
    calls = []

    def fake_fetch(url, query, region, timeout):
        calls.append((url, query, region, timeout))
        return next(pages), "fixture-tls"

    monkeypatch.setattr(web_search, "_fetch_direct_page", fake_fetch)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_REGION", "us-en")

    data = asyncio.run(web_search._direct_search("fixture query", 3))

    assert data["backend"] == "direct"
    assert data["source"] == "ddg-lite"
    assert data["results"][0]["url"] == "https://example.org/beta"
    assert data["tls_backend"] == "fixture-tls"
    assert data["cache"]["hit"] is False
    assert data["attempts"] == [
        {"backend": "ddg-html", "round": 1, "status": "empty", "tls_backend": "fixture-tls"},
        {"backend": "ddg-lite", "round": 1, "status": "ok", "tls_backend": "fixture-tls"},
    ]
    assert [call[1] for call in calls] == ["fixture query", "fixture query"]
    assert [call[2] for call in calls] == ["us-en", "us-en"]


def test_search_probe_reports_repeated_direct_backend(monkeypatch):
    calls = []

    async def fake_perform(query, max_results):
        calls.append((query, max_results))
        return {
            "query": query,
            "backend": "direct",
            "source": "ddg-html" if query == "OpenAI" else "ddg-lite",
            "tls_backend": "fixture-tls",
            "results": [{"title": query, "url": "https://example.com", "snippet": "fixture"}],
        }

    monkeypatch.setattr(web_search, "_perform_search", fake_perform)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_MODE", "direct")
    report = asyncio.run(web_search.probe_public_search())
    assert report["status"] == "healthy"
    assert report["effective_mode"] == "direct"
    assert calls == [("OpenAI", 1), ("Python documentation", 1)]
    assert [item["source"] for item in report["probes"]] == ["ddg-html", "ddg-lite"]
    assert [item["tls_backend"] for item in report["probes"]] == ["fixture-tls", "fixture-tls"]
    assert all(item["ok"] for item in report["probes"])
    assert report["probe"] == report["probes"][0]


def test_sensitive_private_ip_never_reaches_public_backend(monkeypatch):
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("public backend should not be called")

    monkeypatch.setattr(web_search, "_perform_search", forbidden)
    result = asyncio.run(web_search.public_web_search.coroutine(
        query="search 192.168.0.25 admin password",
        max_results=2,
        config={"configurable": {"thread_id": "test"}},
    ))
    payload = json.loads(result)
    assert payload["error"] == "Query blocked for security reasons"
    assert calls == []


def test_direct_fetch_builds_bounded_duckduckgo_request(monkeypatch):
    observed = {}

    class Headers:
        def get_content_charset(self):
            return "utf-8"

    class Response:
        headers = Headers()
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self, limit):
            observed["limit"] = limit
            return _HTML_RESULT.encode("utf-8")

    fixture_context = object()

    def fake_context():
        return fixture_context, "fixture-trust"

    def fake_urlopen(request, timeout, context):
        observed["url"] = request.full_url
        observed["timeout"] = timeout
        observed["ua"] = request.headers.get("User-agent")
        observed["context"] = context
        return Response()

    monkeypatch.setattr(web_search, "_build_direct_ssl_context", fake_context)
    monkeypatch.setattr(web_search, "urlopen", fake_urlopen)
    page, tls_backend = web_search._fetch_direct_page(
        "https://html.duckduckgo.com/html/",
        "hello world",
        "us-en",
        7.0,
    )
    assert page == _HTML_RESULT
    assert tls_backend == "fixture-trust"
    assert observed["context"] is fixture_context
    assert "q=hello+world" in observed["url"]
    assert "kl=us-en" in observed["url"]
    assert observed["timeout"] == 7.0
    assert observed["limit"] == 2_000_000
    assert "AgentPi" in observed["ua"]


def test_search_probe_is_unhealthy_when_second_request_fails(monkeypatch):
    calls = 0

    async def fake_perform(query, max_results):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "query": query,
                "backend": "direct",
                "source": "ddg-html",
                "results": [{"title": query, "url": "https://example.com", "snippet": "fixture"}],
            }
        return {
            "error": "Search failed",
            "message": "fixture second-request failure",
            "query": query,
            "backend": "direct",
            "attempts": [
                {"backend": "ddg-html", "status": "error", "error_type": "URLError"},
                {"backend": "ddg-lite", "status": "error", "error_type": "URLError"},
            ],
        }

    monkeypatch.setattr(web_search, "_perform_search", fake_perform)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_MODE", "direct")
    report = asyncio.run(web_search.probe_public_search())
    assert report["status"] == "unhealthy"
    assert report["probes"][0]["ok"] is True
    assert report["probes"][1]["ok"] is False
    assert report["probes"][1]["error"] == "fixture second-request failure"


def test_windows_tls_context_prefers_truststore(monkeypatch):
    import types

    created = []
    fixture_context = object()

    def fake_ssl_context(protocol):
        created.append(protocol)
        return fixture_context

    fake_truststore = types.SimpleNamespace(SSLContext=fake_ssl_context)
    monkeypatch.setitem(__import__("sys").modules, "truststore", fake_truststore)
    monkeypatch.setattr(web_search.sys, "platform", "win32")

    context, backend = web_search._build_direct_ssl_context()

    assert context is fixture_context
    assert backend == "windows-cryptoapi-truststore"
    assert created == [web_search.ssl.PROTOCOL_TLS_CLIENT]


def test_successful_search_is_cached_and_second_call_avoids_fetch(monkeypatch):
    calls = []

    def fake_fetch(url, query, region, timeout):
        calls.append((url, query))
        return _HTML_RESULT, "fixture-tls"

    monkeypatch.setattr(web_search, "_fetch_direct_page", fake_fetch)

    first = asyncio.run(web_search._direct_search("cached fixture", 3))
    second = asyncio.run(web_search._direct_search("cached fixture", 3))

    assert first["cache"]["hit"] is False
    assert second["cache"]["hit"] is True
    assert second["results"] == first["results"]
    assert len(calls) == 1


def test_empty_results_retry_once_then_succeed(monkeypatch):
    pages = iter([
        "<html><body>empty html</body></html>",
        "<html><body>empty lite</body></html>",
        _HTML_RESULT,
    ])
    calls = []

    def fake_fetch(url, query, region, timeout):
        calls.append(url)
        return next(pages), "fixture-tls"

    monkeypatch.setattr(web_search, "_fetch_direct_page", fake_fetch)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_EMPTY_RETRIES", 1)

    data = asyncio.run(web_search._direct_search("retry fixture", 2))

    assert data["results"][0]["url"] == "https://example.com/alpha"
    assert len(calls) == 3
    assert [(a["round"], a["status"]) for a in data["attempts"]] == [
        (1, "empty"),
        (1, "empty"),
        (2, "ok"),
    ]


def test_search_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_CACHE_MAX_ENTRIES", 2)

    for index in range(3):
        web_search._cache_put(
            f"query {index}",
            1,
            "us-en",
            {
                "query": f"query {index}",
                "backend": "direct",
                "source": "fixture",
                "results": [{"title": str(index), "url": f"https://example.com/{index}", "snippet": ""}],
            },
        )

    snapshot = web_search._cache_snapshot()
    assert snapshot["entries"] == 2
    assert snapshot["max_entries"] == 2
    assert web_search._cache_get("query 0", 1, "us-en") is None
    assert web_search._cache_get("query 2", 1, "us-en")["cache"]["hit"] is True
