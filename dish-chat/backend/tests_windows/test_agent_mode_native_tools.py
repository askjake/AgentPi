from __future__ import annotations

from pathlib import Path

from app.agent_mode import tools as agent_tools


class _DummySocket:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_device_port_probe_uses_native_socket(monkeypatch):
    calls = []

    def fake_create_connection(address, timeout):
        calls.append((address, timeout))
        return _DummySocket()

    monkeypatch.setattr(agent_tools.socket, "create_connection", fake_create_connection)

    result = agent_tools.agent_check_device.func(
        ip_address="192.0.2.25",
        check_type="port",
        port=3000,
    )

    assert "Port 3000: OPEN" in result
    assert calls == [(("192.0.2.25", 3000), 2.0)]


def test_agent_run_python_uses_current_interpreter(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_tools, "BASE_AGENT_WORKDIR", str(tmp_path))

    result = agent_tools.agent_run_python.func(
        chat_id="runtime-python",
        code="import sys; print(sys.executable)",
        filename="runtime_probe.py",
        use_venv=False,
    )

    assert "return code=0" in result
    assert str(Path(agent_tools.sys.executable)) in result
