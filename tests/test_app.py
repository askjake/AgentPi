from fastapi.testclient import TestClient

from backend.app import create_app
from backend.models import Device


def test_health_and_dashboard():
    app = create_app()
    with TestClient(app) as client:
        health = client.get("/rest/api/v1/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["inventory"]["total"] == 0
        assert client.get("/").status_code == 200


def test_local_scan_upserts_devices_and_reports_errors(monkeypatch):
    async def fake_arp(lookup_vendors=False):
        return [Device(id="arp1", name="host", protocol="arp", address="192.0.2.10")]

    async def fake_mdns(timeout=2.0):
        return [
            Device(id="mdns1", name="svc", protocol="mdns", device_type="mdns_service"),
            Device.error_device("mdns", "one service failed"),
        ]

    monkeypatch.setattr("backend.app.scan_arp", fake_arp)
    monkeypatch.setattr("backend.app.discover_mdns_devices_async", fake_mdns)
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/rest/api/v1/discovery/scan",
            json={"arp": True, "mdns": True, "mdns_timeout": 0.0},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["discovered"] == 2
        assert body["inventory"]["total"] == 2
        assert body["errors"][0]["source"] == "mdns"
        assert client.get("/rest/api/v1/devices").json()["count"] == 2
        assert client.delete("/rest/api/v1/devices").json()["cleared"] == 2


def test_rtsp_is_opt_in(monkeypatch):
    called = False
    async def fake_rtsp(*args, **kwargs):
        nonlocal called
        called = True
        return []
    monkeypatch.setattr("backend.app.scan_rtsp", fake_rtsp)
    app = create_app()
    with TestClient(app) as client:
        result = client.post(
            "/rest/api/v1/discovery/scan",
            json={"arp": False, "mdns": False},
        )
        assert result.status_code == 200
        assert called is False


def test_rtsp_request_is_bounded_by_api_schema():
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/rest/api/v1/discovery/scan",
            json={
                "arp": False, "mdns": False,
                "rtsp_cidr": "10.0.0.0/24", "rtsp_max_hosts": 9999,
            },
        )
        assert response.status_code == 422
