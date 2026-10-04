import asyncio
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.db import get_db_session_ctxmgr, sessionmanager
from app.tools.web_search import probe_public_search, search_runtime_status

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
    from app.agent_mode import agent, child_conversation, mcop_tools, orchestration_packets
    identity = coverity_tool_loop.execution_identity()
    identity['chat_binding_matches'] = agentic_rag.run_coverity_tool_loop is coverity_tool_loop.run_coverity_tool_loop
    identity['agent_mode_binding_matches'] = agent.run_coverity_tool_loop is coverity_tool_loop.run_coverity_tool_loop

    expected_mcop = set(coverity_tool_loop.MCOP_TOOL_NAMES)
    agent_mode_names = {
        str(getattr(tool, 'name', '') or '')
        for tool in agentic_rag.get_tools_set('agent_mode')
    }
    mcop = identity.setdefault('mcop', {})
    mcop.update({
        'registry_binding_matches': expected_mcop.issubset(agent_mode_names),
        'bound_tool_names': sorted(expected_mcop & agent_mode_names),
        'max_depth': child_conversation.MCOP_MAX_DEPTH,
        'max_children': child_conversation.MCOP_MAX_CHILDREN,
        'parallel_limit': child_conversation.MCOP_PARALLEL_LIMIT,
        'loaded_child_sha256': child_conversation.LOADED_SOURCE_SHA256,
        'loaded_tools_sha256': mcop_tools.LOADED_SOURCE_SHA256,
        'loaded_packets_sha256': orchestration_packets.LOADED_SOURCE_SHA256,
    })
    identity['pid'] = os.getpid()
    identity['status'] = (
        'binding_verified'
        if identity['chat_binding_matches']
        and identity['agent_mode_binding_matches']
        and mcop['registry_binding_matches']
        else 'binding_mismatch'
    )
    # Deliberately excludes credentials, URLs, user paths and conversation IDs.
    return identity


@router.get("/health/search", tags=["health"])
async def search_health_check(probe: bool = False) -> dict:
    """Report the configured public-search route; optionally execute a safe probe."""
    if probe:
        return await probe_public_search()
    return search_runtime_status()
