import pytest
from backend.discovery import arp


def test_parse_proc_arp_filters_incomplete():
    text = "IP address HW type Flags HW address Mask Device\n10.0.0.2 0x1 0x2 aa:bb:cc:dd:ee:ff * eth0\n10.0.0.3 0x1 0x0 00:00:00:00:00:00 * eth0\n"
    assert arp._parse_proc_arp(text) == [{
        "ip":"10.0.0.2","mac":"AA:BB:CC:DD:EE:FF","iface":"eth0","state":"reachable"
    }]


def test_parse_windows_arp():
    text = "Interface: 192.168.1.50 --- 0x7\n  192.168.1.1          aa-bb-cc-dd-ee-ff     dynamic\n"
    entries = arp._parse_windows_arp(text)
    assert entries[0]["mac"] == "AA:BB:CC:DD:EE:FF"
    assert entries[0]["iface"] == "192.168.1.50"


@pytest.mark.asyncio
async def test_scan_populates_canonical_fields(monkeypatch):
    async def entries():
        return [{"ip":"10.0.0.2","mac":"aa-bb-cc-dd-ee-ff","iface":"wlan0","state":"reachable"}]
    monkeypatch.setattr(arp, "_neighbor_entries", entries)
    devices = await arp.scan_arp(False)
    assert len(devices) == 1
    d = devices[0]
    assert d.mac == "AA:BB:CC:DD:EE:FF"
    assert d.interface == "wlan0"
    assert d.address == "10.0.0.2"
    assert d.properties["arp_state"] == "reachable"


@pytest.mark.asyncio
async def test_scan_identity_survives_ip_change(monkeypatch):
    calls = iter([
        [{"ip":"10.0.0.2","mac":"aa:bb:cc:dd:ee:ff","iface":"eth0","state":"reachable"}],
        [{"ip":"10.0.0.9","mac":"aa:bb:cc:dd:ee:ff","iface":"eth0","state":"reachable"}],
    ])
    async def entries(): return next(calls)
    monkeypatch.setattr(arp, "_neighbor_entries", entries)
    first = (await arp.scan_arp())[0]
    second = (await arp.scan_arp())[0]
    assert first.id == second.id
