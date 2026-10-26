"""FastAPI 应用入口。

启动流程：校验配置 -> 创建运行时目录 -> 启动对账 -> 保留清理循环。
停止流程：取消调度任务 -> 取消清理循环 -> 释放数据库连接池。
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import settings
from app.core.database import dispose_engine
from app.core.errors import ApiError, ErrorCode, error_response, ok
from app.core.logging import configure_logging, get_logger
from app.scheduler.manager import scheduler
from app.services.maintenance_service import reconcile_on_startup, retention_loop

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    try:
        await reconcile_on_startup()
    except Exception as exc:  # noqa: BLE001 - 数据库尚未就绪时允许服务启动并返回错误
        logger.error("startup reconciliation failed: %s", exc)
    retention_task = asyncio.create_task(retention_loop(), name="ase-retention")
    logger.info("automated security assessment backend started")
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            await scheduler.shutdown()
        retention_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await retention_task
        await dispose_engine()
        logger.info("automated security assessment backend stopped")


app = FastAPI(
    title="自动化安全评估系统 API",
    version="0.1.0",
    description="项目需求规格说明书 v1.3 对应的后端骨架",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.data)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = []
    for item in exc.errors():
        location = ".".join(str(part) for part in item.get("loc", []) if part != "body")
        details.append(f"{location}: {item.get('msg', '参数非法')}")
    return error_response(422, ErrorCode.INTERNAL_ERROR, "请求参数校验失败：" + "；".join(details))


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return error_response(404, ErrorCode.INTERNAL_ERROR, "接口不存在")
    return error_response(
        exc.status_code, ErrorCode.INTERNAL_ERROR, str(exc.detail)
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error: %s", exc)
    return error_response(500, ErrorCode.INTERNAL_ERROR, "服务内部错误")


@app.get("/healthz", tags=["系统"])
async def healthz():
    return ok({"status": "ok"})


app.include_router(api_router, prefix="/api")
