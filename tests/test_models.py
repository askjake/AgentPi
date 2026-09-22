from backend.models import Device, stable_device_id


def test_properties_are_not_shared():
    assert Device().properties is not Device().properties


def test_stable_device_id_is_stable_and_protocol_scoped():
    assert stable_device_id("arp", "AA") == stable_device_id("arp", "aa")
    assert stable_device_id("arp", "AA") != stable_device_id("mqtt", "AA")


def test_error_device_serializes():
    d = Device.error_device("rtsp", "bad range")
    assert d.device_type == "error"
    assert d.online is False
    assert d.to_dict()["properties"]["error"] == "bad range"
