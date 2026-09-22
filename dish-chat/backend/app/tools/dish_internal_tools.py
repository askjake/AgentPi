"""
DISH Internal Tools Framework

Provides LLM access to DISH internal tools and services:
- CART (Customer Account Research Tool)
- CCTools (Customer Care Tools)
- Portal (Internal Tools Portal)

NOTE: These tools use internal IPs/hostnames configured via environment variables.
      DNS resolution may not be available on all servers.
"""

import json
import logging
import os
from typing import Optional, Any, Dict, Literal
from datetime import datetime
from langchain_core.tools import InjectedToolArg
from langchain_core.runnables import RunnableConfig
from langchain.tools import tool
from typing_extensions import Annotated

import httpx

from app.agent_mode.thought_interceptor import interceptor

logger = logging.getLogger(__name__)

# ============================================================================
# Service Configuration
# ============================================================================

# Service definitions with hostname and configurable host/IP
SERVICES = {
    "cart": {
        "hostname": "cart.dtc.dish.corp",
        "host": os.getenv("CART_HOST", "cart.dtc.dish.corp"),
        "description": "Customer Account Research Tool - Account lookup and research",
        "endpoints": {
            "search": "/api/search",
            "account": "/api/account",
            "customer": "/api/customer"
        }
    },
    "cctools": {
        "hostname": "cctools.dtc.dish.corp",
        "host": os.getenv("CCTOOLS_HOST", "cctools.dtc.dish.corp"),
        "description": "Customer Care Tools - Support and troubleshooting",
        "endpoints": {
            "lookup": "/api/lookup",
            "tools": "/api/tools",
            "status": "/api/status"
        }
    },
    "portal": {
        "hostname": "inlpecca01.dtc.dish.corp",
        "host": os.getenv("PORTAL_HOST", "inlpecca01.dtc.dish.corp"),
        "description": "Internal Tools Portal - Gateway to internal tools",
        "endpoints": {
            "tools": "/api/tools",
            "services": "/api/services"
        }
    }
}

# Global timeout
INTERNAL_TOOLS_TIMEOUT = float(os.getenv("INTERNAL_TOOLS_TIMEOUT", "30.0"))

# Log configuration
for service_name, config in SERVICES.items():
    logger.info(
        f"Internal tool configured: {service_name} -> "
        f"host={config['host']}, hostname={config['hostname']}"
    )


# ============================================================================
# Helper Functions
# ============================================================================

def get_service_config(service: str) -> Optional[Dict]:
    """Get configuration for a service"""
    return SERVICES.get(service.lower())


def build_url(service: str, endpoint: str = "") -> str:
    """Build URL for a service and endpoint"""
    config = get_service_config(service)
    if not config:
        raise ValueError(f"Unknown service: {service}")
    
    host = config["host"]
    
    # Add protocol if not present
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"https://{host}"
    
    # Add endpoint
    if endpoint:
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        return f"{host}{endpoint}"
    
    return host


# ============================================================================
# Main Tool
# ============================================================================

