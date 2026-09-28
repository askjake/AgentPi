from __future__ import annotations

import json
import sys
import urllib.request

URL = "http://127.0.0.1:8000/rest/api/v1/health/search?probe=true"

try:
    with urllib.request.urlopen(URL, timeout=35) as response:
        payload = json.loads(response.read().decode("utf-8"))
except Exception as exc:
    print(f"LIVE_WEB_SEARCH_PROBE_FAILED transport={type(exc).__name__}: {exc}")
    raise SystemExit(1)

probe = payload.get("probe") or {}
safe = {
    "status": payload.get("status"),
    "configured_mode": payload.get("configured_mode"),
    "effective_mode": payload.get("effective_mode"),
    "direct_backends": payload.get("direct_backends"),
    "probe": {
        "ok": bool(probe.get("ok")),
        "backend": probe.get("backend"),
        "source": probe.get("source"),
        "result_count": probe.get("result_count"),
        "error": probe.get("error"),
        "attempts": probe.get("attempts", []),
    },
}
print(json.dumps(safe, indent=2))

if payload.get("status") != "healthy" or not probe.get("ok"):
    print("LIVE_WEB_SEARCH_PROBE_FAILED")
    raise SystemExit(1)

if payload.get("effective_mode") == "direct" and probe.get("backend") != "direct":
    print("LIVE_WEB_SEARCH_PROBE_FAILED unexpected backend")
    raise SystemExit(1)

print("LIVE_WEB_SEARCH_PROBE_PASS")
