"""统一响应包络与业务错误码。

接口成功统一返回 ``{"code": 0, "message": "ok", "data": ...}``；
业务失败通过 ``ApiError`` 抛出，由全局异常处理器转换为对应 HTTP 状态码。
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


class ErrorCode:
    OK = 0
    INVALID_CREDENTIALS = 1001
    UNAUTHORIZED = 1002
    FORBIDDEN = 1003
    USER_DISABLED = 1004
    SYSTEM_ALREADY_INITIALIZED = 1005
    SYSTEM_NOT_INITIALIZED = 1006

    PROJECT_NOT_FOUND = 2001
    PROJECT_STATE_CONFLICT = 2002
    PROJECT_CONCURRENCY_LIMIT = 2003
    SOURCE_PATH_INVALID = 2004
    PROJECT_RUNNING_CANNOT_DELETE = 2005
    DELETE_CONFIRM_REQUIRED = 2007
    SOURCE_TYPE_NOT_SUPPORTED = 2008

    ENVIRONMENT_CREATE_FAILED = 3001
    ENVIRONMENT_UNAVAILABLE = 3002
    COMMAND_NOT_ALLOWED = 3003
    COMMAND_TIMEOUT = 3004
    PATH_OUT_OF_SCOPE = 3005
    ENVIRONMENT_STATE_CONFLICT = 3006
    ENVIRONMENT_NOT_FOUND = 3007
    SOURCE_SYNC_FAILED = 3008

    STAGE_STATE_CONFLICT = 4001
    STAGE_TIMEOUT = 4002

    VULNERABILITY_NOT_FOUND = 5001
    INVALID_PATH_ITEM = 5003

    ATTACK_PATH_NOT_FOUND = 6001

    REPORT_NOT_READY = 7001
    REPORT_GENERATE_FAILED = 7002

    CONFIG_INVALID = 8001

    LLM_REQUEST_FAILED = 9001
    WS_UNAUTHORIZED = 9002
    INTERNAL_ERROR = 9999


DEFAULT_MESSAGES: dict[int, str] = {
    ErrorCode.INVALID_CREDENTIALS: "用户名或密码错误",
    ErrorCode.UNAUTHORIZED: "未登录或登录已失效",
    ErrorCode.FORBIDDEN: "无权限访问该资源",
    ErrorCode.USER_DISABLED: "账号已被禁用",
    ErrorCode.SYSTEM_ALREADY_INITIALIZED: "系统已初始化",
    ErrorCode.SYSTEM_NOT_INITIALIZED: "系统尚未初始化",
    ErrorCode.PROJECT_NOT_FOUND: "项目不存在",
    ErrorCode.PROJECT_STATE_CONFLICT: "项目当前状态不允许该操作",
    ErrorCode.PROJECT_CONCURRENCY_LIMIT: "同时运行的项目数已达上限",
    ErrorCode.SOURCE_PATH_INVALID: "源码路径非法或不可读",
    ErrorCode.PROJECT_RUNNING_CANNOT_DELETE: "运行中的项目不能删除",
    ErrorCode.DELETE_CONFIRM_REQUIRED: "删除操作需要确认",
    ErrorCode.SOURCE_TYPE_NOT_SUPPORTED: "本期仅支持本机目录源码",
    ErrorCode.ENVIRONMENT_CREATE_FAILED: "隔离环境创建失败",
    ErrorCode.ENVIRONMENT_UNAVAILABLE: "隔离环境不可用",
    ErrorCode.COMMAND_NOT_ALLOWED: "命令不在白名单内",
    ErrorCode.COMMAND_TIMEOUT: "命令执行超时",
    ErrorCode.PATH_OUT_OF_SCOPE: "路径越界",
    ErrorCode.ENVIRONMENT_STATE_CONFLICT: "隔离环境状态冲突",
    ErrorCode.ENVIRONMENT_NOT_FOUND: "隔离环境不存在",
    ErrorCode.SOURCE_SYNC_FAILED: "源码同步到 VM 失败",
    ErrorCode.STAGE_STATE_CONFLICT: "阶段状态冲突",
    ErrorCode.STAGE_TIMEOUT: "阶段执行超时",
    ErrorCode.VULNERABILITY_NOT_FOUND: "漏洞不存在",
    ErrorCode.INVALID_PATH_ITEM: "攻击路径步骤非法",
    ErrorCode.ATTACK_PATH_NOT_FOUND: "攻击路径不存在",
    ErrorCode.REPORT_NOT_READY: "报告尚未生成",
    ErrorCode.REPORT_GENERATE_FAILED: "报告生成失败",
    ErrorCode.CONFIG_INVALID: "配置项或配置值非法",
    ErrorCode.LLM_REQUEST_FAILED: "LLM 调用失败",
    ErrorCode.INTERNAL_ERROR: "服务内部错误",
}


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: int,
        message: str | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(message or DEFAULT_MESSAGES.get(code, "请求失败"))
        self.status_code = status_code
        self.code = code
        self.message = message or DEFAULT_MESSAGES.get(code, "请求失败")
        self.data = data


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    return {"code": ErrorCode.OK, "message": message, "data": data}


def error_response(status_code: int, code: int, message: str, data: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "data": data},
    )
