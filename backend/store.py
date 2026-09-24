from __future__ import annotations
import copy, json, os, sqlite3, threading, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from backend.models import Device

def _db_path() -> Path:
    return Path(os.environ.get("AGENTPI_DB", "/var/lib/agentpi/devices.db"))

def _to_row(d: Device) -> tuple:
    return (d.id, json.dumps(d.to_dict()), time.time())

def _from_row(row) -> Device:
    data = json.loads(row["data"] if hasattr(row, "keys") else row[1])
    ts = lambda k: datetime.fromisoformat(data[k]) if data.get(k) else datetime.now(timezone.utc)
    return Device(
        id=data["id"], name=data.get("name", ""), device_type=data.get("device_type", "host"),
        address=data.get("address"), mac=data.get("mac"), port=data.get("port"),
        protocol=data.get("protocol", "unknown"), interface=data.get("interface"),
        manufacturer=data.get("manufacturer"), online=bool(data.get("online", True)),
        properties=data.get("properties", {}),
        first_seen=ts("first_seen"), last_seen=ts("last_seen"),
    )

class DeviceInventory:
    """SQLite-backed device inventory (PATCH-08).
    Drop-in replacement for the previous in-memory dict.
    Persists across reboots. DB path: AGENTPI_DB env var
    (default /var/lib/agentpi/devices.db).
    """
    def __init__(self) -> None:
        p = _db_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(p)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init()

    def _cn(self) -> sqlite3.Connection:
        if not self._conn:
            c = sqlite3.connect(self._path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            self._conn = c
        return self._conn

    def _init(self) -> None:
        with self._lock:
            c = self._cn()
            c.execute("""CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at REAL NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_u ON devices(updated_at)")
            c.commit()

    def upsert(self, device: Device) -> Device:
        d = copy.deepcopy(device)
        with self._lock:
            c = self._cn()
            row = c.execute("SELECT data FROM devices WHERE id=?", (d.id,)).fetchone()
            if row:
                ex = _from_row(row)
                d.first_seen = min(ex.first_seen, d.first_seen)
                d.last_seen = max(ex.last_seen, d.last_seen)
            c.execute("INSERT OR REPLACE INTO devices(id,data,updated_at) VALUES(?,?,?)", _to_row(d))
            c.commit()
        return copy.deepcopy(d)

    def upsert_many(self, devices: Iterable[Device]) -> List[Device]:
        dl = list(devices)
        if not dl:
            return []
        with self._lock:
            c = self._cn()
            results = []
            for device in dl:
                d = copy.deepcopy(device)
                row = c.execute("SELECT data FROM devices WHERE id=?", (d.id,)).fetchone()
                if row:
                    ex = _from_row(row)
                    d.first_seen = min(ex.first_seen, d.first_seen)
                    d.last_seen = max(ex.last_seen, d.last_seen)
                c.execute("INSERT OR REPLACE INTO devices(id,data,updated_at) VALUES(?,?,?)", _to_row(d))
                results.append(copy.deepcopy(d))
            c.commit()
        return results

    def list(self, *, protocol=None, device_type=None, online=None) -> List[Device]:
        with self._lock:
            rows = self._cn().execute("SELECT data FROM devices").fetchall()
        items = [_from_row(r) for r in rows]
        if protocol:     items = [d for d in items if d.protocol.lower()    == protocol.lower()]
        if device_type:  items = [d for d in items if d.device_type.lower() == device_type.lower()]
        if online is not None: items = [d for d in items if d.online is online]
        items.sort(key=lambda d: (d.protocol, d.name.lower(), d.id))
        return items

    def clear(self) -> int:
        with self._lock:
            c = self._cn()
            n = c.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
            c.execute("DELETE FROM devices")
            c.commit()
        return n

    def count(self) -> int:
        with self._lock:
            return self._cn().execute("SELECT COUNT(*) FROM devices").fetchone()[0]

    def summary(self) -> dict:
        devs = self.list()
        protocols: Dict[str, int] = {}
        types: Dict[str, int] = {}
        n_on = 0
        for d in devs:
            protocols[d.protocol] = protocols.get(d.protocol, 0) + 1
            types[d.device_type]  = types.get(d.device_type, 0)  + 1
            n_on += int(d.online)
        return {"total": len(devs), "online": n_on, "offline": len(devs) - n_on,
                "protocols": protocols, "types": types}

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
