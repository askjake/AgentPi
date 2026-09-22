"""
Home Assistant REST + WebSocket Integration
Fetches entity states and syncs device inventory from a local HA instance.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

from backend.models import Device

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
    "input_boolean": "iot",
    "automation": "iot",
    "script": "iot",
    "scene": "iot",
    "device_tracker": "host",
    "person": "host",
    "weather": "sensor",
    "sun": "sensor",
    "zone": "sensor",
}


class HomeAssistantClient:
    """Async client for Home Assistant REST and WebSocket APIs."""

    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._ws_task: Optional[asyncio.Task] = None
        self._on_state_change: Optional[Callable[[Device], None]] = None

    async def test_connection(self) -> bool:
        """Test HA API connectivity."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self.url}/api/",
                    headers=self._headers
                )
                return resp.status_code == 200
        except Exception as exc:
            logger.error("HA connection test failed: %s", exc)
            return False

    async def get_config(self) -> dict:
        """GET /api/config — HA instance configuration."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.url}/api/config",
                    headers=self._headers
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("HA get_config failed: %s", exc)
            return {}

    async def get_states(self) -> List[dict]:
        """GET /api/states — all entity states."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.url}/api/states",
                    headers=self._headers
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("HA get_states failed: %s", exc)
            return []

    def _entity_to_device(self, state: dict) -> Optional[Device]:
        """Convert a HA entity state dict to an AgentPi Device."""
        entity_id: str = state.get("entity_id", "")
        if not entity_id:
            return None

        domain = entity_id.split(".")[0]
        # Skip non-physical entities
        if domain in ("person", "zone", "sun", "automation", "script", "scene",
                      "input_boolean", "input_number", "input_text", "input_select",
                      "input_datetime", "timer", "counter", "group"):
            return None

        attributes: dict = state.get("attributes", {})
        friendly_name = attributes.get("friendly_name") or entity_id
        dev_type = HA_DOMAIN_TYPE_MAP.get(domain, "iot")

        # Refine media_player type
        if domain == "media_player":
            device_class = attributes.get("device_class", "")
            if "tv" in friendly_name.lower() or "television" in friendly_name.lower():
                dev_type = "tv"

        now = datetime.now(timezone.utc)
        entity_state = state.get("state", "unknown")
        is_online = entity_state not in ("unavailable", "unknown")

        # Extract IP/host if available
        address = (
            attributes.get("ip") or
            attributes.get("host") or
            attributes.get("ip_address") or
            None
        )

        # Parse last_changed timestamp
        last_changed_str = state.get("last_changed", "")
        try:
            last_changed = datetime.fromisoformat(last_changed_str.replace("Z", "+00:00"))
        except Exception:
            last_changed = now

        props = {
            "entity_id": entity_id,
            "domain": domain,
            "state": entity_state,
            "friendly_name": friendly_name,
            "source": "homeassistant",
        }
        # Include useful attributes
        for key in ("device_class", "unit_of_measurement", "icon",
                    "manufacturer", "model", "sw_version",
                    "battery_level", "temperature", "humidity",
                    "brightness", "color_temp", "rgb_color",
                    "media_title", "media_artist", "source",
                    "supported_features"):
            if key in attributes:
                props[key] = attributes[key]

        return Device(
            id=str(uuid.uuid5(uuid.NAMESPACE_OID, f"ha:{entity_id}")),
            name=friendly_name,
            device_type=dev_type,
            address=address,
            port=None,
            protocol="homeassistant",
            properties=props,
            online=is_online,
            first_seen=last_changed,
            last_seen=last_changed,
        )

    async def sync_devices(self) -> List[Device]:
        """Fetch all HA states and convert to Device list."""
        states = await self.get_states()
        devices = []
        skipped = 0
        for state in states:
            dev = self._entity_to_device(state)
            if dev:
                devices.append(dev)
            else:
                skipped += 1
        logger.info("HA sync: %d devices, %d skipped", len(devices), skipped)
        return devices

    async def subscribe_events(self, on_device: Callable[[Device], None]):
        """
        Connect to HA WebSocket API and subscribe to state_changed events.
        Runs as a background task — call cancel() to stop.
        """
        self._on_state_change = on_device
        ws_url = self.url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/websocket"

        try:
            import websockets  # optional dependency
        except ImportError:
            logger.warning("websockets not installed — HA WebSocket sync unavailable")
            return

        async def _ws_loop():
            msg_id = 1
            try:
                async with websockets.connect(ws_url) as ws:
                    # Auth handshake
                    auth_required = json.loads(await ws.recv())
                    if auth_required.get("type") == "auth_required":
                        await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                        auth_ok = json.loads(await ws.recv())
                        if auth_ok.get("type") != "auth_ok":
                            logger.error("HA WebSocket auth failed")
                            return

                    # Subscribe to state_changed
                    await ws.send(json.dumps({
                        "id": msg_id, "type": "subscribe_events",
                        "event_type": "state_changed"
                    }))
                    msg_id += 1

                    logger.info("HA WebSocket: subscribed to state_changed events")

                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("type") == "event":
                            event = msg.get("event", {})
                            if event.get("event_type") == "state_changed":
                                new_state = event.get("data", {}).get("new_state")
                                if new_state:
                                    dev = self._entity_to_device(new_state)
                                    if dev and self._on_state_change:
                                        self._on_state_change(dev)
            except Exception as exc:
                logger.error("HA WebSocket error: %s", exc)

        self._ws_task = asyncio.create_task(_ws_loop())
        return self._ws_task

    def disconnect(self):
        """Cancel WebSocket subscription."""
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
