"""
Zigbee2MQTT / Z-Wave MQTT parsing and listener integration.
"""
from __future__ import annotations

import copy
import json
import logging
from typing import Callable, Dict, List, Optional

from backend.models import Device, stable_device_id, utcnow

logger = logging.getLogger(__name__)

DEFAULT_ZIGBEE_BASE_TOPIC = "zigbee2mqtt"
DEFAULT_ZWAVE_BRIDGE_DEVICES = "zwavejs2mqtt/bridge/devices"

ZIGBEE_TYPE_MAP = {
    "EndDevice": "sensor",
    "Router": "iot",
    "Coordinator": "iot",
    "GreenPower": "sensor",
}

ZIGBEE_CATEGORY_MAP = {
    "light": "smart_light",
    "switch": "smart_plug",
    "sensor": "sensor",
    "cover": "iot",
    "lock": "iot",
    "climate": "thermostat",
    "fan": "iot",
    "remote": "sensor",
    "button": "sensor",
    "plug": "smart_plug",
    "outlet": "smart_plug",
    "bulb": "smart_light",
    "strip": "smart_light",
    "controller": "iot",
    "thermostat": "thermostat",
    "motion": "sensor",
    "contact": "sensor",
    "temperature": "sensor",
    "humidity": "sensor",
    "smoke": "sensor",
    "water": "sensor",
    "vibration": "sensor",
    "door": "sensor",
    "window": "sensor",
    "presence": "sensor",
    "occupancy": "sensor",
}


def _expose_words(exposes) -> str:
    words: List[str] = []
    if not isinstance(exposes, list):
        return ""
    stack = list(exposes)
    while stack:
        item = stack.pop()
        if not isinstance(item, dict):
            continue
        for key in ("type", "name", "property"):
            value = item.get(key)
            if isinstance(value, str):
                words.append(value.lower())
        features = item.get("features")
        if isinstance(features, list):
            stack.extend(features)
    return " ".join(words)


def _classify_zigbee(device_info: dict) -> str:
    if not isinstance(device_info, dict):
        return "iot"
    definition = device_info.get("definition") or {}
    if not isinstance(definition, dict):
        definition = {}
    description = str(definition.get("description") or device_info.get("description") or "").lower()
    model_id = str(device_info.get("model_id") or definition.get("model") or "").lower()
    vendor = str(definition.get("vendor") or device_info.get("vendor") or "").lower()
    ztype = str(device_info.get("type") or "")
    haystack = " ".join((description, model_id, _expose_words(definition.get("exposes"))))

    for keyword, device_type in ZIGBEE_CATEGORY_MAP.items():
        if keyword in haystack:
            return device_type

    if "philips" in vendor or "signify" in vendor:
        return "smart_light"
    if "ikea" in vendor and any(k in haystack for k in ("light", "bulb")):
        return "smart_light"
    if "aqara" in vendor or "xiaomi" in vendor:
        return "sensor"
    if any(v in vendor for v in ("sonoff", "tuya", "zemismart")):
        return "iot"
    if "osram" in vendor or "ledvance" in vendor:
        return "smart_light"
    return ZIGBEE_TYPE_MAP.get(ztype, "iot")


def parse_zigbee_devices(payload: str) -> List[Device]:
    now = utcnow()
    try:
        items = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        logger.error("Failed to parse Zigbee2MQTT devices: %s", exc)
        return []
    if not isinstance(items, list):
        return []

    devices: List[Device] = []
    for item in items:
        if not isinstance(item, dict):
            logger.warning("Ignoring non-object Zigbee2MQTT device entry")
            continue
        ieee = str(item.get("ieee_address") or "")
        if not ieee:
            continue
        definition = item.get("definition") or {}
        if not isinstance(definition, dict):
            definition = {}
        friendly_name = str(item.get("friendly_name") or ieee)
        interview_state = str(item.get("interview_state") or "").upper()
        interviewing = item.get("interviewing", False)
        disabled = bool(item.get("disabled", False))
        if interview_state:
            ready = interview_state == "SUCCESSFUL"
        else:
            ready = not bool(interviewing)

        vendor = str(definition.get("vendor") or item.get("vendor") or "")
        model = str(item.get("model_id") or definition.get("model") or "")
        devices.append(Device(
            id=stable_device_id("zigbee", ieee),
            name=friendly_name,
            device_type=_classify_zigbee(item),
            protocol="zigbee",
            manufacturer=vendor or None,
            properties={
                "ieee_address": ieee,
                "network_address": item.get("network_address"),
                "type": item.get("type", ""),
                "vendor": vendor,
                "model": model,
                "description": definition.get("description", ""),
                "power_source": item.get("power_source", ""),
                "interview_state": interview_state or None,
                "supported": item.get("supported", False),
                "disabled": disabled,
                "source": "zigbee2mqtt",
                "availability": "unknown",
            },
            online=ready and not disabled,
            first_seen=now,
            last_seen=now,
        ))
    return devices


