import asyncio
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.db import get_db_session_ctxmgr, sessionmanager

from .schemas import Health

router = APIRouter()

@router.get("/health", tags=["health"])
async def health_check() -> Health:
    return Health()

@router.get("/health/db", tags=["health"])
async def database_health_check() -> dict:
    """Verify PostgreSQL responsiveness and expose non-secret pool diagnostics."""
    async def _probe() -> None:
        async with get_db_session_ctxmgr() as db:
            await db.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_probe(), timeout=5.0)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "component": "postgresql",
                "error_type": type(exc).__name__,
            },
        ) from exc

    try:
        pool_status = sessionmanager.engine.sync_engine.pool.status()
    except Exception:
        pool_status = "unavailable"

    return {
        "status": "healthy",
        "component": "postgresql",
        "pool": pool_status,
    }


@router.get("/health/execution", tags=["health"])
async def execution_health_check() -> dict:
    """Identify the LOADED chat/agent bindings; no tool or provider is invoked."""
    import os
    from app.agent.agents import agentic_rag, coverity_tool_loop
    from app.agent_mode import agent
    identity = coverity_tool_loop.execution_identity()
    identity['chat_binding_matches'] = agentic_rag.run_coverity_tool_loop is coverity_tool_loop.run_coverity_tool_loop
    identity['agent_mode_binding_matches'] = agent.run_coverity_tool_loop is coverity_tool_loop.run_coverity_tool_loop
    identity['pid'] = os.getpid()
    identity['status'] = 'binding_verified' if identity['chat_binding_matches'] and identity['agent_mode_binding_matches'] else 'binding_mismatch'
    # Deliberately excludes credentials, URLs, user paths and conversation IDs.
    return identity
