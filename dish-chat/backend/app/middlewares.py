import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.concurrency import iterate_in_threadpool
from fastapi import Request, Header

logger = logging.getLogger(__name__)


class LocalIdInjectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        headers = dict(request.scope["headers"])
        headers[b"x-auth-request-email"] = b"test.test@dish.com"
        request.scope["headers"] = [(k, v) for k, v in headers.items()]

        return await call_next(request)


class LogRespMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_body = await request.body()
        
        logger.debug(f"Request path: {request.method} {request.url.path}")
        logger.debug(f"Request params: {request.query_params}")
        logger.debug(f"Request body: {request_body}")
        
        response = await call_next(request)
        
        # Check if it's a streaming response by headers
        is_streaming = (
            response.headers.get("transfer-encoding") == "chunked" or
            "text/event-stream" in response.headers.get("content-type", "")
        )
        
        if is_streaming:
            logger.debug(f"Streaming response, status: {response.status_code}")
        else:
            try:
                response_body = [chunk async for chunk in response.body_iterator]
                response.body_iterator = iterate_in_threadpool(iter(response_body))
                if response_body:
                    logger.debug(f"response_body={response_body[0].decode()}")
            except:
                logger.debug(f"Could not decode response, status: {response.status_code}")
        
        return response
