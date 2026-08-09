"""自定义异常，带错误码和 HTTP 状态码，中间件会统一处理"""

from typing import Any


class AppError(Exception):
    """业务异常基类，子类可以覆盖 code 和 status_code"""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500
    detail: str | None = None

    def __init__(self, detail: str | None = None, **extra: Any):
        self.detail = detail
        self.extra = extra
        super().__init__(detail or self.code)
