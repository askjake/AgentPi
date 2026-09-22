"""
Netra Search Tool - Internal DISH log/record search system

Netra is DISH's internal search platform for logs, records, and system data.
This tool provides LLM access to search Netra by record ID and date.

NOTE: Netra uses internal IP (100.64.1.30) as DNS may not be available
      on all servers. Can be overridden with NETRA_HOST environment variable.
"""

import json
import logging
import os
from typing import Optional, Any
from datetime import datetime, date
from langchain_core.tools import InjectedToolArg
from langchain_core.runnables import RunnableConfig
from langchain.tools import tool
from typing_extensions import Annotated

import httpx

from app.agent_mode.thought_interceptor import interceptor

logger = logging.getLogger(__name__)

# Netra configuration
# Default to IP address as DNS may not be available on all servers
# Can be overridden with environment variable if DNS is configured
NETRA_HOST = os.getenv("NETRA_HOST", "netra.dish.com")
NETRA_HOSTNAME = "netra.dish.com"  # For Host header

# Build base URL
if NETRA_HOST.startswith("http://") or NETRA_HOST.startswith("https://"):
    NETRA_BASE_URL = NETRA_HOST
else:
    # Default to HTTPS for IP or hostname
    NETRA_BASE_URL = f"https://{NETRA_HOST}"

NETRA_SEARCH_ENDPOINT = f"{NETRA_BASE_URL}/common/search"

# Timeout for Netra requests
NETRA_TIMEOUT = 30.0

logger.info(f"Netra tool configured: host={NETRA_HOST}, base_url={NETRA_BASE_URL}")


