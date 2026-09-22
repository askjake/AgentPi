from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "dish-chat" / "backend"
LOCAL_DB_ENV = ROOT / "runtime" / "local-db.env"

if not LOCAL_DB_ENV.is_file():
    raise SystemExit(f"Local DB environment missing: {LOCAL_DB_ENV}")

os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

load_dotenv(BACKEND / ".env", override=False)
load_dotenv(LOCAL_DB_ENV, override=True)

os.environ["POSTGRES_HOST"] = "127.0.0.1"
os.environ["POSTGRES_PORT"] = "55432"
os.environ["AUTH_DISABLED"] = os.environ.get("AUTH_DISABLED", "true")
os.environ["LOCAL"] = os.environ.get("LOCAL", "true")
os.environ["DEBUG"] = os.environ.get("DEBUG", "false")
os.environ["FASTAPI_HOST"] = "0.0.0.0"
os.environ["FASTAPI_PORT"] = "8000"
os.environ["AGENTPI_URL"] = "http://127.0.0.1:8765"
os.environ["AGENT_MODE_WORKDIR"] = str(ROOT / "runtime" / "workspaces")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
        loop="asyncio:SelectorEventLoop",
    )
