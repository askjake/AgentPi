"""
Zigbee2MQTT / Z-Wave JS Integration
Subscribes to MQTT bridge topics to discover and track Zigbee/Z-Wave devices.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from backend.models import Device

logger = logging.getLogger(__name__)

ZIGBEE_BRIDGE_DEVICES = "zigbee2mqtt/bridge/devices"
ZIGBEE_BRIDGE_STATE = "zigbee2mqtt/bridge/state"
ZIGBEE_DEVICE_WILDCARD = "zigbee2mqtt/+"
ZWAVE_BRIDGE_DEVICES = "zwavejs2mqtt/bridge/devices"

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


def _classify_zigbee(device_info: dict) -> str:
    """Determine AgentPi device_type from Zigbee2MQTT device info."""
    # Try definition category
    definition = device_info.get("definition") or {}
    description = (definition.get("description") or "").lower()
    model_id = (device_info.get("model_id") or "").lower()
    vendor = (device_info.get("vendor") or "").lower()
    ztype = device_info.get("type", "")

    # Check description / model for category keywords
    for kw, dtype in ZIGBEE_CATEGORY_MAP.items():
        if kw in description or kw in model_id:
            return dtype

    # Vendor hints
    if "philips" in vendor or "signify" in vendor:
        return "smart_light"
    if "ikea" in vendor and "bulb" in description:
        return "smart_light"
    if "aqara" in vendor or "xiaomi" in vendor:
        return "sensor"
    if "sonoff" in vendor:
        return "iot"
    if "tuya" in vendor or "zemismart" in vendor:
        return "iot"
    if "osram" in vendor or "ledvance" in vendor:
        return "smart_light"

    return ZIGBEE_TYPE_MAP.get(ztype, "iot")


def parse_zigbee_devices(payload: str) -> List[Device]:
    """Parse zigbee2mqtt/bridge/devices payload into Device list."""
    now = datetime.now(timezone.utc)
    devices = []
    try:
        items = json.loads(payload)
        if not isinstance(items, list):
            return []
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse Zigbee2MQTT devices: %s", exc)
        return []

    for item in items:
        ieee = item.get("ieee_address", "")
        if not ieee:
            continue
        friendly_name = item.get("friendly_name") or ieee
        dev_type = _classify_zigbee(item)
        definition = item.get("definition") or {}

        dev = Device(
            id=str(uuid.uuid5(uuid.NAMESPACE_OID, f"zigbee:{ieee}")),
            name=friendly_name,
            device_type=dev_type,
            address=None,
            port=None,
            protocol="zigbee",
            properties={
                "ieee_address": ieee,
                "network_address": item.get("network_address"),
                "type": item.get("type", ""),
                "vendor": item.get("vendor") or definition.get("vendor", ""),
                "model": item.get("model_id") or definition.get("model", ""),
                "description": definition.get("description", ""),
                "power_source": item.get("power_source", ""),
                "link_quality": item.get("link_quality"),
                "interviewing": item.get("interviewing", False),
                "interview_completed": item.get("interview_completed", False),
                "supported": item.get("supported", False),
                "source": "zigbee2mqtt",
            },
            online=not item.get("interviewing", False),
            first_seen=now,
            last_seen=now,
        )
        devices.append(dev)
        logger.info("Zigbee device: %s [%s] %s", ieee, dev_type, friendly_name)

    return devices


def parse_zwave_devices(payload: str) -> List[Device]:
    """Parse zwavejs2mqtt/bridge/devices payload into Device list."""
    now = datetime.now(timezone.utc)
    devices = []
    try:
        items = json.loads(payload)
        if not isinstance(items, list):
            return []
    except json.JSONDecodeError:
        return []

    for item in items:
        node_id = item.get("nodeId")
        if node_id is None:
            continue
        name = item.get("name") or item.get("productDescription") or f"Z-Wave Node {node_id}"
        product_type = (item.get("productType") or "").lower()

        dev_type = "iot"
        for kw, dtype in ZIGBEE_CATEGORY_MAP.items():
            if kw in product_type or kw in name.lower():
                dev_type = dtype
                break

        dev = Device(
            id=str(uuid.uuid5(uuid.NAMESPACE_OID, f"zwave:{item.get('id', node_id)}")),
            name=name,
            device_type=dev_type,
            address=None,
            port=None,
            protocol="zwave",
            properties={
                "node_id": node_id,
                "manufacturer": item.get("manufacturer", ""),
                "product_type": item.get("productType", ""),
                "product_description": item.get("productDescription", ""),
                "firmware_version": item.get("firmwareVersion", ""),
                "is_routing": item.get("isRouting", False),
                "is_secure": item.get("isSecure", False),
                "source": "zwavejs2mqtt",
            },
            online=item.get("ready", False),
            first_seen=now,
            last_seen=now,
        )
        devices.append(dev)
    return devices


class ZigbeeListener:
    """
    MQTT listener for Zigbee2MQTT and Z-Wave JS device discovery.
    Integrates with existing paho-mqtt client from backend/discovery/mqtt.py.
    """

    def __init__(self, on_devices: Callable[[List[Device]], None]):
        self.on_devices = on_devices
        self._client = None

    def attach(self, mqtt_client):
        """Attach to an existing paho MQTT client."""
        self._client = mqtt_client
        mqtt_client.subscribe(ZIGBEE_BRIDGE_DEVICES)
        mqtt_client.subscribe(ZIGBEE_BRIDGE_STATE)
        mqtt_client.subscribe(ZWAVE_BRIDGE_DEVICES)
        original_on_message = mqtt_client.on_message

        def _on_message(client, userdata, msg):
            topic = msg.topic
            payload = msg.payload.decode("utf-8", errors="ignore")
            if topic == ZIGBEE_BRIDGE_DEVICES:
                devs = parse_zigbee_devices(payload)
                if devs:
                    self.on_devices(devs)
            elif topic == ZWAVE_BRIDGE_DEVICES:
                devs = parse_zwave_devices(payload)
                if devs:
                    self.on_devices(devs)
            elif original_on_message:
                original_on_message(client, userdata, msg)

        mqtt_client.on_message = _on_message
        logger.info("ZigbeeListener attached to MQTT client")
