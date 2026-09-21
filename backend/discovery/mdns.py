import time
from typing import List
from ..models import Device
try:
    from zeroconf import ServiceBrowser, Zeroconf
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False

SERVICES = [
    '_http._tcp.local.', '_ssh._tcp.local.', '_smb._tcp.local.',
    '_homekit._tcp.local.', '_hap._tcp.local.', '_googlecast._tcp.local.',
    '_airplay._tcp.local.', '_mqtt._tcp.local.', '_esphome._tcp.local.',
    '_home-assistant._tcp.local.'
]

def discover_mdns_devices(timeout: float = 5.0) -> List[Device]:
    if not ZEROCONF_AVAILABLE:
        return [Device(name="zeroconf-unavailable", device_type="mdns_service",
            address="", protocol="mdns", online=False,
            properties={"error": "zeroconf not installed"})]
    found = []
    zc = Zeroconf()
    class Listener:
        def add_service(self, zc, stype, name):
            try:
                info = zc.get_service_info(stype, name, timeout=2000)
                if info:
                    addrs = [str(a) for a in info.parsed_scoped_addresses()]
                    found.append(Device(
                        name=name.replace(f'.{stype}', ''),
                        device_type='mdns_service',
                        address=addrs[0] if addrs else '',
                        port=info.port, protocol='mdns',
                        properties={'service_type': stype, 'server': info.server}
                    ))
            except Exception: pass
        def remove_service(self, *a): pass
        def update_service(self, *a): pass
    [ServiceBrowser(zc, s, Listener()) for s in SERVICES]
    time.sleep(timeout)
    zc.close()
    return found
