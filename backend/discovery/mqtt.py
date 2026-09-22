from __future__ import annotations

import json
import logging
import threading
from typing import Callable, Dict, Optional

from backend.models import Device, stable_device_id, utcnow

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    mqtt = None
    MQTT_AVAILABLE = False

MessageHandler = Callable[[object, object, object], None]


def _ha_identity(topic: str, payload: dict) -> str:
    unique_id = payload.get("unique_id")
    if unique_id:
        return str(unique_id)
    object_id = payload.get("object_id")
    if object_id:
        return str(object_id)
    return topic.removesuffix("/config")


class MQTTDiscovery:
    def __init__(self, broker, port=1883, username=None, password=None, on_device=None):
        self.broker = broker
        self.port = int(port)
        self.username = username
        self.password = password
        self.on_device = on_device
        self._client = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._topic_handlers: Dict[str, MessageHandler] = {}

    @property
    def client(self):
        return self._client

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def add_topic_handler(self, topic_filter: str, handler: MessageHandler) -> None:
        with self._lock:
            self._topic_handlers[topic_filter] = handler
            client = self._client
        if client is not None:
            try:
                client.subscribe(topic_filter)
            except Exception:
                logger.debug("MQTT subscribe failed while adding %s", topic_filter, exc_info=True)

    def remove_topic_handler(self, topic_filter: str) -> None:
        with self._lock:
            self._topic_handlers.pop(topic_filter, None)
            client = self._client
        if client is not None:
            try:
                client.unsubscribe(topic_filter)
            except Exception:
                logger.debug("MQTT unsubscribe failed for %s", topic_filter, exc_info=True)

    def start(self):
        if not MQTT_AVAILABLE or mqtt is None:
            logger.warning("paho-mqtt not installed — MQTT discovery unavailable")
            return False
        with self._lock:
            if self.is_running:
                return True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True, name=f"agentpi-mqtt-{self.broker}:{self.port}")
            self._thread.start()
        return True

    def stop(self, join_timeout: float = 3.0):
        self._stop_event.set()
        client = self._client
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                logger.debug("MQTT disconnect failed", exc_info=True)
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, join_timeout))
        return not self.is_running

    def _emit(self, device: Device) -> None:
        if not self.on_device:
            return
        try:
            self.on_device(device)
        except Exception:
            logger.exception("MQTT device callback failed for %s", device.id)

    def _device_from_ha_message(self, topic: str, payload: bytes) -> Optional[Device]:
        now = utcnow()
        if not payload:
            identity = topic.removesuffix("/config")
            return Device(
                id=stable_device_id("mqtt", self.broker, self.port, identity),
                name=identity.rsplit("/", 1)[-1] or "removed",
                device_type="mqtt",
                address=self.broker,
                port=self.port,
                protocol="mqtt",
                online=False,
                properties={"topic": topic, "removed": True},
                first_seen=now,
                last_seen=now,
            )
        try:
            decoded = payload.decode("utf-8")
            config = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("Invalid MQTT discovery payload on %s: %s", topic, exc)
            return None
        if not isinstance(config, dict):
            logger.warning("Ignoring non-object MQTT discovery payload on %s", topic)
            return None
        identity = _ha_identity(topic, config)
        name = config.get("name") or config.get("object_id") or identity.rsplit("/", 1)[-1] or "unknown"
        return Device(
            id=stable_device_id("mqtt", self.broker, self.port, identity),
            name=str(name),
            device_type="mqtt",
            address=self.broker,
            port=self.port,
            protocol="mqtt",
            properties={
                "topic": topic,
                "unique_id": config.get("unique_id", ""),
                "object_id": config.get("object_id", ""),
                "component": topic.split("/")[1] if "/" in topic else "",
                "payload": config,
            },
            online=True,
            first_seen=now,
            last_seen=now,
        )

    def _run(self):
        assert mqtt is not None
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.suppress_exceptions = True
        if self.username:
            client.username_pw_set(self.username, self.password)
        if hasattr(client, "reconnect_delay_set"):
            client.reconnect_delay_set(min_delay=1, max_delay=30)

        def on_connect(c, userdata, flags, reason_code, properties):
            if reason_code != 0:
                logger.error("MQTT broker rejected connection to %s:%s: %s", self.broker, self.port, reason_code)
                return
            c.subscribe("homeassistant/+/+/config")
            c.subscribe("homeassistant/+/+/+/config")
            with self._lock:
                filters = list(self._topic_handlers)
            for topic_filter in filters:
                c.subscribe(topic_filter)

        def on_message(c, userdata, msg):
            with self._lock:
                handlers = list(self._topic_handlers.items())
            for topic_filter, handler in handlers:
                try:
                    if mqtt.topic_matches_sub(topic_filter, msg.topic):
                        handler(c, userdata, msg)
                except Exception:
                    logger.exception("MQTT topic handler failed for %s", msg.topic)
            if not msg.topic.startswith("homeassistant/") or not msg.topic.endswith("/config"):
                return
            device = self._device_from_ha_message(msg.topic, msg.payload)
            if device is not None:
                self._emit(device)

        client.on_connect = on_connect
        client.on_message = on_message
        with self._lock:
            self._client = client
        try:
            client.connect(self.broker, self.port, 60)
            client.loop_forever(retry_first_connection=True)
        except Exception as exc:
            if not self._stop_event.is_set():
                logger.error("MQTT connect/loop error for %s:%s: %s", self.broker, self.port, exc)
        finally:
            with self._lock:
                if self._client is client:
                    self._client = None


_disc: Dict[tuple, MQTTDiscovery] = {}
_disc_lock = threading.RLock()


def start_mqtt_discovery(broker, port=1883, username=None, password=None, on_device=None):
    key = (str(broker), int(port), username or "")
    with _disc_lock:
        existing = _disc.get(key)
        if existing is not None and existing.is_running:
            if on_device is not None:
                existing.on_device = on_device
            return existing
        if existing is not None:
            _disc.pop(key, None)
        discovery = MQTTDiscovery(broker, port, username, password, on_device)
        _disc[key] = discovery
    discovery.start()
    return discovery


def stop_mqtt_discovery(broker, port=1883, username=None) -> bool:
    key = (str(broker), int(port), username or "")
    with _disc_lock:
        discovery = _disc.pop(key, None)
    return True if discovery is None else discovery.stop()
