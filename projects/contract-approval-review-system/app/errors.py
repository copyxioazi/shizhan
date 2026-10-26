"""统一异常类型。"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    code = "APP_ERROR"
    status_code = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        **details: Any,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details


class NotImplementedFeature(AppError):
    code = "NOT_IMPLEMENTED"
    status_code = 501


class ToolError(AppError):
    code = "TOOL_ERROR"
    status_code = 400


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404


class UpstreamError(AppError):
    code = "UPSTREAM_ERROR"
    status_code = 502


class BlockedError(AppError):
    code = "BLOCKED"
    status_code = 409