@tool("netra_search")
async def netra_search(
    rec_id: Optional[str] = None,
    search_date: Optional[str] = None,
    query: Optional[str] = None,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """
    Search Netra (DISH's internal log/record search system).
    
    Netra is used to find logs, records, and system data across DISH infrastructure.
    
    Args:
        rec_id: Record ID to search for (e.g., "1971450629")
        search_date: Date to search in YYYYMMDD format (e.g., "20260204")
        query: Optional text query for general search
    
    Returns:
        JSON string with search results or error information
    
    Examples:
        - Search by record ID: netra_search(rec_id="1971450629", search_date="20260204")
        - General search: netra_search(query="error logs", search_date="20260204")
    
    Use this tool when you need to:
    - Look up specific record IDs
    - Search system logs by date
    - Find operational data in DISH systems
    - Investigate issues with known record IDs
    """
    interceptor.tool_call(
        "netra_search",
        params={
            "rec_id": rec_id,
            "search_date": search_date,
            "query": query[:50] if query else None
        }
    )
    interceptor.thought(
        f"Searching Netra for: rec_id={rec_id}, date={search_date}, query={query[:30] if query else None}",
        "tool"
    )
    
    # Extract chat_id from config
    chat_id = None
    if config and "configurable" in config:
        chat_id = config["configurable"].get("thread_id")
    
    # Validate inputs
    if not rec_id and not query:
        return json.dumps({
            "error": "Missing required parameter",
            "message": "Either rec_id or query must be provided"
        })
    
    # Build query parameters
    params = {}
    if rec_id:
        params["rec_id"] = rec_id
    if search_date:
        # Validate date format
        try:
            datetime.strptime(search_date, "%Y%m%d")
            params["date"] = search_date
        except ValueError:
            return json.dumps({
                "error": "Invalid date format",
                "message": f"Date must be in YYYYMMDD format, got: {search_date}",
                "example": "20260204"
            })
    if query:
        params["q"] = query
    
    logger.info(f"Netra search in chat {chat_id}: params={params}, host={NETRA_HOST}")
    
    try:
        # Make request to Netra
        # Use IP address directly but set Host header for proper routing
        async with httpx.AsyncClient(
            timeout=NETRA_TIMEOUT,
            follow_redirects=True,
            verify=False  # Disable SSL verification for internal IP
        ) as client:
            resp = await client.get(
                NETRA_SEARCH_ENDPOINT,
                params=params,
                headers={
                    "Host": NETRA_HOSTNAME,  # Important: Set Host header for proper routing
                    "User-Agent": "DISH-Chat-Agent/1.0",
                    "Accept": "application/json, text/html",
                }
            )
            resp.raise_for_status()
            
            # Try to parse as JSON first
            content_type = resp.headers.get("content-type", "")
            
            if "application/json" in content_type:
                data = resp.json()
                interceptor.tool_call("netra_search", result=f"Found JSON results")
                return json.dumps(data, indent=2)
            
            elif "text/html" in content_type:
                # HTML response - extract useful information
                html_content = resp.text
                
                # Basic parsing - look for common patterns
                result = {
                    "source": "Netra",
                    "url": f"https://{NETRA_HOSTNAME}/common/search?{'&'.join(f'{k}={v}' for k,v in params.items())}",
                    "rec_id": rec_id,
                    "date": search_date,
                    "content_type": "html",
                    "content_length": len(html_content),
                    "message": "HTML response received. Content may need manual review.",
                    "preview": html_content[:500] + "..." if len(html_content) > 500 else html_content
                }
                
                # Try to extract useful info from HTML
                if "error" in html_content.lower() or "not found" in html_content.lower():
                    result["status"] = "not_found"
                    result["message"] = "Record may not exist or no results found"
                elif "results" in html_content.lower() or "records" in html_content.lower():
                    result["status"] = "results_found"
                    result["message"] = "Results found - see preview or visit URL"
                else:
                    result["status"] = "unknown"
                
                interceptor.tool_call("netra_search", result=f"HTML response: {result['status']}")
                return json.dumps(result, indent=2)
            
            else:
                # Unknown content type
                return json.dumps({
                    "source": "Netra",
                    "url": f"https://{NETRA_HOSTNAME}/common/search?{'&'.join(f'{k}={v}' for k,v in params.items())}",
                    "content_type": content_type,
                    "message": "Unexpected content type",
                    "raw_content": resp.text[:500]
                }, indent=2)
    
    except httpx.HTTPStatusError as e:
        logger.error(f"Netra HTTP error: {e.response.status_code}")
        
        error_msg = {
            "error": "HTTP error",
            "status_code": e.response.status_code,
            "message": str(e),
            "netra_host": NETRA_HOST
        }
        
        if e.response.status_code == 401:
            error_msg["message"] = "Authentication required. User may need to log in to Netra."
        elif e.response.status_code == 403:
            error_msg["message"] = "Access forbidden. User may not have permission to access this record."
        elif e.response.status_code == 404:
            error_msg["message"] = "Record not found or invalid search parameters."
        
        return json.dumps(error_msg, indent=2)
    
    except httpx.TimeoutException:
        logger.error(f"Netra request timeout after {NETRA_TIMEOUT}s")
        return json.dumps({
            "error": "Timeout",
            "message": f"Netra search timed out after {NETRA_TIMEOUT} seconds",
            "netra_host": NETRA_HOST
        })
    
    except httpx.ConnectError as e:
        logger.error(f"Netra connection error: {e}")
        return json.dumps({
            "error": "Connection error",
            "message": f"Could not connect to Netra at {NETRA_HOST}",
            "details": str(e),
            "suggestion": "Check network connectivity or NETRA_HOST configuration"
        })
    
    except Exception as e:
        logger.error(f"Netra search failed: {e}", exc_info=True)
        return json.dumps({
            "error": "Search failed",
            "message": str(e),
            "type": type(e).__name__,
            "netra_host": NETRA_HOST
        })


@tool("netra_url_builder")
def netra_url_builder(
    rec_id: Optional[str] = None,
    search_date: Optional[str] = None,
    query: Optional[str] = None
) -> str:
    """
    Build a Netra URL for manual access.
    
    Use this when you want to provide a user with a direct link to Netra
    instead of executing the search programmatically.
    
    Args:
        rec_id: Record ID to search for
        search_date: Date in YYYYMMDD format
        query: Text query
    
    Returns:
        Formatted Netra URL
    """
    params = []
    if rec_id:
        params.append(f"rec_id={rec_id}")
    if search_date:
        params.append(f"date={search_date}")
    if query:
        params.append(f"q={query}")
    
    # Always use the public hostname for URLs given to users
    if params:
        url = f"https://{NETRA_HOSTNAME}/common/search?{'&'.join(params)}"
    else:
        url = f"https://{NETRA_HOSTNAME}"
    
    return json.dumps({
        "url": url,
        "message": "Visit this URL in your browser to access Netra",
        "note": "You may need to authenticate with your DISH credentials",
        "internal_note": f"Tool uses {NETRA_HOST} but URL shows {NETRA_HOSTNAME} for user access"
    }, indent=2)
