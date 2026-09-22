from app.tools import agentpi_bridge as bridge


def test_compact_devices_limits_fields():
    data = {"devices": [{
        "id":"1", "name":"x", "device_type":"host", "address":"1.2.3.4",
        "mac":"AA", "port":None, "protocol":"arp", "interface":"eth0",
        "manufacturer":None, "online":True, "properties":{"secret":"not copied"}
    }]}
    compact = bridge._compact_devices(data)
    assert compact[0]["id"] == "1"
    assert "properties" not in compact[0]


def test_base_url_from_env(monkeypatch):
    monkeypatch.setenv("AGENTPI_URL", "http://127.0.0.1:9999/")
    assert bridge._base_url() == "http://127.0.0.1:9999"
