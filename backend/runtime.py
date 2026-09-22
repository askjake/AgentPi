from __future__ import annotations

import asyncio
import threading
from typing import Dict, Optional, Tuple

from backend.discovery.homeassistant import HomeAssistantClient
from backend.discovery.mqtt import start_mqtt_discovery, stop_mqtt_discovery
from backend.discovery.zigbee import ZigbeeListener
from backend.store import DeviceInventory


class RuntimeManager:
    """Own long-lived MQTT/Zigbee and Home Assistant subscriptions."""

    def __init__(self, inventory: DeviceInventory) -> None:
        self.inventory = inventory
        self._lock = threading.RLock()
        self._mqtt: Dict[Tuple[str, int, str], ZigbeeListener] = {}
        self._ha: Optional[HomeAssistantClient] = None

    def start_mqtt(
        self,
        *,
        broker: str,
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        zigbee_base_topic: str = "zigbee2mqtt",
    ) -> dict:
        key = (str(broker), int(port), username or "")
        with self._lock:
            previous = self._mqtt.pop(key, None)
        if previous is not None:
            previous.detach()

        discovery = start_mqtt_discovery(
            broker,
            port=port,
            username=username,
            password=password,
            on_device=self.inventory.upsert,
        )
        listener = ZigbeeListener(
            on_devices=self.inventory.upsert_many,
            base_topic=zigbee_base_topic,
        )
        listener.attach(discovery)
        with self._lock:
            self._mqtt[key] = listener
        return {
            "broker": str(broker),
            "port": int(port),
            "username": username or None,
            "running": bool(discovery.is_running),
            "zigbee_base_topic": zigbee_base_topic,
        }

    def stop_mqtt(
        self,
        *,
        broker: str,
        port: int = 1883,
        username: Optional[str] = None,
    ) -> bool:
        key = (str(broker), int(port), username or "")
        with self._lock:
            listener = self._mqtt.pop(key, None)
        if listener is not None:
            listener.detach()
        return stop_mqtt_discovery(broker, port=port, username=username)

    async def start_homeassistant(
        self,
        *,
        url: str,
        token: str,
        subscribe: bool = True,
    ) -> dict:
        self.stop_homeassistant()
        client = HomeAssistantClient(url, token)
        if not await client.test_connection():
            raise ConnectionError("Home Assistant connection failed")
        devices = await client.sync_devices()
        self.inventory.upsert_many(devices)
        if subscribe:
            await client.subscribe_events(self.inventory.upsert)
        self._ha = client
        return {
            "url": url.rstrip("/"),
            "synced": len(devices),
            "subscribed": bool(subscribe),
        }

    def stop_homeassistant(self) -> bool:
        client = self._ha
        self._ha = None
        if client is None:
            return False
        client.disconnect()
        return True

    async def shutdown(self) -> None:
        self.stop_homeassistant()
        with self._lock:
            keys = list(self._mqtt)
        for broker, port, username in keys:
            await asyncio.to_thread(
                self.stop_mqtt,
                broker=broker,
                port=port,
                username=username or None,
            )

    def status(self) -> dict:
        with self._lock:
            mqtt = [
                {"broker": b, "port": p, "username": u or None}
                for b, p, u in sorted(self._mqtt)
            ]
        return {
            "mqtt": mqtt,
            "homeassistant": self._ha is not None,
        }
