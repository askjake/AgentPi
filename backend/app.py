from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr

from backend.discovery.arp import scan_arp
from backend.discovery.mdns import discover_mdns_devices_async
from backend.discovery.rtsp import scan_rtsp
from backend.models import Device
from backend.runtime import RuntimeManager
from backend.store import DeviceInventory


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class ScanRequest(BaseModel):
    arp: bool = True
    mdns: bool = True
    mdns_timeout: float = Field(default=2.0, ge=0.0, le=15.0)
    lookup_vendors: bool = False
    rtsp_cidr: Optional[str] = None
    rtsp_concurrency: int = Field(default=12, ge=1, le=64)
    rtsp_max_hosts: int = Field(default=64, ge=1, le=256)


class MQTTStartRequest(BaseModel):
    broker: str = Field(min_length=1)
    port: int = Field(default=1883, ge=1, le=65535)
    username: Optional[str] = None
    password: Optional[SecretStr] = None
    zigbee_base_topic: str = Field(default="zigbee2mqtt", min_length=1)


class MQTTStopRequest(BaseModel):
    broker: str = Field(min_length=1)
    port: int = Field(default=1883, ge=1, le=65535)
    username: Optional[str] = None


class HomeAssistantStartRequest(BaseModel):
    url: str = Field(min_length=1)
    token: SecretStr
    subscribe: bool = True


def _device_dicts(devices):
    return [device.to_dict() for device in devices]


def create_app() -> FastAPI:
    inventory = DeviceInventory()
    runtime = RuntimeManager(inventory)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await runtime.shutdown()

    app = FastAPI(
        title="AgentPi",
        version="0.1.0-r1r2",
        lifespan=lifespan,
    )
    app.state.inventory = inventory
    app.state.runtime = runtime

    if FRONTEND.is_dir():
        app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

    @app.get("/", include_in_schema=False)
    async def dashboard():
        index = FRONTEND / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="frontend/index.html is missing")
        return FileResponse(index)

    @app.get("/rest/api/v1/health")
    async def health():
        return {
            "status": "ok",
            "service": "agentpi",
            "version": app.version,
            "inventory": inventory.summary(),
            "runtime": runtime.status(),
        }

    @app.get("/rest/api/v1/devices")
    async def devices(
        protocol: Optional[str] = Query(default=None),
        device_type: Optional[str] = Query(default=None),
        online: Optional[bool] = Query(default=None),
    ):
        items = inventory.list(protocol=protocol, device_type=device_type, online=online)
        return {"count": len(items), "devices": _device_dicts(items)}

    @app.delete("/rest/api/v1/devices")
    async def clear_devices():
        return {"cleared": inventory.clear()}

    @app.post("/rest/api/v1/discovery/scan")
    async def discovery_scan(request: ScanRequest):
        jobs = []
        labels = []
        if request.arp:
            jobs.append(scan_arp(lookup_vendors=request.lookup_vendors))
            labels.append("arp")
        if request.mdns:
            jobs.append(discover_mdns_devices_async(timeout=request.mdns_timeout))
            labels.append("mdns")
        if request.rtsp_cidr:
            jobs.append(scan_rtsp(
                request.rtsp_cidr,
                concurrency=request.rtsp_concurrency,
                max_hosts=request.rtsp_max_hosts,
            ))
            labels.append("rtsp")

        results = await asyncio.gather(*jobs, return_exceptions=True)
        discovered = []
        errors = []
        for label, result in zip(labels, results):
            if isinstance(result, Exception):
                errors.append({"source": label, "error": str(result)})
                continue
            for device in result:
                if isinstance(device, Device) and device.device_type == "error":
                    errors.append({
                        "source": label,
                        "error": device.properties.get("error", "unknown discovery error"),
                    })
                    continue
                if isinstance(device, Device):
                    discovered.append(device)

        inventory.upsert_many(discovered)
        return {
            "sources": labels,
            "discovered": len(discovered),
            "errors": errors,
            "inventory": inventory.summary(),
            "devices": _device_dicts(discovered),
        }

    @app.post("/rest/api/v1/mqtt/start")
    async def mqtt_start(request: MQTTStartRequest):
        try:
            return runtime.start_mqtt(
                broker=request.broker,
                port=request.port,
                username=request.username,
                password=request.password.get_secret_value() if request.password else None,
                zigbee_base_topic=request.zigbee_base_topic,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MQTT start failed: {exc}") from exc

    @app.post("/rest/api/v1/mqtt/stop")
    async def mqtt_stop(request: MQTTStopRequest):
        stopped = await asyncio.to_thread(
            runtime.stop_mqtt,
            broker=request.broker,
            port=request.port,
            username=request.username,
        )
        return {"stopped": stopped}

    @app.post("/rest/api/v1/homeassistant/start")
    async def homeassistant_start(request: HomeAssistantStartRequest):
        try:
            return await runtime.start_homeassistant(
                url=request.url,
                token=request.token.get_secret_value(),
                subscribe=request.subscribe,
            )
        except ConnectionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Home Assistant start failed: {exc}") from exc

    @app.post("/rest/api/v1/homeassistant/stop")
    async def homeassistant_stop():
        return {"stopped": runtime.stop_homeassistant()}

    @app.get("/rest/api/v1/runtime")
    async def runtime_status():
        return runtime.status()

    return app


app = create_app()
