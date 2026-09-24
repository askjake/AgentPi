from __future__ import annotations
import json, os
from typing import Optional
import httpx
from langchain.tools import tool

def _base() -> str:
    return os.environ.get("AGENTPI_URL", "http://127.0.0.1:8765").rstrip("/")

def _req(method: str, path: str, *, body=None, params=None, t: float = 30.0):
    with httpx.Client(timeout=t) as c:
        r = c.request(method, _base() + path, json=body, params=params)
        r.raise_for_status()
        return r.json()

def _compact(data: dict, lim: int = 100) -> list:
    return [
        {"id": d.get("id"), "name": d.get("name"), "device_type": d.get("device_type"),
         "address": d.get("address"), "mac": d.get("mac"), "port": d.get("port"),
         "protocol": d.get("protocol"), "interface": d.get("interface"),
         "manufacturer": d.get("manufacturer"), "online": d.get("online")}
        for d in (data.get("devices") or [])[:lim]
    ]

# ── Existing tools ────────────────────────────────────────────────────────────

@tool("agentpi_health")
def agentpi_health() -> str:
    """Check whether the local AgentPi discovery/tool service is healthy."""
    try:    return json.dumps(_req("GET", "/rest/api/v1/health", t=5.0), indent=2)
    except Exception as e: return f"AgentPi health check failed: {e}"

@tool("agentpi_discover_devices")
def agentpi_discover_devices(arp: bool = True, mdns: bool = True, mdns_timeout: float = 2.0) -> str:
    """Discover local network devices via ARP and/or mDNS.
    Set arp=False for mDNS-only. Set mdns=False for ARP-only.
    mdns_timeout: seconds to listen (max 10).
    """
    try:
        payload = {"arp": bool(arp), "mdns": bool(mdns),
                   "mdns_timeout": max(0.0, min(float(mdns_timeout), 10.0)),
                   "lookup_vendors": False}
        d = _req("POST", "/rest/api/v1/discovery/scan", body=payload,
                 t=max(15.0, payload["mdns_timeout"] + 8.0))
        return json.dumps({"sources": d.get("sources", []), "discovered": d.get("discovered", 0),
                           "errors": d.get("errors", []), "inventory": d.get("inventory", {}),
                           "devices": _compact(d)}, indent=2)
    except Exception as e: return f"AgentPi discovery failed: {e}"

@tool("agentpi_list_devices")
def agentpi_list_devices(protocol: Optional[str] = None, device_type: Optional[str] = None,
                          online: Optional[bool] = None) -> str:
    """List devices currently in AgentPi's local inventory."""
    try:
        params = {}
        if protocol:            params["protocol"]    = protocol
        if device_type:         params["device_type"] = device_type
        if online is not None:  params["online"]      = str(bool(online)).lower()
        d = _req("GET", "/rest/api/v1/devices", params=params, t=10.0)
        return json.dumps({"count": d.get("count", 0), "devices": _compact(d)}, indent=2)
    except Exception as e: return f"AgentPi inventory query failed: {e}"

@tool("agentpi_scan_rtsp")
def agentpi_scan_rtsp(cidr: str, concurrency: int = 8, max_hosts: int = 64) -> str:
    """Run a bounded RTSP camera scan over the given CIDR range."""
    try:
        payload = {"arp": False, "mdns": False, "rtsp_cidr": cidr,
                   "rtsp_concurrency": max(1, min(int(concurrency), 32)),
                   "rtsp_max_hosts":   max(1, min(int(max_hosts),   256))}
        d = _req("POST", "/rest/api/v1/discovery/scan", body=payload, t=180.0)
        return json.dumps({"discovered": d.get("discovered", 0), "errors": d.get("errors", []),
                           "devices": _compact(d)}, indent=2)
    except Exception as e: return f"AgentPi RTSP scan failed: {e}"

@tool("agentpi_runtime_status")
def agentpi_runtime_status() -> str:
    """Show AgentPi MQTT and Home Assistant runtime connection status."""
    try:    return json.dumps(_req("GET", "/rest/api/v1/runtime", t=5.0), indent=2)
    except Exception as e: return f"AgentPi runtime query failed: {e}"

# ── NEW tools (PATCH-04) ──────────────────────────────────────────────────────

@tool("agentpi_mqtt_start")
def agentpi_mqtt_start(broker: str, port: int = 1883,
                        username: Optional[str] = None, password: Optional[str] = None,
                        zigbee_base_topic: str = "zigbee2mqtt") -> str:
    """Connect AgentPi to an MQTT broker (Mosquitto, Zigbee2MQTT, etc).
    broker: IP or hostname. port: TCP port (default 1883).
    zigbee_base_topic: Zigbee2MQTT topic prefix (default 'zigbee2mqtt').
    """
    try:
        p: dict = {"broker": broker, "port": int(port), "zigbee_base_topic": zigbee_base_topic}
        if username: p["username"] = username
        if password: p["password"] = password
        return json.dumps(_req("POST", "/rest/api/v1/mqtt/start", body=p, t=15.0), indent=2)
    except Exception as e: return f"AgentPi MQTT start failed: {e}"

@tool("agentpi_mqtt_stop")
def agentpi_mqtt_stop(broker: str, port: int = 1883, username: Optional[str] = None) -> str:
    """Disconnect AgentPi from an MQTT broker. broker/port must match agentpi_mqtt_start."""
    try:
        p: dict = {"broker": broker, "port": int(port)}
        if username: p["username"] = username
        return json.dumps(_req("POST", "/rest/api/v1/mqtt/stop", body=p, t=10.0), indent=2)
    except Exception as e: return f"AgentPi MQTT stop failed: {e}"

@tool("agentpi_homeassistant_start")
def agentpi_homeassistant_start(url: str, token: str, subscribe: bool = True) -> str:
    """Connect AgentPi to a Home Assistant instance.
    url: HA base URL e.g. http://homeassistant.local:8123
    token: Long-lived access token from HA Profile → Security.
    """
    try:
        return json.dumps(_req("POST", "/rest/api/v1/homeassistant/start",
                               body={"url": url, "token": token, "subscribe": subscribe},
                               t=20.0), indent=2)
    except Exception as e: return f"AgentPi HA start failed: {e}"

@tool("agentpi_homeassistant_stop")
def agentpi_homeassistant_stop() -> str:
    """Disconnect AgentPi from Home Assistant."""
    try:    return json.dumps(_req("POST", "/rest/api/v1/homeassistant/stop", t=10.0), indent=2)
    except Exception as e: return f"AgentPi HA stop failed: {e}"

@tool("agentpi_clear_inventory")
def agentpi_clear_inventory() -> str:
    """Clear ALL devices from AgentPi's local inventory. Returns count removed."""
    try:    return json.dumps(_req("DELETE", "/rest/api/v1/devices", t=10.0), indent=2)
    except Exception as e: return f"AgentPi inventory clear failed: {e}"
