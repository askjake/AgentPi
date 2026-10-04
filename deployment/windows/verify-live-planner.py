"""Read-only confirmation that port 8000 serves the updated planner binding."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import urllib.request


def verify(root: Path, report: dict) -> None:
    if report.get('contract') != 'agentpi-live-planner-v1':
        raise ValueError('Missing or obsolete live planner contract')
    for key in ('chat_binding_matches', 'agent_mode_binding_matches'):
        if report.get(key) is not True:
            raise ValueError(f'Live graph binding mismatch: {key}')
    for filename, key in (
        ('coverity_tool_loop.py', 'loaded_entrypoint_sha256'),
        ('coverity_tool_loop_token_limit.py', 'loaded_implementation_sha256'),
    ):
        path = root / 'dish-chat/backend/app/agent/agents' / filename
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if report.get(key) != actual:
            raise ValueError(f'Running process/source mismatch: {filename}; restart the managed backend')
    mcop = report.get('mcop', {})
    if mcop.get('implemented_in_this_revision') is not True:
        raise ValueError('MCOP implementation is not active in the running revision')
    if mcop.get('contract') != 'agentpi-mcop-v1':
        raise ValueError('Missing or obsolete MCOP contract')
    if mcop.get('registry_binding_matches') is not True:
        raise ValueError('MCOP registry binding mismatch')
    expected_tools = {
        'agent_spawn_task',
        'agent_spawn_parallel',
        'agent_check_tasks',
        'agent_read_task_result',
        'agent_read_packet',
    }
    if set(mcop.get('bound_tool_names') or []) != expected_tools:
        raise ValueError('MCOP tool binding inventory mismatch')
    if mcop.get('max_depth') != 1:
        raise ValueError('MCOP recursive depth invariant changed')
    for relpath, key in (
        ('dish-chat/backend/app/agent_mode/child_conversation.py', 'loaded_child_sha256'),
        ('dish-chat/backend/app/agent_mode/mcop_tools.py', 'loaded_tools_sha256'),
        ('dish-chat/backend/app/agent_mode/orchestration_packets.py', 'loaded_packets_sha256'),
    ):
        path = root / relpath
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if mcop.get(key) != actual:
            raise ValueError(f'Running MCOP/source mismatch: {relpath}; restart the managed backend')


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    # Bypass ambient HTTP proxy configuration for this loopback-only check.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('http://127.0.0.1:8000/rest/api/v1/health/execution', timeout=5) as response:
            report = json.load(response)
        verify(root, report)
    except Exception as exc:
        print(f'LIVE_PLANNER_IDENTITY_FAILED: {type(exc).__name__}: {exc}')
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=True))
    print('LIVE_PLANNER_IDENTITY_PASS (loaded bindings/source; not a live tool-execution result)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
