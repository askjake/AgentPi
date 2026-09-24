import asyncio, logging
from collections.abc import Awaitable, Callable
from typing import Dict, List
from langchain_core.tools import BaseTool
from app.config import get_settings
from app.agent.agents.utils import get_mcp_tools
from app.tools.web_search import public_web_search
from app.tools.internal_search import internal_search
from app.tools.agentpi_bridge import (
    agentpi_health, agentpi_discover_devices, agentpi_list_devices,
    agentpi_scan_rtsp, agentpi_runtime_status,
    agentpi_mqtt_start, agentpi_mqtt_stop,
    agentpi_homeassistant_start, agentpi_homeassistant_stop,
    agentpi_clear_inventory,
)
from app.agent_mode.tools import (
    agent_git_clone, agent_create_venv, agent_run_python,
    agent_list_artifacts, agent_run_shell,
    agent_network_scan, agent_check_device, agent_save_device_info, agent_list_devices,
    agent_docker_ps, agent_system_info, agent_mqtt_publish, agent_wake_on_lan,
)

logger = logging.getLogger(__name__)
settings = get_settings()

_ATC: Dict[str, List[BaseTool]] = {}
_TF:  Dict[str, Callable[[], List[BaseTool]]] = {}
_ATF: Dict[str, Callable[[], Awaitable[List[BaseTool]] | List[BaseTool]]] = {}

if getattr(settings, "ENABLE_BETAREPORT_MCP", False) and getattr(settings, "BETAREPORT_MCP_CONFIG", None):
    _ATF["beta_report"] = lambda: get_mcp_tools(settings.BETAREPORT_MCP_CONFIG)
if getattr(settings, "ENABLE_INTERNAL_TOOLS_MCP", False):
    _ATF["internal_tools"] = lambda: get_mcp_tools(settings.INTERNAL_TOOLS_MCP_CONFIG)

_TF.update({
    "search": lambda: [public_web_search, internal_search],
    "agent_mode": lambda: [
        # AgentPi bridge — preferred for all device/discovery ops (calls localhost:8765)
        agentpi_health,
        agentpi_discover_devices,
        agentpi_list_devices,
        agentpi_scan_rtsp,
        agentpi_runtime_status,
        agentpi_mqtt_start,            # PATCH-04
        agentpi_mqtt_stop,             # PATCH-04
        agentpi_homeassistant_start,   # PATCH-04
        agentpi_homeassistant_stop,    # PATCH-04
        agentpi_clear_inventory,       # PATCH-04
        # Development
        agent_git_clone, agent_create_venv, agent_run_python,
        agent_list_artifacts, agent_run_shell,
        # Network
        agent_network_scan, agent_check_device, agent_save_device_info, agent_list_devices,
        # System
        agent_docker_ps, agent_system_info,
        # Smart home
        agent_mqtt_publish, agent_wake_on_lan,
    ],
})

async def initialize_mcp_tools() -> None:
    global _ATC, _TF
    if _ATC:
        return
    for name, factory in _ATF.items():
        try:
            tools = factory()
            if asyncio.iscoroutine(tools) or isinstance(tools, Awaitable):
                tools = await tools
            _ATC[name] = list(tools)
            logger.info("MCP tool set '%s' loaded (%d tools)", name, len(_ATC[name]))
        except Exception:
            logger.exception("Failed MCP tool set %s", name)
            _ATC[name] = []
    for n in _ATF:
        if n not in _TF:
            _TF[n] = lambda k=n: _ATC.get(k, [])

def get_tools_set(tool_type: str) -> List[BaseTool]:
    f = _TF.get(tool_type)
    if not f:
        logger.warning("Unknown tool_type %r", tool_type)
        return []
    return list(f())
