"""
AgentPi shared data models.
All discovery modules return List[Device].
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid


@dataclass
class Device:
    """Canonical device record produced by every discovery scanner."""

    # ── identity ──────────────────────────────────────────────────────────
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    device_type: str = "host"          # smart_light | sensor | camera_ip | …

    # ── network ───────────────────────────────────────────────────────────
    address: Optional[str] = None       # IP or hostname
    mac: Optional[str] = None
    port: Optional[int] = None
    protocol: str = "unknown"           # arp | mdns | rtsp | homeassistant | …
    interface: Optional[str] = None

    # ── meta ──────────────────────────────────────────────────────────────
    manufacturer: Optional[str] = None
    online: bool = True
    properties: Dict[str, Any] = field(default_factory=dict)
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen:  datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ── helpers ───────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "name":        self.name,
            "device_type": self.device_type,
            "address":     self.address,
            "mac":         self.mac,
            "port":        self.port,
            "protocol":    self.protocol,
            "interface":   self.interface,
            "manufacturer":self.manufacturer,
            "online":      self.online,
            "properties":  self.properties,
            "first_seen":  self.first_seen.isoformat(),
            "last_seen":   self.last_seen.isoformat(),
        }

    @classmethod
    def error_device(cls, source: str, message: str) -> "Device":
        """Return a sentinel Device that records a discovery error."""
        return cls(
            id=str(uuid.uuid4()),
            name=f"[error:{source}]",
            device_type="error",
            protocol=source,
            online=False,
            properties={"error": message},
        )
