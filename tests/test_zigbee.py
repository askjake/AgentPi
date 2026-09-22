import json
from types import SimpleNamespace
from backend.discovery.zigbee import parse_zigbee_devices, ZigbeeListener


def test_current_z2m_payload_uses_definition_vendor_and_interview_state():
    payload=json.dumps([{
        "ieee_address":"0x1","friendly_name":"lamp","type":"Router","supported":True,
        "interview_state":"SUCCESSFUL","definition":{"vendor":"Philips","model":"X","description":"dimmable light","exposes":[{"type":"light"}]}
    }])
    d=parse_zigbee_devices(payload)[0]
    assert d.manufacturer == "Philips"
    assert d.device_type == "smart_light"
    assert d.online is True


def test_non_object_item_is_ignored():
    assert parse_zigbee_devices('[null, 7, "x"]') == []


def test_listener_composes_with_mqtt_and_tracks_availability():
    handlers={}; emitted=[]
    class Discovery:
        def add_topic_handler(self,t,h): handlers[t]=h
        def remove_topic_handler(self,t): handlers.pop(t,None)
    listener=ZigbeeListener(emitted.extend)
    d=Discovery(); listener.attach(d)
    bridge=listener.zigbee_bridge_devices
    handlers[bridge](None,None,SimpleNamespace(topic=bridge,payload=json.dumps([{
        "ieee_address":"0x1","friendly_name":"lamp","type":"Router","interview_state":"SUCCESSFUL","definition":{"vendor":"Philips","description":"light"}
    }]).encode()))
    avail=listener.base_topic+"/lamp/availability"
    handlers[listener.zigbee_availability](None,None,SimpleNamespace(topic=avail,payload=b'{"state":"offline"}'))
    assert emitted[-1].name == "lamp"
    assert emitted[-1].online is False

def test_zigbee_identity_is_stable():
    payload=json.dumps([{"ieee_address":"0xabc","friendly_name":"x","interview_state":"SUCCESSFUL","definition":{}}])
    assert parse_zigbee_devices(payload)[0].id == parse_zigbee_devices(payload)[0].id


def test_custom_base_topic_is_registered():
    topics=[]
    class Discovery:
        def add_topic_handler(self,t,h): topics.append(t)
        def remove_topic_handler(self,t): pass
    listener=ZigbeeListener(lambda d:None, base_topic="house/zigbee")
    listener.attach(Discovery())
    assert "house/zigbee/bridge/devices" in topics
    assert "house/zigbee/+/availability" in topics
