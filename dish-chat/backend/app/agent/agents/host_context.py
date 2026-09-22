from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Iterable


def _run(cmd: list[str]) -> str:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        return (cp.stdout or cp.stderr or "").strip()
    except Exception:
        return ""


def _exists_any(paths: Iterable[str]) -> list[str]:
    return [p for p in paths if Path(p).exists()]


@lru_cache(maxsize=1)
def build_host_context() -> str:
    facts: list[str] = []

    proc_version = Path("/proc/version").read_text(errors="ignore") if Path("/proc/version").exists() else ""
    is_wsl = "microsoft" in proc_version.lower() or bool(os.getenv("WSL_DISTRO_NAME")) or Path("/mnt/c/Windows").exists()

    if is_wsl:
        facts.append("You are running inside WSL on a Windows host.")
        facts.append("Linux shell commands run inside WSL, but Windows files are usually reachable under /mnt/c, /mnt/d, etc.")
        facts.append("Windows commands may be reachable via powershell.exe or cmd.exe from WSL.")
    else:
        facts.append("You are running on a Linux-like host environment with shell access.")

    if shutil.which("powershell.exe"):
        facts.append("powershell.exe is available from this environment.")
    if shutil.which("cmd.exe"):
        facts.append("cmd.exe is available from this environment.")
    if shutil.which("ffmpeg"):
        facts.append("ffmpeg is installed and can be used for capture/inspection tasks.")
    if shutil.which("v4l2-ctl"):
        facts.append("v4l2-ctl is installed and can inspect V4L2 video devices.")

    mounts = _exists_any(["/mnt/c/Users", "/mnt/c/Windows", "/mnt/c/Program Files", "/mnt/c/Users/Public/Desktop"])
    if mounts:
        facts.append(f"Detected Windows mount points: {', '.join(mounts)}")

    vids = sorted(str(p) for p in Path("/dev").glob("video*"))
    if vids:
        facts.append(f"Detected Linux video device nodes: {', '.join(vids[:8])}")
    bypath = _exists_any(["/dev/v4l/by-path", "/dev/v4l/by-id"])
    if bypath:
        facts.append(f"Detected V4L device metadata paths: {', '.join(bypath)}")

    lsusb = _run(["bash", "-lc", "lsusb 2>/dev/null | egrep -i 'magewell|camera|video|capture|hdmi' | head -n 20"])
    if lsusb:
        facts.append("USB/video-related devices detected by lsusb:")
        facts.append(lsusb)

    facts.append("For local host, filesystem, process, VLC, Windows, peripheral, and device questions, prefer shell/process inspection over web search.")
    facts.append("For current events or fresh facts, prefer public_web_search and retry with tighter queries before concluding no answer exists.")

    return "\n".join(f"- {f}" for f in facts if f)
