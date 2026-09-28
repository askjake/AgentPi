from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SEARCH_SOURCE = ROOT / "dish-chat" / "backend" / "app" / "tools" / "web_search.py"
URL = "http://127.0.0.1:8000/rest/api/v1/health/search?probe=true"

try:
    with urllib.request.urlopen(URL, timeout=55) as response:
        payload = json.loads(response.read().decode("utf-8"))
except Exception as exc:
    print(f"LIVE_WEB_SEARCH_PROBE_FAILED transport={type(exc).__name__}: {exc}")
    raise SystemExit(1)

expected_sha = hashlib.sha256(SEARCH_SOURCE.read_bytes()).hexdigest()
loaded_sha = payload.get("loaded_search_source_sha256")
probes = payload.get("probes") or [payload.get("probe") or {}]

safe = {
    "status": payload.get("status"),
    "contract": payload.get("contract"),
    "configured_mode": payload.get("configured_mode"),
    "effective_mode": payload.get("effective_mode"),
    "direct_backends": payload.get("direct_backends"),
    "loaded_search_source_sha256": loaded_sha,
    "expected_search_source_sha256": expected_sha,
    "source_identity_matches": loaded_sha == expected_sha,
    "probes": probes,
}
print(json.dumps(safe, indent=2))

if payload.get("contract") != "agentpi-public-search-v2":
    print("LIVE_WEB_SEARCH_PROBE_FAILED wrong contract")
    raise SystemExit(1)
if loaded_sha != expected_sha:
    print("LIVE_WEB_SEARCH_PROBE_FAILED stale loaded search source")
    raise SystemExit(1)
if payload.get("status") != "healthy" or not probes or not all(bool(p.get("ok")) for p in probes):
    print("LIVE_WEB_SEARCH_PROBE_FAILED repeated search probe")
    raise SystemExit(1)
if payload.get("effective_mode") == "direct" and not all(p.get("backend") == "direct" for p in probes):
    print("LIVE_WEB_SEARCH_PROBE_FAILED unexpected backend")
    raise SystemExit(1)

print("LIVE_WEB_SEARCH_PROBE_PASS")
