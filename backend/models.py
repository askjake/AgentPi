"""
AgentPi shared data models.
All discovery modules return List[Device].
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid


def utcnow() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


def stable_device_id(protocol: str, *identity_parts: object) -> str:
    """Create a stable UUID for the same observed device identity."""
    normalized = [protocol.strip().lower()]
    normalized.extend(str(part).strip().lower() for part in identity_parts if part is not None)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "agentpi:" + ":".join(normalized)))


@dataclass
class Device:
    """Canonical device record produced by every discovery scanner."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    device_type: str = "host"

    address: Optional[str] = None
    mac: Optional[str] = None
    port: Optional[int] = None
    protocol: str = "unknown"
    interface: Optional[str] = None

    manufacturer: Optional[str] = None
    online: bool = True
    properties: Dict[str, Any] = field(default_factory=dict)
    first_seen: datetime = field(default_factory=utcnow)
    last_seen: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "device_type": self.device_type,
            "address": self.address,
            "mac": self.mac,
            "port": self.port,
            "protocol": self.protocol,
            "interface": self.interface,
            "manufacturer": self.manufacturer,
            "online": self.online,
            "properties": self.properties,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
        }

    @classmethod
    def error_device(cls, source: str, message: str) -> "Device":
        """Return a sentinel Device that records a discovery error."""
        now = utcnow()
        return cls(
            id=stable_device_id("error", source, message),
            name=f"[error:{source}]",
            device_type="error",
            protocol=source,
            online=False,
            properties={"error": message},
            first_seen=now,
            last_seen=now,
        )
