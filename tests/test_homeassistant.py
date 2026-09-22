import asyncio
import pytest
from backend.discovery.homeassistant import HomeAssistantClient


def test_entity_to_device_uses_observation_time_and_canonical_manufacturer():
    client = HomeAssistantClient("http://ha.local", "token")
    d = client._entity_to_device({
        "entity_id":"sensor.temp",
        "state":"42",
        "last_changed":"2020-01-01T00:00:00+00:00",
        "attributes":{"friendly_name":"Temperature","manufacturer":"Acme","ip_address":"10.0.0.4"},
    })
    assert d.manufacturer == "Acme"
    assert d.address == "10.0.0.4"
    assert d.properties["ha_last_changed"].startswith("2020-")
    assert d.last_seen.year >= 2026


def test_skips_nonphysical_domain():
    client = HomeAssistantClient("http://ha.local", "token")
    assert client._entity_to_device({"entity_id":"automation.foo","attributes":{}}) is None


@pytest.mark.asyncio
async def test_ws_session_validates_subscription_and_emits_async_callback():
    sent = []
    emitted = []
    class FakeWS:
        def __init__(self):
            self.recv_values = iter([
                '{"type":"auth_required"}',
                '{"type":"auth_ok"}',
                '{"id":1,"type":"result","success":true,"result":null}',
            ])
            self.events = iter([
                '{"id":1,"type":"event","event":{"event_type":"state_changed","data":{"new_state":{"entity_id":"sensor.x","state":"1","attributes":{}}}}}'
            ])
        async def recv(self): return next(self.recv_values)
        async def send(self, value): sent.append(value)
        def __aiter__(self): return self
        async def __anext__(self):
            try: return next(self.events)
            except StopIteration: raise StopAsyncIteration
    class CM:
        async def __aenter__(self): return FakeWS()
        async def __aexit__(self,*a): return False
    class FakeWebsockets:
        @staticmethod
        def connect(url): return CM()
    client = HomeAssistantClient("http://ha.local", "token")
    async def cb(device): emitted.append(device)
    client._on_state_change = cb
    await client._ws_session(FakeWebsockets)
    assert emitted and emitted[0].id
    assert any("subscribe_events" in s for s in sent)


@pytest.mark.asyncio
async def test_ws_session_rejects_failed_subscription():
    class FakeWS:
        def __init__(self): self.values = iter(['{"type":"auth_required"}','{"type":"auth_ok"}','{"id":1,"type":"result","success":false}'])
        async def recv(self): return next(self.values)
        async def send(self,v): pass
    class CM:
        async def __aenter__(self): return FakeWS()
        async def __aexit__(self,*a): return False
    class W:
        @staticmethod
        def connect(url): return CM()
    client=HomeAssistantClient("http://ha.local","token")
    with pytest.raises(RuntimeError):
        await client._ws_session(W)

def test_malformed_state_is_ignored():
    client = HomeAssistantClient("http://ha.local", "token")
    assert client._entity_to_device(None) is None
    assert client._entity_to_device({"entity_id":"bad"}) is None
