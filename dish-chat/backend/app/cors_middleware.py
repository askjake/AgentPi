import re
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class LocalNetworkCORSMiddleware(BaseHTTPMiddleware):
    """Allow CORS for localhost and all 10.*.*.* and 172.16.*.* network IPs"""
    
    ALLOWED_PATTERNS = [
        re.compile(r"^http://10\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$"),  # 10.*.*.* with port
        re.compile(r"^http://172\.16\.\d{1,3}\.\d{1,3}:\d+$"),  # 172.16.*.* with port
        re.compile(r"^http://localhost:\d+$"),  # localhost with port
        re.compile(r"^http://127\.0\.0\.1:\d+$"),  # 127.0.0.1 with port
        re.compile(r"^https://.*\.dishtv\.technology$"),  # Production domain
    ]
    
    # Explicitly list allowed headers (required when credentials=true)
    ALLOWED_HEADERS = [
        "accept",
        "accept-encoding",
        "accept-language",
        "authorization",
        "content-type",
        "dnt",
        "origin",
        "user-agent",
        "x-csrftoken",
        "x-requested-with",
        "x-auth-request-email",
        "x-auth-request-user",
        "x-auth-request-preferred-username",
        "cache-control",
        "pragma",
    ]
    
    async def dispatch(self, request, call_next):
        origin = request.headers.get("origin")
        
        # Check if origin is allowed
        is_allowed = False
        if origin:
            for pattern in self.ALLOWED_PATTERNS:
                if pattern.match(origin):
                    is_allowed = True
                    break
        
        # Handle preflight OPTIONS requests
        if request.method == "OPTIONS":
            response = Response(status_code=200)
            if is_allowed:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = ", ".join(self.ALLOWED_HEADERS)
                response.headers["Access-Control-Max-Age"] = "3600"
            return response
        
        # Process actual request
        response = await call_next(request)
        
        # Add CORS headers to response if origin is allowed
        if is_allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Expose-Headers"] = "*"
        
        return response
