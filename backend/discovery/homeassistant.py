"""
Home Assistant REST + WebSocket Integration.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from backend.models import Device, stable_device_id, utcnow

logger = logging.getLogger(__name__)

HA_DOMAIN_TYPE_MAP = {
    "light": "smart_light",
    "switch": "smart_plug",
    "climate": "thermostat",
    "sensor": "sensor",
    "binary_sensor": "sensor",
    "camera": "camera_ip",
    "media_player": "media_server",
    "vacuum": "iot",
    "fan": "iot",
    "cover": "iot",
    "lock": "iot",
    "alarm_control_panel": "iot",
    "device_tracker": "host",
    "weather": "sensor",
}

_SKIP_DOMAINS = {
    "person", "zone", "sun", "automation", "script", "scene",
    "input_boolean", "input_number", "input_text", "input_select",
    "input_datetime", "timer", "counter", "group",
}

DeviceCallback = Callable[[Device], Any]


class HomeAssistantClient:
    """Async client for Home Assistant REST and WebSocket APIs."""

    def __init__(self, url: str, token: str, reconnect_delay: float = 2.0):
        self.url = url.rstrip("/")
        self.token = token
        self.reconnect_delay = max(0.1, float(reconnect_delay))
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._ws_task: Optional[asyncio.Task] = None
        self._on_state_change: Optional[DeviceCallback] = None

    async def test_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.url}/api/", headers=self._headers)
                return resp.status_code == 200
        except Exception as exc:
            logger.error("HA connection test failed: %s", exc)
            return False

    async def get_config(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.url}/api/config", headers=self._headers)
                resp.raise_for_status()
                payload = resp.json()
                return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            logger.error("HA get_config failed: %s", exc)
            return {}

    async def get_states(self) -> List[dict]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(f"{self.url}/api/states", headers=self._headers)
                resp.raise_for_status()
                payload = resp.json()
                return payload if isinstance(payload, list) else []
        except Exception as exc:
            logger.error("HA get_states failed: %s", exc)
            return []

    def _entity_to_device(self, state: dict) -> Optional[Device]:
        if not isinstance(state, dict):
            return None
        entity_id = str(state.get("entity_id") or "")
        if not entity_id or "." not in entity_id:
            return None
        domain = entity_id.split(".", 1)[0]
        if domain in _SKIP_DOMAINS:
            return None

        attributes = state.get("attributes") or {}
        if not isinstance(attributes, dict):
            attributes = {}
        friendly_name = str(attributes.get("friendly_name") or entity_id)
        device_type = HA_DOMAIN_TYPE_MAP.get(domain, "iot")
        if domain == "media_player" and (
            "tv" in friendly_name.lower() or "television" in friendly_name.lower()
        ):
            device_type = "tv"

        entity_state = str(state.get("state", "unknown"))
        online = entity_state not in {"unavailable", "unknown"}
        address = attributes.get("ip") or attributes.get("host") or attributes.get("ip_address")
        manufacturer = attributes.get("manufacturer")
        now = utcnow()

        props: Dict[str, Any] = {
            "entity_id": entity_id,
            "domain": domain,
            "state": entity_state,
            "friendly_name": friendly_name,
            "source": "homeassistant",
            "ha_last_changed": state.get("last_changed"),
            "ha_last_updated": state.get("last_updated"),
        }
        for key in (
            "device_class", "unit_of_measurement", "icon", "manufacturer", "model",
            "sw_version", "battery_level", "temperature", "humidity", "brightness",
            "color_temp", "rgb_color", "media_title", "media_artist", "source",
            "supported_features",
        ):
            if key in attributes:
                props[key] = attributes[key]

        return Device(
            id=stable_device_id("homeassistant", entity_id),
            name=friendly_name,
            device_type=device_type,
            address=str(address) if address is not None else None,
            protocol="homeassistant",
            manufacturer=str(manufacturer) if manufacturer else None,
            properties=props,
            online=online,
            first_seen=now,
            last_seen=now,
        )

    async def sync_devices(self) -> List[Device]:
        devices: List[Device] = []
        skipped = 0
        for state in await self.get_states():
            dev = self._entity_to_device(state)
            if dev is None:
                skipped += 1
            else:
                devices.append(dev)
        logger.info("HA sync: %d devices, %d skipped", len(devices), skipped)
        return devices

    def _websocket_url(self) -> str:
        parts = urlsplit(self.url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        return urlunsplit((scheme, parts.netloc, parts.path.rstrip("/") + "/api/websocket", "", ""))

    async def _emit(self, dev: Device) -> None:
        callback = self._on_state_change
        if callback is None:
            return
        try:
            result = callback(dev)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("HA state-change callback failed for %s", dev.id)

    async def _ws_session(self, websockets_module) -> None:
        async with websockets_module.connect(self._websocket_url()) as ws:
            hello = json.loads(await ws.recv())
            if hello.get("type") != "auth_required":
                raise RuntimeError(f"unexpected HA websocket greeting: {hello.get('type')!r}")

            await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            auth = json.loads(await ws.recv())
            if auth.get("type") != "auth_ok":
                raise PermissionError(auth.get("message") or "HA websocket authentication failed")

            subscription_id = 1
            await ws.send(json.dumps({
                "id": subscription_id,
                "type": "subscribe_events",
                "event_type": "state_changed",
            }))
            result = json.loads(await ws.recv())
            if (
                result.get("type") != "result"
                or result.get("id") != subscription_id
                or not result.get("success")
            ):
                raise RuntimeError(f"HA state_changed subscription failed: {result!r}")

            logger.info("HA WebSocket: subscribed to state_changed events")
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    logger.warning("HA WebSocket delivered malformed JSON")
                    continue
                if msg.get("type") != "event" or msg.get("id") != subscription_id:
                    continue
                event = msg.get("event") or {}
                if event.get("event_type") != "state_changed":
                    continue
                new_state = (event.get("data") or {}).get("new_state")
                dev = self._entity_to_device(new_state) if new_state else None
                if dev is not None:
                    await self._emit(dev)

    async def subscribe_events(self, on_device: DeviceCallback):
        """Start a reconnecting background subscription to state_changed events."""
        self.disconnect()
        self._on_state_change = on_device
        try:
            import websockets
        except ImportError:
            logger.warning("websockets not installed — HA WebSocket sync unavailable")
            return None

        async def _ws_loop():
            while True:
                try:
                    await self._ws_session(websockets)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("HA WebSocket error: %s", exc)
                    await asyncio.sleep(self.reconnect_delay)

        self._ws_task = asyncio.create_task(_ws_loop(), name="agentpi-ha-events")
        return self._ws_task

    def disconnect(self) -> None:
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        self._ws_task = None
