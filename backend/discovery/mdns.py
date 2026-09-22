from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional

from backend.models import Device, stable_device_id, utcnow

logger = logging.getLogger(__name__)

try:
    from zeroconf import ServiceBrowser, Zeroconf
    ZEROCONF_AVAILABLE = True
except ImportError:
    ServiceBrowser = None
    Zeroconf = None
    ZEROCONF_AVAILABLE = False

SERVICES = [
    "_http._tcp.local.", "_ssh._tcp.local.", "_smb._tcp.local.",
    "_homekit._tcp.local.", "_hap._tcp.local.", "_googlecast._tcp.local.",
    "_airplay._tcp.local.", "_mqtt._tcp.local.", "_esphome._tcp.local.",
    "_home-assistant._tcp.local.",
]


def _choose_address(addresses: List[str]) -> Optional[str]:
    if not addresses:
        return None
    for address in addresses:
        if "." in address and ":" not in address:
            return address
    return addresses[0]


def discover_mdns_devices(timeout: float = 5.0) -> List[Device]:
    if timeout < 0:
        return [Device.error_device("mdns", "timeout must be >= 0")]
    if not ZEROCONF_AVAILABLE or Zeroconf is None or ServiceBrowser is None:
        return [Device.error_device("mdns", "zeroconf not installed")]

    found: Dict[tuple[str, str], Device] = {}
    browsers = []
    try:
        zc = Zeroconf()
    except Exception as exc:
        logger.exception("Could not create Zeroconf instance")
        return [Device.error_device("mdns", f"zeroconf initialization failed: {exc}")]

    class Listener:
        def _resolve(self, zc_obj, service_type: str, name: str) -> None:
            try:
                info = zc_obj.get_service_info(service_type, name, timeout=2000)
                if not info:
                    return
                addresses = [str(a) for a in info.parsed_scoped_addresses()]
                now = utcnow()
                found[(service_type, name)] = Device(
                    id=stable_device_id("mdns", service_type, name),
                    name=name[:-len(service_type) - 1] if name.endswith("." + service_type) else name,
                    device_type="mdns_service",
                    address=_choose_address(addresses),
                    port=info.port,
                    protocol="mdns",
                    properties={
                        "service_type": service_type,
                        "server": info.server,
                        "addresses": addresses,
                    },
                    online=True,
                    first_seen=now,
                    last_seen=now,
                )
            except Exception as exc:
                logger.warning("mDNS resolution failed for %s (%s): %s", name, service_type, exc)

        def add_service(self, zc_obj, service_type, name):
            self._resolve(zc_obj, service_type, name)

        def update_service(self, zc_obj, service_type, name):
            self._resolve(zc_obj, service_type, name)

        def remove_service(self, zc_obj, service_type, name):
            found.pop((service_type, name), None)

    listener = Listener()
    try:
        for service in SERVICES:
            browsers.append(ServiceBrowser(zc, service, listener))
        time.sleep(timeout)
    except Exception as exc:
        logger.exception("mDNS browsing failed")
        return [Device.error_device("mdns", f"browse failed: {exc}")]
    finally:
        for browser in browsers:
            try:
                browser.cancel()
            except Exception:
                logger.debug("Failed to cancel mDNS browser", exc_info=True)
        try:
            zc.close()
        except Exception:
            logger.debug("Failed to close Zeroconf", exc_info=True)

    return list(found.values())


async def discover_mdns_devices_async(timeout: float = 5.0) -> List[Device]:
    return await asyncio.to_thread(discover_mdns_devices, timeout)
