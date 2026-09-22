import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Dict, List

from langchain_core.tools import BaseTool

from app.config import get_settings
from app.agent.agents.utils import get_mcp_tools
from app.tools.web_search import public_web_search
from app.tools.internal_search import internal_search
from app.tools.netra_search import netra_search
from app.tools.dish_internal_tools import dish_internal_tool
from app.tools.cluster_inspect import cluster_inspect
from app.tools.agentpi_bridge import (
    agentpi_health,
    agentpi_discover_devices,
    agentpi_list_devices,
    agentpi_scan_rtsp,
    agentpi_runtime_status,
)
from app.agent_mode.tools import (
    # Core agent tools
    agent_git_clone,
    agent_create_venv,
    agent_run_python,
    agent_list_artifacts,
    agent_run_shell,
    
    # Network discovery & management
    agent_network_scan,
    agent_check_device,
    agent_save_device_info,
    agent_list_devices,
    
    # System & container management
    agent_docker_ps,
    agent_system_info,
    
    # Smart home & IoT
    agent_mqtt_publish,
    agent_wake_on_lan,
)

logger = logging.getLogger(__name__)
settings = get_settings()

_ASYNC_TOOL_CACHE: Dict[str, List[BaseTool]] = {}
_TOOL_FACTORIES: Dict[str, Callable[[], List[BaseTool]]] = {}
_ASYNC_TOOL_FACTORIES: Dict[str, Callable[[], Awaitable[List[BaseTool]] | List[BaseTool]]] = {}

# MCP tool sets (if configured)
if getattr(settings, "ENABLE_BETAREPORT_MCP", False) and getattr(settings, "BETAREPORT_MCP_CONFIG", None):
    _ASYNC_TOOL_FACTORIES["beta_report"] = lambda: get_mcp_tools(
        settings.BETAREPORT_MCP_CONFIG
    )

if getattr(settings, "ENABLE_INTERNAL_TOOLS_MCP", False):
    _ASYNC_TOOL_FACTORIES["internal_tools"] = lambda: get_mcp_tools(
        settings.INTERNAL_TOOLS_MCP_CONFIG
    )

# Pure-Python tools for HOME AGENT
_TOOL_FACTORIES.update(
    {
        # Web search and information retrieval
        "search": lambda: [
            public_web_search,
            internal_search,
        ],
        
        # Home network & system management (PRIMARY TOOL SET)
        "agent_mode": lambda: [
            # Hardened AgentPi discovery/device tools (preferred on Windows)
            agentpi_health,
            agentpi_discover_devices,
            agentpi_list_devices,
            agentpi_scan_rtsp,
            agentpi_runtime_status,

            # Development tools
            agent_git_clone,
            agent_create_venv,
            agent_run_python,
            agent_list_artifacts,
            agent_run_shell,
            
            # Network management
            agent_network_scan,
            agent_check_device,
            agent_save_device_info,
            agent_list_devices,
            
            # System & containers
            agent_docker_ps,
            agent_system_info,
            
            # Smart home & IoT
            agent_mqtt_publish,
            agent_wake_on_lan,
        ],
    }
)


async def initialize_mcp_tools() -> None:
    """Initialize MCP (Model Context Protocol) tools asynchronously."""
    global _ASYNC_TOOL_CACHE, _TOOL_FACTORIES

    if _ASYNC_TOOL_CACHE:
        return

    for name, factory in _ASYNC_TOOL_FACTORIES.items():
        try:
            tools = factory()
            if asyncio.iscoroutine(tools) or isinstance(tools, Awaitable):
                tools = await tools
            _ASYNC_TOOL_CACHE[name] = list(tools)
            logger.info(
                "Loaded MCP tool set '%s' with %d tools",
                name,
                len(_ASYNC_TOOL_CACHE[name]),
            )
        except Exception as exc:
            logger.exception(
                "Failed to initialise MCP tool set %s; continuing with it disabled.",
                name,
            )
            _ASYNC_TOOL_CACHE[name] = []

    for name in _ASYNC_TOOL_FACTORIES.keys():
        if name not in _TOOL_FACTORIES:
            _TOOL_FACTORIES[name] = lambda n=name: _ASYNC_TOOL_CACHE.get(n, [])


def get_tools_set(tool_type: str) -> List[BaseTool]:
    """Get a list of tools by tool set type.
    
    Args:
        tool_type: Type of tool set ("search", "agent_mode", etc.)
    
    Returns:
        List of BaseTool instances for the requested tool set.
    """
    factory = _TOOL_FACTORIES.get(tool_type)
    if not factory:
        logger.warning("Unknown tool_type %r requested; returning empty tool list.", tool_type)
        return []
    return list(factory())
