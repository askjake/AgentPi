# app/agent_mode/router.py
"""
Agent Mode router.

Mounts sub-routers:
  GET /rest/api/v1/agent-mode/runs          - list runs for a chat
  GET /rest/api/v1/agent-mode/runs/{run_id} - get single run
  (artifacts mounted separately in main.py via artifacts_router)
"""
from fastapi import APIRouter

from app.agent_mode.runs_router import router as runs_router

router = APIRouter(prefix="/agent-mode", tags=["agent-mode"])
router.include_router(runs_router)
