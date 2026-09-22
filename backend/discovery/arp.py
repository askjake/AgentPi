"""
ARP Table Scanner + MAC Vendor Lookup
Reads /proc/net/arp and ip neigh, resolves OUI to manufacturer.
"""
import asyncio
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from backend.models import Device

logger = logging.getLogger(__name__)

# OUI prefix → device type hints (first 8 chars of MAC, uppercase, colon-separated)
OUI_TYPE_HINTS = {
    # Raspberry Pi Foundation
    "B8:27:EB": "host", "DC:A6:32": "host", "E4:5F:01": "host",
    # Espressif (ESP8266/ESP32)
    "24:0A:C4": "iot", "30:AE:A4": "iot", "84:F3:EB": "iot",
    "A4:CF:12": "iot", "EC:FA:BC": "iot", "94:B9:7E": "iot",
    # Apple
    "00:17:F2": "host", "3C:15:C2": "host", "A8:86:DD": "host",
    # Samsung
    "00:26:37": "tv", "8C:77:12": "tv", "F4:7B:5E": "tv",
    # Sonos
    "00:0E:58": "media_server", "5C:AA:FD": "media_server",
    # NVIDIA
    "00:04:4B": "game_console",
    # Philips (Hue)
    "00:17:88": "smart_light",
    # TP-Link
    "50:C7:BF": "router", "B0:4E:26": "router",
    # Ubiquiti
    "00:15:6D": "ap", "04:18:D6": "ap", "78:8A:20": "ap",
    # Netgear
    "00:14:6C": "router", "20:4E:7F": "router",
}

MFR_TYPE_HINTS = {
    "apple": "host",
    "espressif": "iot",
    "raspberry pi": "host",
    "nvidia": "game_console",
    "samsung": "tv",
    "sonos": "media_server",
    "philips": "smart_light",
    "signify": "smart_light",
    "ubiquiti": "ap",
    "tp-link": "router",
    "netgear": "router",
    "asus": "router",
    "linksys": "router",
    "synology": "nas",
    "qnap": "nas",
    "western digital": "nas",
    "canon": "printer",
    "hp": "printer",
    "epson": "printer",
    "brother": "printer",
    "google": "voice_assistant",
    "amazon": "voice_assistant",
    "govee": "smart_light",
    "lifx": "smart_light",
    "shelly": "smart_plug",
    "sonoff": "iot",
    "tasmota": "iot",
}


def _oui_type(mac: str) -> Optional[str]:
    prefix = mac.upper()[:8]
    return OUI_TYPE_HINTS.get(prefix)


async def _lookup_mac_vendor(mac: str, timeout: float = 3.0) -> str:
    """Query macvendors.com API for MAC OUI manufacturer."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"https://api.macvendors.com/{mac}")
            if resp.status_code == 200:
                return resp.text.strip()
    except Exception as exc:
        logger.debug("MAC vendor lookup failed for %s: %s", mac, exc)
    return ""


def _read_proc_arp() -> List[dict]:
    """Parse /proc/net/arp for ARP table entries."""
    entries = []
    try:
        with open("/proc/net/arp") as f:
            lines = f.readlines()
        for line in lines[1:]:  # skip header
            parts = line.split()
            if len(parts) >= 4:
                ip, hw_type, flags, mac = parts[0], parts[1], parts[2], parts[3]
                iface = parts[5] if len(parts) > 5 else ""
                if mac != "00:00:00:00:00:00" and flags != "0x0":
                    entries.append({"ip": ip, "mac": mac.upper(), "iface": iface})
    except Exception as exc:
        logger.warning("Could not read /proc/net/arp: %s", exc)
    return entries


async def _run_ip_neigh() -> List[dict]:
    """Run `ip neigh show` for additional ARP/NDP entries."""
    entries = []
    try:
        proc = await asyncio.create_subprocess_exec(
            "ip", "neigh", "show",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        for line in stdout.decode().splitlines():
            # Format: 192.168.1.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE
            m = re.match(
                r"(\S+)\s+dev\s+(\S+)\s+lladdr\s+([0-9a-fA-F:]{17})\s+(\S+)",
                line
            )
            if m:
                ip, iface, mac, state = m.groups()
                if state not in ("FAILED", "INCOMPLETE"):
                    entries.append({"ip": ip, "mac": mac.upper(), "iface": iface, "state": state})
    except Exception as exc:
        logger.warning("ip neigh failed: %s", exc)
    return entries


async def scan_arp(lookup_vendors: bool = True) -> List[Device]:
    """Scan ARP table and return Device list with MAC vendor info."""
    # Merge proc/arp and ip neigh, dedup by IP
    seen_ips = {}
    for entry in _read_proc_arp():
        seen_ips[entry["ip"]] = entry
    for entry in await _run_ip_neigh():
        if entry["ip"] not in seen_ips:
            seen_ips[entry["ip"]] = entry

    # Vendor lookups (rate-limited — batch with small delay)
    vendor_map = {}
    if lookup_vendors:
        for i, (ip, entry) in enumerate(seen_ips.items()):
            mac = entry["mac"]
            if i > 0:
                await asyncio.sleep(0.5)  # respect rate limit
            vendor = await _lookup_mac_vendor(mac)
            vendor_map[ip] = vendor

    now = datetime.now(timezone.utc)
    devices = []
    for ip, entry in seen_ips.items():
        mac = entry["mac"]
        vendor = vendor_map.get(ip, "")

        # Determine device type
        dev_type = _oui_type(mac)
        if not dev_type and vendor:
            vl = vendor.lower()
            for key, t in MFR_TYPE_HINTS.items():
                if key in vl:
                    dev_type = t
                    break
        if not dev_type:
            dev_type = "host"

        name = vendor if vendor else mac
        dev = Device(
            id=str(uuid.uuid5(uuid.NAMESPACE_OID, mac)),
            name=f"{name} ({ip})",
            device_type=dev_type,
            address=ip,
            port=None,
            protocol="arp",
            properties={
                "mac": mac,
                "manufacturer": vendor,
                "interface": entry.get("iface", ""),
                "arp_state": entry.get("state", "reachable"),
            },
            online=True,
            first_seen=now,
            last_seen=now,
        )
        devices.append(dev)
        logger.info("ARP found: %s [%s] %s (%s)", ip, mac, vendor, dev_type)

    return devices
