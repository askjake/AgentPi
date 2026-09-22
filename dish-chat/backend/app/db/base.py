"""
Database base configuration and session management.

The sessionmanager is built once at module-import time.  To ensure that
POSTGRES_* environment variables have been loaded from .env before we read
them, we call dotenv.load_dotenv() here before any os.getenv() call.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, MappedColumn, mapped_column


# Load .env so that os.getenv() always returns the configured values even
# when this module is imported before pydantic-settings runs.
#
# We search up from this file's directory to find the first .env file,
# which handles both "run from backend/" and "run from backend/app/" cases.
_here = os.path.dirname(__file__)
for _candidate in [
    os.path.join(_here, "..", "..", ".env"),   # backend/.env  (normal)
    os.path.join(_here, "..", ".env"),          # backend/app/.env  (fallback)
]:
    _abs = os.path.abspath(_candidate)
    if os.path.isfile(_abs):
        load_dotenv(_abs, override=False)   # override=False: real env vars win
        break


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass



class DatabaseSessionManager:
    """Manage async database connections and sessions."""

    def __init__(self, url: str) -> None:
        self.engine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
        self.session_maker = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield a session; commit on success, rollback on error."""
        async with self.session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @asynccontextmanager
    async def connect(self):
        """Yield a raw engine connection."""
        async with self.engine.begin() as conn:
            yield conn

    async def close(self) -> None:
        """Dispose of all connections."""
        await self.engine.dispose()


def _build_db_url() -> str:
    """
    Build the SQLAlchemy async URL from POSTGRES_* environment variables.
    load_dotenv() above ensures these are populated from .env when running
    outside of uvicorn's pydantic-settings startup path.
    """
    user = os.getenv("POSTGRES_USER", "dev_user")
    pwd  = os.getenv("POSTGRES_PWD",  "dev123")
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB",   "dishchat")
    return f"postgresql+asyncpg://{user}:{pwd}@{host}:{port}/{db}"


# Global session manager – initialised once at import time using correct creds
sessionmanager = DatabaseSessionManager(_build_db_url())


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency – kept for backward compatibility."""
    async with sessionmanager.session() as session:
        yield session


async def get_db_session():
    """
    FastAPI dependency alias exported directly from base.py.
    Some modules import this from app.db.base rather than app.db.
    Delegates to the global sessionmanager.
    """
    async with sessionmanager.session() as session:
        yield session
