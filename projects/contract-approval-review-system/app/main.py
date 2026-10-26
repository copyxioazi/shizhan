"""FastAPI 应用入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, tasks, tools
from app.config import settings
from app.errors import AppError, NotImplementedFeature
from app.mock_upstream.router import router as mock_upstream_router
from app.mock_upstream.service import MockUpstreamError
from app.services.queue import get_queue_manager
from app.web.routes import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    # 启动恢复必须在 worker 启动前执行，避免任务卡在中间态。
    from app.services.tasks import recover_interrupted_tasks

    app.state.recovered = recover_interrupted_tasks()

    manager = get_queue_manager()
    await manager.start()
    app.state.queue_manager = manager
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(
    title="合同审批审查系统",
    version="1.0.0",
    description=(
        "合同审批 + 自动审查 + 风险评论回写闭环：拉取去重、PDF/DOCX/OCR 解析、"
        "6 种规则匹配、幂等回写与阻塞重试。"
    ),
    lifespan=lifespan,
)

# 本地开发用：允许 /ui、file:// 预览和本地静态服务器访问 API。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$|^null$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(
    "/static",
    StaticFiles(directory=str(settings.base_dir / "app" / "static")),
    name="static",
)

# 零构建前端控制台：frontend/index.html + style.css + app.js
frontend_dir = settings.base_dir / "frontend"
if frontend_dir.is_dir():
    app.mount(
        "/ui",
        StaticFiles(directory=str(frontend_dir), html=True),
        name="ui",
    )

app.include_router(tools.router)
app.include_router(tasks.router)
app.include_router(admin.router)
app.include_router(mock_upstream_router)
app.include_router(web_router)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {
        "status": "ok",
        "service": "contract-approval-review-system",
        "stage": "closed-loop",
    }


@app.exception_handler(NotImplementedFeature)
async def not_implemented_handler(request: Request, exc: NotImplementedFeature):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {"code": exc.code, "message": str(exc), "details": exc.details},
        },
    )


@app.exception_handler(MockUpstreamError)
async def mock_upstream_error_handler(request: Request, exc: MockUpstreamError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        },
    )


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {"code": exc.code, "message": str(exc), "details": exc.details},
        },
    )
