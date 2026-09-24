from __future__ import annotations

import os
import sys
import asyncio
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dish-chat" / "backend"
RUNTIME = ROOT / "runtime"
LOCAL_DB_ENV = RUNTIME / "local-db.env"

if not LOCAL_DB_ENV.is_file():
    raise SystemExit(f"Local DB environment missing: {LOCAL_DB_ENV}")

# Put the real DishChat package root on sys.path before importing app.*.
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

# Local DB credentials intentionally override the Pi-imported .env values.
load_dotenv(LOCAL_DB_ENV, override=True)
os.environ["POSTGRES_HOST"] = "127.0.0.1"
os.environ["POSTGRES_PORT"] = "55432"
os.environ["AUTH_DISABLED"] = "true"
os.environ["LOCAL"] = "true"
os.environ["DEBUG"] = "false"
os.environ["FASTAPI_HOST"] = "127.0.0.1"
os.environ["FASTAPI_PORT"] = "8000"
os.environ["AGENTPI_URL"] = "http://127.0.0.1:8765"
os.environ["AGENT_MODE_WORKDIR"] = str(RUNTIME / "workspaces")
os.environ["IDLE_CHAT_CHECKER_ENABLED"] = "false"
os.environ["ENABLE_BETAREPORT_MCP"] = "false"
os.environ["ENABLE_VIEWERSHIP_MCP"] = "false"
os.environ["ENABLE_LOG_ASSIST_MCP"] = "false"
os.environ["ENABLE_INTERNAL_TOOLS_MCP"] = "false"

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False, log_level="info", loop="asyncio:SelectorEventLoop")
