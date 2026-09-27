"""Pytest isolation for AgentPi persistent runtime state."""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# backend.app creates a module-level FastAPI app at import time. Give that
# import-time DeviceInventory an isolated DB before any test modules import it.
_SESSION_TMP = Path(tempfile.mkdtemp(prefix="agentpi-pytest-session-"))
os.environ["AGENTPI_DB"] = str(_SESSION_TMP / "import-inventory.db")


@atexit.register
def _cleanup_session_tmp() -> None:
    shutil.rmtree(_SESSION_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_agentpi_db(tmp_path, monkeypatch):
    """Every test gets a fresh SQLite inventory instead of production runtime state."""
    db_path = tmp_path / "agentpi-test-inventory.db"
    monkeypatch.setenv("AGENTPI_DB", str(db_path))
    yield db_path
