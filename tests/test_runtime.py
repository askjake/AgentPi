import pytest

from backend.models import Device
from backend.runtime import RuntimeManager
from backend.store import DeviceInventory
import backend.runtime as runtime_mod


def test_mqtt_runtime_attaches_and_stops(monkeypatch):
    events = []
    class Discovery:
        is_running = True
    class Listener:
        def __init__(self, on_devices, base_topic):
            self.base_topic = base_topic
        def attach(self, discovery):
            events.append(("attach", self.base_topic, discovery.is_running))
        def detach(self):
            events.append(("detach", self.base_topic))
    monkeypatch.setattr(runtime_mod, "ZigbeeListener", Listener)
    monkeypatch.setattr(runtime_mod, "start_mqtt_discovery", lambda *a, **k: Discovery())
    monkeypatch.setattr(runtime_mod, "stop_mqtt_discovery", lambda *a, **k: True)

    manager = RuntimeManager(DeviceInventory())
    result = manager.start_mqtt(broker="broker", zigbee_base_topic="house/zigbee")
    assert result["running"] is True
    assert manager.status()["mqtt"][0]["broker"] == "broker"
    assert manager.stop_mqtt(broker="broker") is True
    assert events == [("attach", "house/zigbee", True), ("detach", "house/zigbee")]


@pytest.mark.asyncio
async def test_homeassistant_runtime_syncs_and_subscribes(monkeypatch):
    class Client:
        def __init__(self, url, token):
            self.url = url
        async def test_connection(self): return True
        async def sync_devices(self):
            return [Device(id="ha1", name="HA", protocol="homeassistant")]
        async def subscribe_events(self, callback):
            self.callback = callback
        def disconnect(self): pass
    monkeypatch.setattr(runtime_mod, "HomeAssistantClient", Client)
    inventory = DeviceInventory()
    manager = RuntimeManager(inventory)
    result = await manager.start_homeassistant(
        url="http://ha.local:8123", token="secret", subscribe=True,
    )
    assert result["synced"] == 1
    assert inventory.count() == 1
    assert manager.status()["homeassistant"] is True
    assert manager.stop_homeassistant() is True