@tool("dish_internal_tool")
async def dish_internal_tool(
    service: Literal["cart", "cctools", "portal"],
    endpoint: Optional[str] = None,
    params: Optional[Dict[str, str]] = None,
    method: Literal["GET", "POST"] = "GET",
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """
    Access DISH internal tools and services.
    
    Available services:
    - cart: Customer Account Research Tool (account lookup, research)
    - cctools: Customer Care Tools (support, troubleshooting)
    - portal: Internal Tools Portal (gateway to tools)
    
    Args:
        service: Which internal service to access
        endpoint: API endpoint path (e.g., "/api/search", "/api/account")
        params: Query parameters or POST data
        method: HTTP method (GET or POST)
    
    Returns:
        JSON string with results or error information
    
    Examples:
        - Access CART: dish_internal_tool(service="cart", endpoint="/api/search", params={"account": "12345"})
        - Access CCTools: dish_internal_tool(service="cctools", endpoint="/api/lookup", params={"phone": "555-1234"})
        - Access Portal: dish_internal_tool(service="portal", endpoint="/api/tools")
    
    Use this tool when you need to:
    - Look up customer accounts
    - Access customer care tools
    - Use internal DISH services
    - Troubleshoot customer issues
    """
    interceptor.tool_call(
        "dish_internal_tool",
        params={
            "service": service,
            "endpoint": endpoint,
            "method": method,
            "params": str(params)[:50] if params else None
        }
    )
    interceptor.thought(
        f"Accessing DISH {service} tool: {endpoint}",
        "tool"
    )
    
    # Extract chat_id from config
    chat_id = None
    if config and "configurable" in config:
        chat_id = config["configurable"].get("thread_id")
    
    # Get service configuration
    service_config = get_service_config(service)
    if not service_config:
        return json.dumps({
            "error": "Unknown service",
            "message": f"Service '{service}' not found",
            "available_services": list(SERVICES.keys())
        })
    
    # Build URL
    try:
        url = build_url(service, endpoint or "")
    except ValueError as e:
        return json.dumps({
            "error": "Invalid service",
            "message": str(e)
        })
    
    logger.info(
        f"Internal tool request in chat {chat_id}: "
        f"service={service}, endpoint={endpoint}, method={method}"
    )
    
    try:
        # Make request
        async with httpx.AsyncClient(
            timeout=INTERNAL_TOOLS_TIMEOUT,
            follow_redirects=True,
            verify=False  # May need to disable for internal services
        ) as client:
            # Set headers
            headers = {
                "Host": service_config["hostname"],
                "User-Agent": "DISH-Chat-Agent/1.0",
                "Accept": "application/json, text/html",
            }
            
            # Make request based on method
            if method.upper() == "GET":
                resp = await client.get(url, params=params, headers=headers)
            elif method.upper() == "POST":
                resp = await client.post(url, json=params, headers=headers)
            else:
                return json.dumps({
                    "error": "Invalid method",
                    "message": f"Method {method} not supported"
                })
            
            resp.raise_for_status()
            
            # Try to parse response
            content_type = resp.headers.get("content-type", "")
            
            if "application/json" in content_type:
                data = resp.json()
                interceptor.tool_call("dish_internal_tool", result=f"JSON response from {service}")
                return json.dumps(data, indent=2)
            
            elif "text/html" in content_type:
                html_content = resp.text
                
                result = {
                    "service": service,
                    "url": url,
                    "content_type": "html",
                    "content_length": len(html_content),
                    "message": "HTML response received. May need manual review.",
                    "preview": html_content[:500] + "..." if len(html_content) > 500 else html_content
                }
                
                # Try to detect useful info
                if "error" in html_content.lower():
                    result["status"] = "error_detected"
                elif "success" in html_content.lower() or "result" in html_content.lower():
                    result["status"] = "success_likely"
                else:
                    result["status"] = "unknown"
                
                interceptor.tool_call("dish_internal_tool", result=f"HTML from {service}: {result['status']}")
                return json.dumps(result, indent=2)
            
            else:
                return json.dumps({
                    "service": service,
                    "url": url,
                    "content_type": content_type,
                    "message": "Unexpected content type",
                    "raw_content": resp.text[:500]
                }, indent=2)
    
    except httpx.HTTPStatusError as e:
        logger.error(f"Internal tool HTTP error ({service}): {e.response.status_code}")
        
        error_msg = {
            "error": "HTTP error",
            "service": service,
            "status_code": e.response.status_code,
            "message": str(e),
            "url": url
        }
        
        if e.response.status_code == 401:
            error_msg["message"] = "Authentication required. User may need to log in."
        elif e.response.status_code == 403:
            error_msg["message"] = "Access forbidden. User may not have permission."
        elif e.response.status_code == 404:
            error_msg["message"] = "Endpoint not found. Check endpoint path."
        
        return json.dumps(error_msg, indent=2)
    
    except httpx.TimeoutException:
        logger.error(f"Internal tool timeout ({service}) after {INTERNAL_TOOLS_TIMEOUT}s")
        return json.dumps({
            "error": "Timeout",
            "service": service,
            "message": f"Request timed out after {INTERNAL_TOOLS_TIMEOUT} seconds",
            "url": url
        })
    
    except httpx.ConnectError as e:
        logger.error(f"Internal tool connection error ({service}): {e}")
        return json.dumps({
            "error": "Connection error",
            "service": service,
            "message": f"Could not connect to {service}",
            "details": str(e),
            "suggestion": f"Check {service.upper()}_HOST configuration or network connectivity"
        })
    
    except Exception as e:
        logger.error(f"Internal tool request failed ({service}): {e}", exc_info=True)
        return json.dumps({
            "error": "Request failed",
            "service": service,
            "message": str(e),
            "type": type(e).__name__
        })


# ============================================================================
# URL Builder Tool
# ============================================================================

@tool("dish_internal_tool_url")
def dish_internal_tool_url(
    service: Literal["cart", "cctools", "portal"],
    endpoint: Optional[str] = None,
    params: Optional[Dict[str, str]] = None
) -> str:
    """
    Build a URL for accessing DISH internal tools manually.
    
    Use this when you want to provide a user with a direct link
    instead of executing the request programmatically.
    
    Args:
        service: Which internal service
        endpoint: API endpoint path
        params: Query parameters
    
    Returns:
        Formatted URL for manual access
    """
    service_config = get_service_config(service)
    if not service_config:
        return json.dumps({
            "error": "Unknown service",
            "available_services": list(SERVICES.keys())
        })
    
    # Build URL with hostname (for user access)
    hostname = service_config["hostname"]
    url = f"https://{hostname}"
    
    if endpoint:
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        url += endpoint
    
    if params:
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        url += f"?{param_str}"
    
    return json.dumps({
        "url": url,
        "service": service,
        "description": service_config["description"],
        "message": "Visit this URL in your browser",
        "note": "You may need to authenticate with your DISH credentials"
    }, indent=2)


# ============================================================================
# Service Info Tool
# ============================================================================

@tool("dish_internal_tools_info")
def dish_internal_tools_info() -> str:
    """
    Get information about available DISH internal tools.
    
    Returns:
        JSON with service descriptions and available endpoints
    """
    services_info = {}
    
    for service_name, config in SERVICES.items():
        services_info[service_name] = {
            "description": config["description"],
            "hostname": config["hostname"],
            "configured_host": config["host"],
            "available_endpoints": list(config["endpoints"].keys()),
            "endpoint_paths": config["endpoints"]
        }
    
    return json.dumps({
        "services": services_info,
        "usage": "Use dish_internal_tool(service, endpoint, params) to access these services",
        "configuration": {
            "CART_HOST": "Set to override CART host/IP",
            "CCTOOLS_HOST": "Set to override CCTools host/IP",
            "PORTAL_HOST": "Set to override Portal host/IP",
            "INTERNAL_TOOLS_TIMEOUT": "Set request timeout (default: 30s)"
        }
    }, indent=2)
