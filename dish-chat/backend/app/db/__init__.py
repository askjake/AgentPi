"""
app/db/__init__.py

Central re-export hub for the database package.

All symbols that the rest of the application imports directly from
`app.db` are re-exported here so that `from app.db import X` works
regardless of which internal module originally defines X.
"""
from app.db.base import (
    Base,
    DatabaseSessionManager,
    sessionmanager,
    get_db,
)
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# FastAPI dependency: yields a session, commits on success, rolls back on error
# ---------------------------------------------------------------------------
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency – use with Depends(get_db_session).
    Yields an AsyncSession, commits on success, rolls back on exception.
    """
    async with sessionmanager.session() as session:
        yield session


# Alias used by several routers that import `get_session`
get_session = get_db_session


# ---------------------------------------------------------------------------
# Context-manager variant: for use outside of FastAPI dependency injection
# (background tasks, services, etc.)
# ---------------------------------------------------------------------------
from contextlib import asynccontextmanager

@asynccontextmanager
async def get_db_session_ctxmgr() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context-manager variant – use with `async with get_db_session_ctxmgr() as session`.
    Commits on success, rolls back on exception.
    """
    async with sessionmanager.session() as session:
        yield session


__all__ = [
    "Base",
    "DatabaseSessionManager",
    "sessionmanager",
    "get_db",
    "get_db_session",
    "get_session",
    "get_db_session_ctxmgr",
]
