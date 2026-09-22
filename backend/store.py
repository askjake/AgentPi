from __future__ import annotations

import copy
import threading
from typing import Dict, Iterable, List, Optional

from backend.models import Device


class DeviceInventory:
    """Thread-safe in-memory inventory keyed by stable Device.id."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._devices: Dict[str, Device] = {}

    def upsert(self, device: Device) -> Device:
        incoming = copy.deepcopy(device)
        with self._lock:
            existing = self._devices.get(incoming.id)
            if existing is not None:
                incoming.first_seen = min(existing.first_seen, incoming.first_seen)
                incoming.last_seen = max(existing.last_seen, incoming.last_seen)
            self._devices[incoming.id] = incoming
            return copy.deepcopy(incoming)

    def upsert_many(self, devices: Iterable[Device]) -> List[Device]:
        return [self.upsert(device) for device in devices]

    def list(
        self,
        *,
        protocol: Optional[str] = None,
        device_type: Optional[str] = None,
        online: Optional[bool] = None,
    ) -> List[Device]:
        with self._lock:
            items = [copy.deepcopy(device) for device in self._devices.values()]
        if protocol:
            protocol_l = protocol.lower()
            items = [d for d in items if d.protocol.lower() == protocol_l]
        if device_type:
            type_l = device_type.lower()
            items = [d for d in items if d.device_type.lower() == type_l]
        if online is not None:
            items = [d for d in items if d.online is online]
        items.sort(key=lambda d: (d.protocol, d.name.lower(), d.id))
        return items

    def clear(self) -> int:
        with self._lock:
            count = len(self._devices)
            self._devices.clear()
            return count

    def count(self) -> int:
        with self._lock:
            return len(self._devices)

    def summary(self) -> dict:
        devices = self.list()
        protocols: Dict[str, int] = {}
        types: Dict[str, int] = {}
        online = 0
        for device in devices:
            protocols[device.protocol] = protocols.get(device.protocol, 0) + 1
            types[device.device_type] = types.get(device.device_type, 0) + 1
            online += int(device.online)
        return {
            "total": len(devices),
            "online": online,
            "offline": len(devices) - online,
            "protocols": protocols,
            "types": types,
        }
