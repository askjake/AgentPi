"""Bounded filesystem observations, never an LLM's claim of successful work.

This deliberately does NOT execute artifacts, search another user's workspace,
create files, or certify functionality/desktop installation. File existence is
not evidence of when or by whom a file was created.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

_ALLOWED = {'.py', '.html', '.css', '.js', '.ts', '.md', '.lnk', '.url', '.cmd', '.ps1'}
_SKIP = {'.git', '.venv', '.venv-windows', '__pycache__', 'node_modules'}
_MAX_FILES = 512
_MAX_BYTES = 8 * 1024 * 1024


def _linked(path: Path) -> bool:
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def readback(base: Path, chat_id: str | None) -> dict:
    result = {'kind': 'workspace_readback', 'complete_scan': True, 'artifacts': [],
              'functional_acceptance': 'not_performed', 'desktop_shortcut': 'not_verified'}
    if not isinstance(chat_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', chat_id):
        return {**result, 'complete_scan': False, 'status': 'invalid_workspace_identity'}
    root = Path(base).expanduser().resolve()
    workspace = root / chat_id
    if _linked(workspace) or not workspace.resolve().is_relative_to(root):
        return {**result, 'complete_scan': False, 'status': 'workspace_link_rejected'}
    result['workspace'] = str(workspace)
    if not workspace.is_dir():
        return {**result, 'status': 'workspace_not_found'}
    count = 0
    bytes_read = 0

    def failed(_error):
        result['complete_scan'] = False

    for folder, dirs, files in os.walk(workspace, followlinks=False, onerror=failed):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP and not _linked(Path(folder) / d))
        count += 1
        if count > _MAX_FILES:
            result['complete_scan'] = False
            break
        for name in sorted(files):
            count += 1
            if count > _MAX_FILES:
                result['complete_scan'] = False
                break
            path = Path(folder) / name
            if name.startswith('.') or path.suffix.lower() not in _ALLOWED:
                continue
            try:
                if _linked(path) or not path.resolve().is_relative_to(workspace):
                    continue
                before = path.stat()
                entry = {'path': str(path), 'bytes': before.st_size, 'sha256': None}
                if bytes_read + before.st_size <= _MAX_BYTES:
                    # Read limit also covers files growing during readback.
                    with path.open('rb') as handle:
                        data = handle.read(_MAX_BYTES - bytes_read + 1)
                    bytes_read += len(data)
                    after = path.stat()
                    if len(data) == before.st_size and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
                        entry['sha256'] = hashlib.sha256(data).hexdigest()
                    else:
                        result['complete_scan'] = False
                else:
                    result['complete_scan'] = False
                result['artifacts'].append(entry)
            except OSError:
                result['complete_scan'] = False
        if count > _MAX_FILES:
            break
    result['status'] = 'observed_files' if result['artifacts'] else 'no_artifacts_observed'
    return result


def render(report: dict) -> str:
    lines = ['ARTIFACT_READBACK_ONLY',
             'This is a current filesystem observation, not a completion certificate.',
             'Status: ' + report['status']]
    if report.get('workspace'):
        lines.append('Checked workspace: ' + report['workspace'])
    for item in report['artifacts']:
        lines.append(f"Observed: {item['path']} | {item['bytes']} bytes | SHA256={item['sha256'] or 'not_verified'}")
    if not report['artifacts']:
        lines.append('No matching app/script/shortcut artifacts were observed in this workspace.')
    if not report['complete_scan']:
        lines.append('Readback was incomplete or blocked; absence cannot be concluded.')
    lines += [
        'Files elsewhere, including the Windows Desktop, were not searched.',
        'No syntax test, application launch, device-control capability, or desktop shortcut creation is certified by this readback.',
        'An earlier assistant statement is not a file-write or verification receipt.',
    ]
    return '\n'.join(lines)
