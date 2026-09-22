"""Bounded RTSP/IP camera discovery."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import shutil
from typing import List, Optional

from backend.models import Device, stable_device_id, utcnow

logger = logging.getLogger(__name__)

RTSP_PORTS = [554, 8554, 10554]
RTSP_PATHS = [
    "/", "/stream", "/live", "/live/ch00_0", "/cam/realmonitor",
    "/h264", "/h264Preview_01_main", "/video1", "/video2", "/mpeg4",
    "/mpeg4/media.amp", "/axis-media/media.amp", "/MediaInput/h264",
    "/Streaming/Channels/1", "/Streaming/Channels/101", "/onvif/device_service",
]
THUMB_DIR = os.path.join(os.environ.get("TEMP", "/tmp"), "agentpi_thumbs")
FFPROBE_TIMEOUT = 8
FFMPEG_THUMB_TIMEOUT = 15
DEFAULT_MAX_HOSTS = 4096


async def _terminate_process(proc) -> None:
    try:
        if getattr(proc, "returncode", None) is None:
            proc.kill()
    except ProcessLookupError:
        pass
    except Exception:
        logger.debug("Failed to kill subprocess", exc_info=True)
    try:
        await proc.wait()
    except Exception:
        logger.debug("Failed to reap subprocess", exc_info=True)


async def _tcp_connect(ip: str, port: int, timeout: float = 2.0) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def _ffprobe_stream(rtsp_url: str) -> Optional[dict]:
    if shutil.which("ffprobe") is None:
        logger.debug("ffprobe not installed")
        return None
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-rtsp_transport", "tcp",
            "-print_format", "json", "-show_streams", "-show_format", rtsp_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=FFPROBE_TIMEOUT)
        if proc.returncode != 0:
            return None
        payload = json.loads(stdout.decode(errors="replace"))
        return payload if isinstance(payload, dict) else None
    except asyncio.TimeoutError:
        logger.debug("ffprobe timeout: %s", rtsp_url)
        if proc is not None:
            await _terminate_process(proc)
    except Exception as exc:
        logger.debug("ffprobe error for %s: %s", rtsp_url, exc)
        if proc is not None and getattr(proc, "returncode", None) is None:
            await _terminate_process(proc)
    return None


async def generate_thumbnail(device_id: str, rtsp_url: str) -> Optional[str]:
    if shutil.which("ffmpeg") is None:
        return None
    os.makedirs(THUMB_DIR, exist_ok=True)
    thumb_path = os.path.join(THUMB_DIR, f"thumb_{device_id}.jpg")
    try:
        os.unlink(thumb_path)
    except FileNotFoundError:
        pass
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-rtsp_transport", "tcp", "-i", rtsp_url,
            "-frames:v", "1", "-q:v", "2", thumb_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=FFMPEG_THUMB_TIMEOUT)
        if proc.returncode == 0 and os.path.isfile(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path
    except asyncio.TimeoutError:
        logger.debug("ffmpeg thumbnail timeout for %s", rtsp_url)
        if proc is not None:
            await _terminate_process(proc)
    except Exception as exc:
        logger.debug("ffmpeg thumbnail error for %s: %s", rtsp_url, exc)
        if proc is not None and getattr(proc, "returncode", None) is None:
            await _terminate_process(proc)
    return None


async def _probe_host(ip: str) -> Optional[Device]:
    now = utcnow()
    for port in RTSP_PORTS:
        if not await _tcp_connect(ip, port):
            continue
        for path in RTSP_PATHS:
            rtsp_url = f"rtsp://{ip}:{port}{path}"
            stream_info = await _ffprobe_stream(rtsp_url)
            if not stream_info:
                continue
            streams = stream_info.get("streams", [])
            if not isinstance(streams, list):
                streams = []
            video_streams = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"]
            video = video_streams[0] if video_streams else {}
            codec = video.get("codec_name", "unknown")
            width = video.get("width", 0)
            height = video.get("height", 0)
            dev_id = stable_device_id("rtsp", ip, port, path)
            thumb_path = await generate_thumbnail(dev_id, rtsp_url)
            return Device(
                id=dev_id,
                name=f"IP Camera @ {ip}:{port}",
                device_type="camera_ip",
                address=ip,
                port=port,
                protocol="rtsp",
                properties={
                    "rtsp_url": rtsp_url,
                    "rtsp_path": path,
                    "codec": codec,
                    "resolution": f"{width}x{height}" if width else "unknown",
                    "stream_count": len(streams),
                    "thumbnail": thumb_path or "",
                    "ffprobe": stream_info,
                },
                online=True,
                first_seen=now,
                last_seen=now,
            )
    return None


def _host_count_upper_bound(network) -> int:
    # Conservative bound sufficient to reject huge CIDRs before iteration.
    return int(network.num_addresses)


async def scan_rtsp(cidr: str, concurrency: int = 20, max_hosts: int = DEFAULT_MAX_HOSTS) -> List[Device]:
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        return [Device.error_device("rtsp", f"invalid CIDR {cidr!r}: {exc}")]
    if concurrency < 1 or concurrency > 256:
        return [Device.error_device("rtsp", "concurrency must be between 1 and 256")]
    if max_hosts < 1:
        return [Device.error_device("rtsp", "max_hosts must be >= 1")]
    if _host_count_upper_bound(network) > max_hosts + 2:
        return [Device.error_device(
            "rtsp",
            f"CIDR too large: {network.num_addresses} addresses exceeds max_hosts={max_hosts}",
        )]

    semaphore = asyncio.Semaphore(concurrency)

    async def bounded(ip):
        async with semaphore:
            return await _probe_host(str(ip))

    tasks = [asyncio.create_task(bounded(ip)) for ip in network.hosts()]
    if not tasks:
        return []
    results = await asyncio.gather(*tasks, return_exceptions=True)
    devices: List[Device] = []
    for result in results:
        if isinstance(result, Device):
            devices.append(result)
        elif isinstance(result, Exception):
            logger.warning("RTSP host probe failed: %s", result)
    return devices
