"""
ARP / neighbor-table discovery with optional MAC vendor lookup.

Linux sources:
- /proc/net/arp
- `ip neigh show`

Windows source:
- `arp -a`
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import platform
import re
import shutil
from typing import Dict, List, Optional

import httpx

from backend.models import Device, stable_device_id, utcnow

logger = logging.getLogger(__name__)

OUI_TYPE_HINTS = {
    "B8:27:EB": "host", "DC:A6:32": "host", "E4:5F:01": "host",
    "24:0A:C4": "iot", "30:AE:A4": "iot", "84:F3:EB": "iot",
    "A4:CF:12": "iot", "EC:FA:BC": "iot", "94:B9:7E": "iot",
    "00:17:F2": "host", "3C:15:C2": "host", "A8:86:DD": "host",
    "00:26:37": "tv", "8C:77:12": "tv", "F4:7B:5E": "tv",
    "00:0E:58": "media_server", "5C:AA:FD": "media_server",
    "00:04:4B": "game_console",
    "00:17:88": "smart_light",
    "50:C7:BF": "router", "B0:4E:26": "router",
    "00:15:6D": "ap", "04:18:D6": "ap", "78:8A:20": "ap",
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

_VENDOR_CACHE: Dict[str, str] = {}


def _normalize_mac(mac: str) -> str:
    compact = re.sub(r"[^0-9A-Fa-f]", "", mac)
    if len(compact) != 12:
        return mac.upper().replace("-", ":")
    return ":".join(compact[i:i + 2] for i in range(0, 12, 2)).upper()


def _is_unicast_neighbor(ip: str, mac: str) -> bool:
    """Reject broadcast/multicast pseudo-neighbors from OS ARP tables."""
    normalized = _normalize_mac(mac)
    compact = re.sub(r"[^0-9A-Fa-f]", "", normalized)
    if len(compact) != 12:
        return False
    try:
        first_octet = int(compact[:2], 16)
    except ValueError:
        return False
    if first_octet & 0x01:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if address.is_multicast or address.is_unspecified:
        return False
    if str(address) == "255.255.255.255":
        return False
    return True


def _oui_type(mac: str) -> Optional[str]:
    return OUI_TYPE_HINTS.get(_normalize_mac(mac)[:8])


async def _lookup_mac_vendor(mac: str, timeout: float = 3.0) -> str:
    """Query macvendors.com. This is deliberately opt-in at scan level."""
    mac = _normalize_mac(mac)
    if mac in _VENDOR_CACHE:
        return _VENDOR_CACHE[mac]
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"https://api.macvendors.com/{mac}")
            if resp.status_code == 200:
                vendor = resp.text.strip()
                _VENDOR_CACHE[mac] = vendor
                return vendor
    except Exception as exc:
        logger.debug("MAC vendor lookup failed for %s: %s", mac, exc)
    _VENDOR_CACHE.setdefault(mac, "")
    return ""


def _parse_proc_arp(text: str) -> List[dict]:
    entries: List[dict] = []
    lines = text.splitlines()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        ip, flags, mac = parts[0], parts[2], _normalize_mac(parts[3])
        iface = parts[5] if len(parts) > 5 else ""
        if (
            mac != "00:00:00:00:00:00"
            and flags != "0x0"
            and _is_unicast_neighbor(ip, mac)
        ):
            entries.append({"ip": ip, "mac": mac, "iface": iface, "state": "reachable"})
    return entries


def _read_proc_arp() -> List[dict]:
    path = "/proc/net/arp"
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return _parse_proc_arp(handle.read())
    except Exception as exc:
        logger.warning("Could not read /proc/net/arp: %s", exc)
        return []


def _parse_ip_neigh(text: str) -> List[dict]:
    entries: List[dict] = []
    pattern = re.compile(
        r"^(\S+)\s+dev\s+(\S+).*?\slladdr\s+([0-9a-fA-F:-]{17})\s+(\S+)\s*$"
    )
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        ip, iface, mac, state = match.groups()
        if state.upper() in {"FAILED", "INCOMPLETE"}:
            continue
        if not _is_unicast_neighbor(ip, mac):
            continue
        entries.append({
            "ip": ip,
            "mac": _normalize_mac(mac),
            "iface": iface,
            "state": state.lower(),
        })
    return entries


async def _run_ip_neigh() -> List[dict]:
    if shutil.which("ip") is None:
        return []
    try:
        proc = await asyncio.create_subprocess_exec(
            "ip", "neigh", "show",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        return _parse_ip_neigh(stdout.decode(errors="replace"))
    except Exception as exc:
        logger.warning("ip neigh failed: %s", exc)
        return []


def _parse_windows_arp(text: str) -> List[dict]:
    entries: List[dict] = []
    interface = ""
    for raw in text.splitlines():
        line = raw.strip()
        match = re.match(r"Interface:\s+(\S+)\s+---", line, re.IGNORECASE)
        if match:
            interface = match.group(1)
            continue
        match = re.match(
            r"^(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9A-Fa-f-]{17})\s+(dynamic|static)$",
            line,
            re.IGNORECASE,
        )
        if not match:
            continue
        ip, mac, state = match.groups()
        if not _is_unicast_neighbor(ip, mac):
            continue
        entries.append({
            "ip": ip,
            "mac": _normalize_mac(mac),
            "iface": interface,
            "state": state.lower(),
        })
    return entries


async def _run_windows_arp() -> List[dict]:
    if shutil.which("arp") is None:
        return []
    try:
        proc = await asyncio.create_subprocess_exec(
            "arp", "-a",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        return _parse_windows_arp(stdout.decode(errors="replace"))
    except Exception as exc:
        logger.warning("arp -a failed: %s", exc)
        return []


async def _neighbor_entries() -> List[dict]:
    if platform.system().lower() == "windows":
        return await _run_windows_arp()
    entries = _read_proc_arp()
    entries.extend(await _run_ip_neigh())
    return entries


def _classify(mac: str, vendor: str) -> str:
    hinted = _oui_type(mac)
    if hinted:
        return hinted
    vendor_l = vendor.lower()
    for key, device_type in MFR_TYPE_HINTS.items():
        if key in vendor_l:
            return device_type
    return "host"


async def scan_arp(
    lookup_vendors: bool = False,
    vendor_delay: float = 0.5,
) -> List[Device]:
    """Read the local neighbor table and convert entries to canonical Device records."""
    # Prefer a MAC identity so the same host does not become a new Device when its IP changes.
    by_mac: Dict[str, dict] = {}
    for entry in await _neighbor_entries():
        mac = _normalize_mac(entry.get("mac", ""))
        if not mac or mac == "00:00:00:00:00:00":
            continue
        if not _is_unicast_neighbor(str(entry.get("ip", "")), mac):
            continue
        current = by_mac.get(mac)
        if current is None or current.get("state") == "stale":
            normalized = dict(entry)
            normalized["mac"] = mac
            by_mac[mac] = normalized

    vendor_map: Dict[str, str] = {}
    if lookup_vendors:
        for index, mac in enumerate(by_mac):
            if index and vendor_delay > 0:
                await asyncio.sleep(vendor_delay)
            vendor_map[mac] = await _lookup_mac_vendor(mac)

    now = utcnow()
    devices: List[Device] = []
    for mac, entry in by_mac.items():
        ip = entry.get("ip") or None
        interface = entry.get("iface") or None
        vendor = vendor_map.get(mac, "")
        device_type = _classify(mac, vendor)
        name_base = vendor or mac
        name = f"{name_base} ({ip})" if ip else name_base
        devices.append(Device(
            id=stable_device_id("arp", mac),
            name=name,
            device_type=device_type,
            address=ip,
            mac=mac,
            protocol="arp",
            interface=interface,
            manufacturer=vendor or None,
            properties={
                "arp_state": entry.get("state", "reachable"),
                "source": "neighbor_table",
            },
            online=True,
            first_seen=now,
            last_seen=now,
        ))
    return devices