def parse_zwave_devices(payload: str) -> List[Device]:
    now = utcnow()
    try:
        items = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(items, list):
        return []

    devices: List[Device] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        node_id = item.get("nodeId")
        if node_id is None:
            continue
        name = str(item.get("name") or item.get("productDescription") or f"Z-Wave Node {node_id}")
        product_type = str(item.get("productType") or "").lower()
        device_type = "iot"
        for keyword, mapped in ZIGBEE_CATEGORY_MAP.items():
            if keyword in product_type or keyword in name.lower():
                device_type = mapped
                break
        manufacturer = str(item.get("manufacturer") or "")
        devices.append(Device(
            id=stable_device_id("zwave", item.get("id", node_id)),
            name=name,
            device_type=device_type,
            protocol="zwave",
            manufacturer=manufacturer or None,
            properties={
                "node_id": node_id,
                "manufacturer": manufacturer,
                "product_type": item.get("productType", ""),
                "product_description": item.get("productDescription", ""),
                "firmware_version": item.get("firmwareVersion", ""),
                "is_routing": item.get("isRouting", False),
                "is_secure": item.get("isSecure", False),
                "source": "zwavejs2mqtt",
            },
            online=bool(item.get("ready", False)),
            first_seen=now,
            last_seen=now,
        ))
    return devices


class ZigbeeListener:
    """Compose Zigbee2MQTT discovery with MQTTDiscovery without replacing callbacks."""

    def __init__(
        self,
        on_devices: Callable[[List[Device]], None],
        base_topic: str = DEFAULT_ZIGBEE_BASE_TOPIC,
        zwave_bridge_devices: str = DEFAULT_ZWAVE_BRIDGE_DEVICES,
    ):
        self.on_devices = on_devices
        self.base_topic = base_topic.rstrip("/")
        self.zwave_bridge_devices = zwave_bridge_devices
        self._mqtt_discovery = None
        self._devices_by_name: Dict[str, Device] = {}

    @property
    def zigbee_bridge_devices(self) -> str:
        return f"{self.base_topic}/bridge/devices"

    @property
    def zigbee_bridge_state(self) -> str:
        return f"{self.base_topic}/bridge/state"

    @property
    def zigbee_availability(self) -> str:
        return f"{self.base_topic}/+/availability"

    def _emit(self, devices: List[Device]) -> None:
        if not devices:
            return
        try:
            self.on_devices(devices)
        except Exception:
            logger.exception("Zigbee listener callback failed")

    def _handle(self, client, userdata, msg) -> None:
        try:
            payload = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("Ignoring non-UTF8 Zigbee MQTT payload on %s", msg.topic)
            return

        if msg.topic == self.zigbee_bridge_devices:
            devices = parse_zigbee_devices(payload)
            for device in devices:
                self._devices_by_name[device.name] = device
            self._emit(devices)
            return

        if msg.topic == self.zwave_bridge_devices:
            self._emit(parse_zwave_devices(payload))
            return

        prefix = self.base_topic + "/"
        suffix = "/availability"
        if msg.topic.startswith(prefix) and msg.topic.endswith(suffix):
            friendly_name = msg.topic[len(prefix):-len(suffix)]
            existing = self._devices_by_name.get(friendly_name)
            if existing is None:
                return
            try:
                availability = json.loads(payload)
                state = availability.get("state") if isinstance(availability, dict) else None
            except json.JSONDecodeError:
                state = payload.strip()
            if state not in {"online", "offline"}:
                return
            updated = copy.deepcopy(existing)
            updated.online = state == "online"
            updated.last_seen = utcnow()
            updated.properties["availability"] = state
            self._devices_by_name[friendly_name] = updated
            self._emit([updated])

    def attach(self, mqtt_discovery) -> None:
        if not hasattr(mqtt_discovery, "add_topic_handler"):
            raise TypeError("ZigbeeListener.attach expects MQTTDiscovery-compatible add_topic_handler()")
        self._mqtt_discovery = mqtt_discovery
        for topic_filter in (
            self.zigbee_bridge_devices,
            self.zigbee_bridge_state,
            self.zigbee_availability,
            self.zwave_bridge_devices,
        ):
            mqtt_discovery.add_topic_handler(topic_filter, self._handle)
        logger.info("ZigbeeListener attached using base topic %s", self.base_topic)

    def detach(self) -> None:
        discovery = self._mqtt_discovery
        if discovery is None:
            return
        for topic_filter in (
            self.zigbee_bridge_devices,
            self.zigbee_bridge_state,
            self.zigbee_availability,
            self.zwave_bridge_devices,
        ):
            discovery.remove_topic_handler(topic_filter)
        self._mqtt_discovery = None
