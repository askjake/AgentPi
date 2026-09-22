from __future__ import annotations

import json
import os
from typing import Optional

import httpx
from langchain.tools import tool


def _base_url() -> str:
    return os.environ.get("AGENTPI_URL", "http://127.0.0.1:8765").rstrip("/")


def _request(method: str, path: str, *, json_body=None, params=None, timeout: float = 30.0):
    url = _base_url() + path
    with httpx.Client(timeout=timeout) as client:
        response = client.request(method, url, json=json_body, params=params)
        response.raise_for_status()
        return response.json()


def _compact_devices(data: dict, limit: int = 100) -> list[dict]:
    devices = data.get("devices") or []
    result = []
    for device in devices[:limit]:
        result.append({
            "id": device.get("id"),
            "name": device.get("name"),
            "device_type": device.get("device_type"),
            "address": device.get("address"),
            "mac": device.get("mac"),
            "port": device.get("port"),
            "protocol": device.get("protocol"),
            "interface": device.get("interface"),
            "manufacturer": device.get("manufacturer"),
            "online": device.get("online"),
        })
    return result


@tool("agentpi_health")
def agentpi_health() -> str:
    """Check whether the local AgentPi discovery/tool service is healthy."""
    try:
        return json.dumps(_request("GET", "/rest/api/v1/health", timeout=5.0), indent=2)
    except Exception as exc:
        return f"AgentPi health check failed: {exc}"


@tool("agentpi_discover_devices")
def agentpi_discover_devices(
    arp: bool = True,
    mdns: bool = True,
    mdns_timeout: float = 2.0,
) -> str:
    """Discover local devices with AgentPi using safe ARP and mDNS discovery.

    External MAC-vendor lookup is intentionally disabled. RTSP scanning is a
    separate explicit tool because it is more expensive and should stay bounded.
    """
    try:
        payload = {
            "arp": bool(arp),
            "mdns": bool(mdns),
            "mdns_timeout": max(0.0, min(float(mdns_timeout), 10.0)),
            "lookup_vendors": False,
        }
        data = _request(
            "POST", "/rest/api/v1/discovery/scan",
            json_body=payload,
            timeout=max(15.0, payload["mdns_timeout"] + 8.0),
        )
        return json.dumps({
            "sources": data.get("sources", []),
            "discovered": data.get("discovered", 0),
            "errors": data.get("errors", []),
            "inventory": data.get("inventory", {}),
            "devices": _compact_devices(data),
        }, indent=2)
    except Exception as exc:
        return f"AgentPi discovery failed: {exc}"


@tool("agentpi_list_devices")
def agentpi_list_devices(
    protocol: Optional[str] = None,
    device_type: Optional[str] = None,
    online: Optional[bool] = None,
) -> str:
    """List devices currently held in AgentPi's local inventory."""
    try:
        params = {}
        if protocol:
            params["protocol"] = protocol
        if device_type:
            params["device_type"] = device_type
        if online is not None:
            params["online"] = str(bool(online)).lower()
        data = _request("GET", "/rest/api/v1/devices", params=params, timeout=10.0)
        return json.dumps({
            "count": data.get("count", 0),
            "devices": _compact_devices(data),
        }, indent=2)
    except Exception as exc:
        return f"AgentPi inventory query failed: {exc}"


@tool("agentpi_scan_rtsp")
def agentpi_scan_rtsp(
    cidr: str,
    concurrency: int = 8,
    max_hosts: int = 64,
) -> str:
    """Run an explicit bounded RTSP camera scan with AgentPi.

    cidr must be intentionally supplied. max_hosts is capped at 256 and
    concurrency at 32 by this bridge even though the underlying service also
    performs its own validation.
    """
    try:
        payload = {
            "arp": False,
            "mdns": False,
            "rtsp_cidr": cidr,
            "rtsp_concurrency": max(1, min(int(concurrency), 32)),
            "rtsp_max_hosts": max(1, min(int(max_hosts), 256)),
        }
        data = _request(
            "POST", "/rest/api/v1/discovery/scan",
            json_body=payload,
            timeout=180.0,
        )
        return json.dumps({
            "discovered": data.get("discovered", 0),
            "errors": data.get("errors", []),
            "devices": _compact_devices(data),
        }, indent=2)
    except Exception as exc:
        return f"AgentPi RTSP scan failed: {exc}"


@tool("agentpi_runtime_status")
def agentpi_runtime_status() -> str:
    """Show AgentPi MQTT/Zigbee and Home Assistant runtime connection status."""
    try:
        return json.dumps(_request("GET", "/rest/api/v1/runtime", timeout=5.0), indent=2)
    except Exception as exc:
        return f"AgentPi runtime query failed: {exc}"
