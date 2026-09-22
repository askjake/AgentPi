from datetime import timedelta

from backend.models import Device, utcnow
from backend.store import DeviceInventory


def test_inventory_upsert_preserves_first_seen_and_updates_last_seen():
    inventory = DeviceInventory()
    t0 = utcnow()
    t1 = t0 + timedelta(seconds=5)
    inventory.upsert(Device(id="x", name="old", protocol="arp", first_seen=t0, last_seen=t0))
    inventory.upsert(Device(id="x", name="new", protocol="arp", first_seen=t1, last_seen=t1))
    device = inventory.list()[0]
    assert inventory.count() == 1
    assert device.name == "new"
    assert device.first_seen == t0
    assert device.last_seen == t1


def test_inventory_filters_and_clear():
    inventory = DeviceInventory()
    inventory.upsert(Device(id="a", name="A", protocol="arp", device_type="host", online=True))
    inventory.upsert(Device(id="b", name="B", protocol="mdns", device_type="mdns_service", online=False))
    assert [d.id for d in inventory.list(protocol="arp")] == ["a"]
    assert [d.id for d in inventory.list(online=False)] == ["b"]
    assert inventory.summary()["total"] == 2
    assert inventory.clear() == 2
    assert inventory.count() == 0
