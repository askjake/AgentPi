from types import SimpleNamespace
from backend.discovery import mdns


def test_missing_dependency_returns_error(monkeypatch):
    monkeypatch.setattr(mdns, "ZEROCONF_AVAILABLE", False)
    devices = mdns.discover_mdns_devices(0)
    assert devices[0].device_type == "error"


def test_resolution_is_stable_and_browsers_cancel(monkeypatch):
    cancelled=[]
    class Info:
        port=80; server="thing.local."
        def parsed_scoped_addresses(self): return ["fe80::1%3","192.168.1.2"]
    class ZC:
        def get_service_info(self, stype, name, timeout=0): return Info()
        def close(self): self.closed=True
    zc=ZC()
    class Browser:
        def __init__(self, z, service, listener):
            self.service=service
            if service == mdns.SERVICES[0]: listener.add_service(z, service, "Thing."+service)
        def cancel(self): cancelled.append(self.service)
    monkeypatch.setattr(mdns,"ZEROCONF_AVAILABLE",True)
    monkeypatch.setattr(mdns,"Zeroconf",lambda: zc)
    monkeypatch.setattr(mdns,"ServiceBrowser",Browser)
    one=mdns.discover_mdns_devices(0)
    two=mdns.discover_mdns_devices(0)
    assert one[0].id == two[0].id
    assert one[0].address == "192.168.1.2"
    assert len(cancelled) == len(mdns.SERVICES)*2
