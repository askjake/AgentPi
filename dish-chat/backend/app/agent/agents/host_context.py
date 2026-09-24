from __future__ import annotations
import os, shutil, subprocess, time
from pathlib import Path
from typing import Iterable, Optional, Tuple

# PATCH-07: 60-second TTL cache replaces @lru_cache(maxsize=1)
_TTL: float = 60.0
_CACHE: Optional[Tuple[float, str]] = None

def _run(cmd: list) -> str:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        return (cp.stdout or cp.stderr or "").strip()
    except Exception:
        return ""

def _any(paths: Iterable[str]) -> list:
    return [p for p in paths if Path(p).exists()]

def _inner() -> str:
    f: list = []
    pv = Path("/proc/version").read_text(errors="ignore") if Path("/proc/version").exists() else ""
    wsl = "microsoft" in pv.lower() or bool(os.getenv("WSL_DISTRO_NAME")) or Path("/mnt/c/Windows").exists()
    if wsl:
        f += [
            "You are running inside WSL on a Windows host.",
            "Linux shell commands run inside WSL; Windows files are under /mnt/c, /mnt/d etc.",
            "Windows commands may be reachable via powershell.exe or cmd.exe.",
        ]
    else:
        f.append("You are running on a Linux-like host environment with shell access.")
    for b, m in [
        ("powershell.exe", "powershell.exe is available."),
        ("cmd.exe",        "cmd.exe is available."),
        ("ffmpeg",         "ffmpeg is installed (useful for capture/inspection)."),
        ("v4l2-ctl",       "v4l2-ctl is installed (inspects V4L2 video devices)."),
    ]:
        if shutil.which(b):
            f.append(m)
    mts = _any(["/mnt/c/Users", "/mnt/c/Windows", "/mnt/c/Program Files"])
    if mts:
        f.append(f"Detected Windows mount points: {', '.join(mts)}")
    vids = sorted(str(p) for p in Path("/dev").glob("video*"))
    if vids:
        f.append(f"Detected Linux video device nodes: {', '.join(vids[:8])}")
    lu = _run(["bash", "-lc",
               "lsusb 2>/dev/null | egrep -i 'magewell|camera|video|capture|hdmi' | head -n 20"])
    if lu:
        f.append("USB/video devices detected by lsusb:")
        f.append(lu)
    f.append("For host files, processes, cameras, peripherals, bash → prefer agent_run_shell.")
    f.append("For current facts → prefer public_web_search; retry before giving up.")

    # PATCH-01: self-identity facts
    url = os.environ.get("AGENTPI_URL", "http://127.0.0.1:8765")
    f.append(
        f"IMPORTANT: The AgentPi discovery/device service runs on THIS MACHINE at {url}. "
        "Tools agentpi_health, agentpi_discover_devices, agentpi_list_devices, agentpi_scan_rtsp, "
        "agentpi_runtime_status, agentpi_mqtt_start, agentpi_mqtt_stop, "
        "agentpi_homeassistant_start, agentpi_homeassistant_stop, and agentpi_clear_inventory "
        "all call localhost directly. "
        "Do NOT ping 'agentpi', 'agentpi.local', or any hostname to check AgentPi health — "
        "call agentpi_health instead."
    )
    f.append(
        "This process IS the Dish-Chat/Dish-Agent backend running ON the Raspberry Pi. "
        "No SSH needed for agentpi_* operations."
    )
    return "\n".join(f"- {x}" for x in f if x)

def build_host_context() -> str:
    """Return host environment string. Cached for 60 s (PATCH-07).
    Replaces @lru_cache so hot-plugged cameras/mounts appear within 1 min.
    """
    global _CACHE
    now = time.monotonic()
    if _CACHE and (now - _CACHE[0]) < _TTL:
        return _CACHE[1]
    result = _inner()
    _CACHE = (now, result)
    return result
