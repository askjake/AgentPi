from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SEARCH_SOURCE = ROOT / "dish-chat" / "backend" / "app" / "tools" / "web_search.py"
URL = "http://127.0.0.1:8000/rest/api/v1/health/search?probe=true"


def fetch_probe(label: str) -> dict:
    try:
        with urllib.request.urlopen(URL, timeout=70) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"LIVE_WEB_SEARCH_PROBE_FAILED {label} transport={type(exc).__name__}: {exc}")
        raise SystemExit(1)
    return payload


def safe_view(payload: dict, expected_sha: str) -> dict:
    loaded_sha = payload.get("loaded_search_source_sha256")
    probes = payload.get("probes") or [payload.get("probe") or {}]
    return {
        "status": payload.get("status"),
        "contract": payload.get("contract"),
        "configured_mode": payload.get("configured_mode"),
        "effective_mode": payload.get("effective_mode"),
        "direct_backends": payload.get("direct_backends"),
        "tls_preference": payload.get("tls_preference"),
        "cache": payload.get("cache"),
        "pacing": payload.get("pacing"),
        "loaded_search_source_sha256": loaded_sha,
        "expected_search_source_sha256": expected_sha,
        "source_identity_matches": loaded_sha == expected_sha,
        "probes": probes,
    }


def validate(payload: dict, expected_sha: str, label: str) -> list[dict]:
    loaded_sha = payload.get("loaded_search_source_sha256")
    probes = payload.get("probes") or [payload.get("probe") or {}]

    if payload.get("contract") != "agentpi-public-search-v2":
        print(f"LIVE_WEB_SEARCH_PROBE_FAILED {label} wrong contract")
        raise SystemExit(1)
    if loaded_sha != expected_sha:
        print(f"LIVE_WEB_SEARCH_PROBE_FAILED {label} stale loaded search source")
        raise SystemExit(1)
    if payload.get("status") != "healthy" or not probes or not all(bool(p.get("ok")) for p in probes):
        print(f"LIVE_WEB_SEARCH_PROBE_FAILED {label} repeated search probe")
        raise SystemExit(1)
    if payload.get("effective_mode") == "direct" and not all(p.get("backend") == "direct" for p in probes):
        print(f"LIVE_WEB_SEARCH_PROBE_FAILED {label} unexpected backend")
        raise SystemExit(1)
    return probes


expected_sha = hashlib.sha256(SEARCH_SOURCE.read_bytes()).hexdigest()

first = fetch_probe("first")
print("=== LIVE WEB SEARCH PROBE 1 ===")
print(json.dumps(safe_view(first, expected_sha), indent=2))
first_probes = validate(first, expected_sha, "first")

second = fetch_probe("immediate-repeat")
print("=== LIVE WEB SEARCH PROBE 2 (IMMEDIATE REPEAT) ===")
print(json.dumps(safe_view(second, expected_sha), indent=2))
second_probes = validate(second, expected_sha, "immediate-repeat")

if second.get("effective_mode") == "direct":
    misses = [
        p.get("query")
        for p in second_probes
        if not bool((p.get("cache") or {}).get("hit"))
    ]
    if misses:
        print("LIVE_WEB_SEARCH_PROBE_FAILED immediate repeat did not use cache: " + ", ".join(str(x) for x in misses))
        raise SystemExit(1)

print("LIVE_WEB_SEARCH_PROBE_PASS")
