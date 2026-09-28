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


class _Response:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    pages = []

    def __init__(self, *args, **kwargs):
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None):
        self.requests.append((url, params))
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return _Response(page)


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
    monkeypatch.setattr(web_search.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(web_search.settings, "PUBLIC_WEB_SEARCH_REGION", "us-en")
    _Client.pages = ["<html><body>No results fixture</body></html>", _LITE_RESULT]

    data = asyncio.run(web_search._direct_search("fixture query", 3))

    assert data["backend"] == "direct"
    assert data["source"] == "ddg-lite"
    assert data["results"][0]["url"] == "https://example.org/beta"
    assert data["attempts"] == [
        {"backend": "ddg-html", "status": "empty"},
        {"backend": "ddg-lite", "status": "ok"},
    ]


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
