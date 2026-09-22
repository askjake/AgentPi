"""
RTSP / IP Camera Discovery
Scans common RTSP ports, probes paths, generates thumbnails via ffmpeg.
"""
import asyncio
import ipaddress
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from backend.models import Device

logger = logging.getLogger(__name__)

RTSP_PORTS = [554, 8554, 10554]
RTSP_PATHS = [
    "/",
    "/stream",
    "/live",
    "/live/ch00_0",
    "/cam/realmonitor",
    "/h264",
    "/h264Preview_01_main",
    "/video1",
    "/video2",
    "/mpeg4",
    "/mpeg4/media.amp",
    "/axis-media/media.amp",
    "/MediaInput/h264",
    "/Streaming/Channels/1",
    "/Streaming/Channels/101",
    "/onvif/device_service",
]
THUMB_DIR = "/tmp/agentpi_thumbs"
FFPROBE_TIMEOUT = 8  # seconds
FFMPEG_THUMB_TIMEOUT = 15


os.makedirs(THUMB_DIR, exist_ok=True)


async def _tcp_connect(ip: str, port: int, timeout: float = 2.0) -> bool:
    """Quick TCP port check."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def _ffprobe_stream(rtsp_url: str) -> Optional[dict]:
    """Run ffprobe on an RTSP URL, return stream info JSON or None."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-rtsp_transport", "tcp",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        rtsp_url,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=FFPROBE_TIMEOUT
        )
        if proc.returncode == 0:
            return json.loads(stdout.decode())
    except asyncio.TimeoutError:
        logger.debug("ffprobe timeout: %s", rtsp_url)
    except Exception as exc:
        logger.debug("ffprobe error for %s: %s", rtsp_url, exc)
    return None


async def generate_thumbnail(device_id: str, rtsp_url: str) -> Optional[str]:
    """Generate a JPEG thumbnail from an RTSP stream using ffmpeg."""
    thumb_path = os.path.join(THUMB_DIR, f"thumb_{device_id}.jpg")
    cmd = [
        "ffmpeg",
        "-y",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-frames:v", "1",
        "-q:v", "2",
        thumb_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=FFMPEG_THUMB_TIMEOUT)
        if os.path.exists(thumb_path):
            return thumb_path
    except Exception as exc:
        logger.debug("ffmpeg thumbnail error for %s: %s", rtsp_url, exc)
    return None


async def _probe_host(ip: str) -> Optional[Device]:
    """Try all RTSP ports/paths on a host, return Device if found."""
    now = datetime.now(timezone.utc)
    for port in RTSP_PORTS:
        if not await _tcp_connect(ip, port):
            continue
        logger.info("RTSP port %d open on %s — probing paths...", port, ip)
        for path in RTSP_PATHS:
            rtsp_url = f"rtsp://{ip}:{port}{path}"
            stream_info = await _ffprobe_stream(rtsp_url)
            if stream_info:
                streams = stream_info.get("streams", [])
                video_streams = [s for s in streams if s.get("codec_type") == "video"]
                codec = video_streams[0].get("codec_name", "unknown") if video_streams else "unknown"
                width = video_streams[0].get("width", 0) if video_streams else 0
                height = video_streams[0].get("height", 0) if video_streams else 0

                dev_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"rtsp:{ip}:{port}{path}"))

                # Generate thumbnail asynchronously (best-effort)
                thumb_path = await generate_thumbnail(dev_id, rtsp_url)

                dev = Device(
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
                logger.info("RTSP camera found: %s %s (%s %dx%d)", ip, path, codec, width, height)
                return dev
    return None


async def scan_rtsp(cidr: str, concurrency: int = 20) -> List[Device]:
    """Scan a CIDR range for RTSP cameras."""
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        logger.error("Invalid CIDR: %s — %s", cidr, exc)
        return []

    hosts = list(network.hosts())
    logger.info("Scanning %d hosts for RTSP cameras...", len(hosts))

    semaphore = asyncio.Semaphore(concurrency)
    devices = []

    async def _bounded(ip):
        async with semaphore:
            return await _probe_host(str(ip))

    results = await asyncio.gather(*[_bounded(ip) for ip in hosts], return_exceptions=True)
    for r in results:
        if isinstance(r, Device):
            devices.append(r)

    logger.info("RTSP scan complete: %d cameras found", len(devices))
    return devices
