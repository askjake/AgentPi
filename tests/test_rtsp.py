import asyncio
import pytest
from backend.discovery import rtsp


@pytest.mark.asyncio
async def test_invalid_concurrency_is_error_not_deadlock():
    d=(await rtsp.scan_rtsp("127.0.0.1/32",concurrency=0))[0]
    assert d.device_type == "error"
    assert "concurrency" in d.properties["error"]


@pytest.mark.asyncio
async def test_large_cidr_rejected_before_iteration():
    d=(await rtsp.scan_rtsp("10.0.0.0/8"))[0]
    assert d.device_type == "error"
    assert "too large" in d.properties["error"]


@pytest.mark.asyncio
async def test_small_scan(monkeypatch):
    async def probe(ip): return None
    monkeypatch.setattr(rtsp,"_probe_host",probe)
    assert await rtsp.scan_rtsp("192.0.2.0/30", concurrency=2) == []


@pytest.mark.asyncio
async def test_terminate_process_kills_and_reaps():
    class Proc:
        returncode=None
        def __init__(self): self.killed=False; self.waited=False
        def kill(self): self.killed=True; self.returncode=-9
        async def wait(self): self.waited=True; return -9
    p=Proc(); await rtsp._terminate_process(p)
    assert p.killed and p.waited

@pytest.mark.asyncio
async def test_probe_host_uses_stable_identity(monkeypatch):
    async def yes(ip,port,timeout=2): return port == rtsp.RTSP_PORTS[0]
    async def info(url): return {"streams":[{"codec_type":"video","codec_name":"h264","width":640,"height":480}]}
    async def thumb(i,u): return None
    monkeypatch.setattr(rtsp,"_tcp_connect",yes)
    monkeypatch.setattr(rtsp,"_ffprobe_stream",info)
    monkeypatch.setattr(rtsp,"generate_thumbnail",thumb)
    one=await rtsp._probe_host("192.0.2.5")
    two=await rtsp._probe_host("192.0.2.5")
    assert one.id == two.id
    assert one.properties["resolution"] == "640x480"
