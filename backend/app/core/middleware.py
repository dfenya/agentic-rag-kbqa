"""FastAPI 中间件：请求 ID、访问日志、异常处理"""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.exceptions import AppError

logger = structlog.get_logger()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """给每个请求加 X-Request-ID，方便日志追踪"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """记录每个请求的方法、路径、状态码和耗时"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "access",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response


async def error_handler(request: Request, exc: Exception) -> JSONResponse:
    """把 AppError 和其他异常转成 RFC 9457 格式的错误响应"""
    if isinstance(exc, AppError):
        status = exc.status_code
        body = {"error": {"code": exc.code, "message": str(exc.detail or exc)}}
        if exc.extra:
            body["error"]["detail"] = exc.extra
    else:
        logger.exception("Unhandled server error", path=request.url.path)
        status = 500
        body = {"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}}
    return JSONResponse(status_code=status, content=body)


def register_middleware(app):
    """按顺序注册中间件和异常处理器"""
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_exception_handler(AppError, error_handler)
    app.add_exception_handler(Exception, error_handler)
