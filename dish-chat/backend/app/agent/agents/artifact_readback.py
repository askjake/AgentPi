"""Bounded filesystem observations, never an LLM's claim of successful work.

This deliberately does NOT execute artifacts, search another user's workspace,
create files, or certify functionality/desktop installation. File existence is
not evidence of when or by whom a file was created.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

_ALLOWED = {'.py', '.html', '.css', '.js', '.ts', '.md', '.lnk', '.url', '.cmd', '.ps1', '.wav', '.mp3', '.ogg', '.flac', '.m4a', '.pcm', '.txt'}
_SKIP = {'.git', '.venv', '.venv-windows', '__pycache__', 'node_modules'}
_MAX_FILES = 512
_MAX_BYTES = 8 * 1024 * 1024
_MAX_TURN_ARTIFACTS = 12
_MAX_TURN_OUTPUT_CHARS = 6000


def _linked(path: Path) -> bool:
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def readback(base: Path, chat_id: str | None) -> dict:
    result = {'kind': 'workspace_readback', 'complete_scan': True, 'inventory_complete': True, 'artifacts': [],
              'functional_acceptance': 'not_performed', 'desktop_shortcut': 'not_verified'}
    if not isinstance(chat_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', chat_id):
        return {**result, 'complete_scan': False, 'inventory_complete': False, 'status': 'invalid_workspace_identity'}
    root = Path(base).expanduser().resolve()
    workspace = root / chat_id
    if _linked(workspace) or not workspace.resolve().is_relative_to(root):
        return {**result, 'complete_scan': False, 'inventory_complete': False, 'status': 'workspace_link_rejected'}
    result['workspace'] = str(workspace)
    if not workspace.is_dir():
        return {**result, 'status': 'workspace_not_found'}
    count = 0
    bytes_read = 0

    def failed(_error):
        result['complete_scan'] = False
        result['inventory_complete'] = False

    for folder, dirs, files in os.walk(workspace, followlinks=False, onerror=failed):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP and not _linked(Path(folder) / d))
        count += 1
        if count > _MAX_FILES:
            result['complete_scan'] = False
            result['inventory_complete'] = False
            break
        for name in sorted(files):
            count += 1
            if count > _MAX_FILES:
                result['complete_scan'] = False
                result['inventory_complete'] = False
                break
            path = Path(folder) / name
            if name.startswith('.') or path.suffix.lower() not in _ALLOWED:
                continue
            try:
                if _linked(path) or not path.resolve().is_relative_to(workspace):
                    continue
                before = path.stat()
                entry = {'path': str(path), 'bytes': before.st_size, 'mtime_ns': before.st_mtime_ns, 'sha256': None}
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
                result['inventory_complete'] = False
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
        lines.append('No matching app/script/shortcut/audio artifacts were observed in this workspace.')
    if not report['complete_scan']:
        lines.append('Readback was incomplete or blocked; absence cannot be concluded.')
    lines += [
        'Files elsewhere, including the Windows Desktop, were not searched.',
        'No syntax test, application launch, device-control capability, or desktop shortcut creation is certified by this readback.',
        'An earlier assistant statement is not a file-write or verification receipt.',
    ]
    return '\n'.join(lines)


def turn_changes(before: dict, after: dict, preferred_paths=()) -> dict:
    """Compare observations, not wall-clock time or claims made by a tool.

    Missing entries in an incomplete baseline are unknown, never 'created'.
    Hashes detect same-size edits even when timestamps are preserved. Metadata
    alone is a weaker fallback. Concurrent writers cannot be attributed.
    """
    report = {**after, 'kind': 'turn_artifact_readback', 'artifacts': [],
              'historical_omitted': 0, 'omitted_changes': 0, 'unknown_changes': 0}
    report['complete_scan'] = bool(before.get('complete_scan') and after.get('complete_scan'))
    if not before.get('workspace') or before.get('workspace') != after.get('workspace'):
        return {**report, 'complete_scan': False, 'status': 'baseline_unavailable'}
    prior = {item['path']: item for item in before.get('artifacts', [])}
    changed = []
    for item in after.get('artifacts', []):
        old = prior.get(item['path'])
        change = None
        basis = 'snapshot comparison'
        if old is None:
            if before.get('inventory_complete', False):
                change = 'created_this_turn'
            else:
                report['unknown_changes'] += 1
        elif old.get('sha256') and item.get('sha256'):
            if old['sha256'] != item['sha256']:
                change = 'modified_this_turn'
                basis = 'content hash changed'
            else:
                report['historical_omitted'] += 1
        elif (old.get('bytes'), old.get('mtime_ns')) != (item.get('bytes'), item.get('mtime_ns')):
            change = 'modified_this_turn'
            basis = 'size/mtime changed; content not verified'
        else:
            report['historical_omitted'] += 1
            report['unknown_changes'] += 1
        if change:
            changed.append({**item, 'change': change, 'basis': basis})
    # Executor filenames influence ordering only; they cannot add an unobserved
    # path, authorize a read outside this workspace, or establish provenance.
    preferred = {str(path).replace('\\', '/').removeprefix('./') for path in preferred_paths}
    def priority(item):
        path = item['path'].replace('\\', '/')
        workspace = after['workspace'].replace('\\', '/').rstrip('/') + '/'
        relative = path.removeprefix(workspace)
        return (relative not in preferred and path not in preferred, relative)
    changed.sort(key=priority)
    report['artifacts'] = changed[:_MAX_TURN_ARTIFACTS]
    report['omitted_changes'] = max(0, len(changed) - _MAX_TURN_ARTIFACTS)
    report['status'] = 'observed_turn_changes' if changed else 'no_turn_changes_observed'
    return report


def render_turn(report: dict) -> str:
    lines = ['ARTIFACT_READBACK_ONLY — Turn-scoped artifacts',
             'This is a current filesystem observation, not a completion certificate.',
             'Status: ' + report['status']]
    for item in report['artifacts'][:_MAX_TURN_ARTIFACTS]:
        # JSON quoting keeps a hostile filename from creating report lines.
        path = json.dumps(item['path'][:240], ensure_ascii=True)
        lines.append(f"{item['change']}: {path} | {item['bytes']} bytes | "
                     f"SHA256={item['sha256'] or 'not_verified'} | {item['basis']}")
    if not report['artifacts']:
        lines.append('Turn-scoped artifact readback found no created or modified files in the compared observations.')
    lines.append(f"Older workspace artifacts omitted: {report['historical_omitted']}")
    if report['omitted_changes']:
        lines.append(f"Additional changed artifacts omitted: {report['omitted_changes']}")
    if not report['complete_scan'] or report['unknown_changes']:
        lines.append('Comparison incomplete or content unverified; absence of changes cannot be concluded.')
    lines.extend([
        'Created/modified means observed between snapshots; concurrent writers and agent authorship are not established.',
        'File existence does not prove correctness, usability, execution or creation by this agent.',
        'Files elsewhere were not searched. No syntax test, playback, launch or functional acceptance is certified.',
    ])
    # Keep the caveats even when path escaping expands unusual filenames.
    text = '\n'.join(lines)
    if len(text) > _MAX_TURN_OUTPUT_CHARS:
        prefix = '\n'.join(lines[:3])
        suffix = '\n'.join(lines[-5:])
        text = prefix + '\nArtifact paths omitted to enforce output limit.\n' + suffix
    return text
