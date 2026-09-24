from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "dish-chat"
BACKEND = APP_ROOT / "backend"

os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("PYTHONPATH", str(BACKEND))
os.environ.setdefault("AUTH_DISABLED", "true")
os.environ.setdefault("LOCAL", "true")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("FASTAPI_HOST", "127.0.0.1")
os.environ.setdefault("FASTAPI_PORT", "8000")
os.environ.setdefault("POSTGRES_HOST", "127.0.0.1")
os.environ.setdefault("POSTGRES_PORT", "55432")
os.environ.setdefault("AGENTPI_URL", "http://127.0.0.1:8765")
os.environ.setdefault("AGENT_MODE_WORKDIR", str(ROOT / "runtime" / "workspaces"))
os.environ.setdefault("IDLE_CHAT_CHECKER_ENABLED", "false")
os.environ.setdefault("ENABLE_BETAREPORT_MCP", "false")
os.environ.setdefault("ENABLE_VIEWERSHIP_MCP", "false")
os.environ.setdefault("ENABLE_LOG_ASSIST_MCP", "false")
os.environ.setdefault("ENABLE_INTERNAL_TOOLS_MCP", "false")

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False, log_level="info")
