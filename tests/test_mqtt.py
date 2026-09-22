from types import SimpleNamespace
from backend.discovery import mqtt as mod


class FakeReason(int):
    pass


class FakeClient:
    instances=[]
    def __init__(self, api):
        self.api=api; self.on_connect=None; self.on_message=None; self.subscriptions=[]; self.disconnected=False; self.suppress_exceptions=False
        FakeClient.instances.append(self)
    def username_pw_set(self,*a): pass
    def reconnect_delay_set(self,**kw): pass
    def subscribe(self,topic): self.subscriptions.append(topic); return (0,len(self.subscriptions))
    def unsubscribe(self,topic): return (0,1)
    def connect(self,*a): return 0
    def disconnect(self): self.disconnected=True
    def loop_forever(self,retry_first_connection=False):
        self.on_connect(self,None,SimpleNamespace(session_present=False),FakeReason(0),None)


class FakeMQTT:
    class CallbackAPIVersion: VERSION2=2
    Client=FakeClient
    @staticmethod
    def topic_matches_sub(flt,topic):
        fs=flt.split('/'); ts=topic.split('/')
        if len(fs)!=len(ts): return False
        return all(f=='+' or f==t for f,t in zip(fs,ts))


def test_missing_import_exposes_none():
    # Contract exists regardless of whether paho is installed.
    assert hasattr(mod, "mqtt")


def test_device_identity_and_removal():
    d=mod.MQTTDiscovery("broker")
    topic="homeassistant/sensor/node/temp/config"
    a=d._device_from_ha_message(topic,b'{"name":"T","unique_id":"u1"}')
    b=d._device_from_ha_message(topic,b'{"name":"T","unique_id":"u1"}')
    removed=d._device_from_ha_message(topic,b'')
    assert a.id == b.id
    assert removed.online is False and removed.properties["removed"] is True


def test_run_uses_v2_and_both_homeassistant_filters(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(mod,"mqtt",FakeMQTT)
    monkeypatch.setattr(mod,"MQTT_AVAILABLE",True)
    d=mod.MQTTDiscovery("broker")
    d._run()
    c=FakeClient.instances[-1]
    assert c.api == 2
    assert "homeassistant/+/+/config" in c.subscriptions
    assert "homeassistant/+/+/+/config" in c.subscriptions


def test_topic_handlers_resubscribe_on_connect(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(mod,"mqtt",FakeMQTT)
    monkeypatch.setattr(mod,"MQTT_AVAILABLE",True)
    d=mod.MQTTDiscovery("broker")
    d.add_topic_handler("zigbee2mqtt/bridge/devices", lambda *a:None)
    d._run()
    assert "zigbee2mqtt/bridge/devices" in FakeClient.instances[-1].subscriptions

def test_invalid_config_payload_is_ignored():
    d=mod.MQTTDiscovery("broker")
    assert d._device_from_ha_message("homeassistant/sensor/x/config", b'{bad') is None
    assert d._device_from_ha_message("homeassistant/sensor/x/config", b'[]') is None


def test_unique_id_controls_identity_across_topic_name_change():
    d=mod.MQTTDiscovery("broker")
    a=d._device_from_ha_message("homeassistant/sensor/node/old/config",b'{"unique_id":"stable"}')
    b=d._device_from_ha_message("homeassistant/sensor/node/new/config",b'{"unique_id":"stable"}')
    assert a.id == b.id
