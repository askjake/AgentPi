"""
Progress indicator wrapper for slow-running MCP tools.
Emits SSE progress events during long tool execution.
"""

import asyncio
import time
import logging
from typing import Any, Callable, Optional
from functools import wraps
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

# Tools that are known to be slow (30+ seconds)
SLOW_TOOLS = [
    "query_viewership",
    "query_unique_suid_stations",
    "netra_search",
    "cluster_inspect",
]

# Global progress callback that can be set by the message service
_progress_callback: Optional[Callable[[dict], None]] = None


def set_progress_callback(callback: Callable[[dict], None]):
    """Set the callback function for emitting progress events."""
    global _progress_callback
    _progress_callback = callback


def clear_progress_callback():
    """Clear the progress callback."""
    global _progress_callback
    _progress_callback = None


async def _emit_progress(tool_name: str, elapsed: float, status: str = "running"):
    """Emit a progress event via the callback."""
    if _progress_callback:
        try:
            progress_data = {
                "type": "tool_progress",
                "tool_name": tool_name,
                "elapsed_seconds": round(elapsed, 1),
                "status": status,
                "message": f"⏳ {tool_name} running... ({round(elapsed)}s elapsed)"
            }
            _progress_callback(progress_data)
        except Exception as e:
            logger.warning(f"Failed to emit progress event: {e}")


async def _progress_monitor(tool_name: str, task: asyncio.Task, interval: float = 10.0):
    """
    Monitor a running task and emit progress updates at regular intervals.
    
    Args:
        tool_name: Name of the tool being executed
        task: The asyncio task to monitor
        interval: Seconds between progress updates (default 10s)
    """
    start_time = time.time()
    
    while not task.done():
        await asyncio.sleep(interval)
        if not task.done():
            elapsed = time.time() - start_time
            await _emit_progress(tool_name, elapsed, "running")


def wrap_tool_with_progress(tool: BaseTool) -> BaseTool:
    """
    Wrap a tool to emit progress indicators during execution.
    Only wraps tools that are known to be slow.
    
    Args:
        tool: The LangChain tool to wrap
        
    Returns:
        The wrapped tool (or original if not slow)
    """
    # Get tool name safely
    if hasattr(tool, 'name'):
        tool_name = tool.name
    elif hasattr(tool, '__name__'):
        tool_name = tool.__name__
    else:
        tool_name = str(tool)
    
    # Only wrap slow tools
    if not any(slow_tool in tool_name.lower() for slow_tool in SLOW_TOOLS):
        return tool
    
    logger.info(f"Wrapping tool '{tool_name}' with progress indicators")
    
    # Store original invoke methods
    original_invoke = tool._run
    original_ainvoke = tool._arun if hasattr(tool, '_arun') else None
    
    def wrapped_invoke(*args, **kwargs):
        """Synchronous wrapper with progress."""
        logger.info(f"Starting slow tool: {tool_name}")
        start_time = time.time()
        
        try:
            # Inspect function signature to handle config parameter correctly
            if hasattr(original_invoke, '__code__'):
                func_params = original_invoke.__code__.co_varnames
                
                # If function expects 'config' but it's not in kwargs, add it
                if 'config' in func_params and 'config' not in kwargs:
                    kwargs['config'] = {}
                
                # If function does NOT expect 'config' but it's in kwargs, remove it
                elif 'config' not in func_params and 'config' in kwargs:
                    kwargs = {k: v for k, v in kwargs.items() if k != 'config'}
            
            result = original_invoke(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"Tool {tool_name} completed in {elapsed:.1f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Tool {tool_name} failed after {elapsed:.1f}s: {e}")
            raise
    
    async def wrapped_ainvoke(*args, **kwargs):
        """Asynchronous wrapper with progress monitoring."""
        logger.info(f"Starting slow tool (async): {tool_name}")
        start_time = time.time()
        
        # Emit initial progress
        await _emit_progress(tool_name, 0.0, "starting")
        
        try:
            # Create the actual tool execution task
            if original_ainvoke:
                # Inspect function signature to handle config parameter correctly
                if hasattr(original_ainvoke, '__code__'):
                    func_params = original_ainvoke.__code__.co_varnames
                    
                    # If function expects 'config' but it's not in kwargs, add it
                    if 'config' in func_params and 'config' not in kwargs:
                        kwargs['config'] = {}
                    
                    # If function does NOT expect 'config' but it's in kwargs, remove it
                    elif 'config' not in func_params and 'config' in kwargs:
                        kwargs = {k: v for k, v in kwargs.items() if k != 'config'}
                
                exec_task = asyncio.create_task(original_ainvoke(*args, **kwargs))
            else:
                # Fall back to sync version in executor
                loop = asyncio.get_event_loop()
                exec_task = loop.run_in_executor(None, lambda: original_invoke(*args, **kwargs))
                exec_task = asyncio.create_task(exec_task)
            
            # Create progress monitor task
            monitor_task = asyncio.create_task(_progress_monitor(tool_name, exec_task, interval=10.0))
            
            # Wait for execution to complete
            result = await exec_task
            
            # Cancel monitor and emit completion
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            
            elapsed = time.time() - start_time
            await _emit_progress(tool_name, elapsed, "completed")
            logger.info(f"Tool {tool_name} completed in {elapsed:.1f}s")
            
            return result
            
        except Exception as e:
            elapsed = time.time() - start_time
            await _emit_progress(tool_name, elapsed, "failed")
            logger.error(f"Tool {tool_name} failed after {elapsed:.1f}s: {e}")
            raise
    
    # Replace methods
    tool._run = wrapped_invoke
    if original_ainvoke or asyncio.iscoroutinefunction(original_invoke):
        tool._arun = wrapped_ainvoke
    
    return tool


def wrap_tools_with_progress(tools: list[BaseTool]) -> list[BaseTool]:
    """
    Wrap all slow tools in a list with progress indicators.
    
    Args:
        tools: List of LangChain tools
        
    Returns:
        List of wrapped tools
    """
    return [wrap_tool_with_progress(tool) for tool in tools]
