from __future__ import annotations

import asyncio
import json

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
        return next(pages)

    monkeypatch.setattr(web_search, "_fetch_direct_page", fake_fetch)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_REGION", "us-en")

    data = asyncio.run(web_search._direct_search("fixture query", 3))

    assert data["backend"] == "direct"
    assert data["source"] == "ddg-lite"
    assert data["results"][0]["url"] == "https://example.org/beta"
    assert data["attempts"] == [
        {"backend": "ddg-html", "status": "empty"},
        {"backend": "ddg-lite", "status": "ok"},
    ]
    assert [call[1] for call in calls] == ["fixture query", "fixture query"]
    assert [call[2] for call in calls] == ["us-en", "us-en"]


def test_search_probe_reports_actual_direct_backend(monkeypatch):
    async def fake_perform(query, max_results):
        assert query == "OpenAI"
        assert max_results == 1
        return {
            "query": query,
            "backend": "direct",
            "source": "ddg-html",
            "results": [{"title": "OpenAI", "url": "https://openai.com", "snippet": "fixture"}],
        }

    monkeypatch.setattr(web_search, "_perform_search", fake_perform)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_MODE", "direct")
    report = asyncio.run(web_search.probe_public_search())
    assert report["status"] == "healthy"
    assert report["effective_mode"] == "direct"
    assert report["probe"] == {
        "ok": True,
        "backend": "direct",
        "source": "ddg-html",
        "result_count": 1,
    }


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

    def fake_urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["timeout"] = timeout
        observed["ua"] = request.headers.get("User-agent")
        return Response()

    monkeypatch.setattr(web_search, "urlopen", fake_urlopen)
    page = web_search._fetch_direct_page(
        "https://html.duckduckgo.com/html/",
        "hello world",
        "us-en",
        7.0,
    )
    assert page == _HTML_RESULT
    assert "q=hello+world" in observed["url"]
    assert "kl=us-en" in observed["url"]
    assert observed["timeout"] == 7.0
    assert observed["limit"] == 2_000_000
    assert "AgentPi" in observed["ua"]
