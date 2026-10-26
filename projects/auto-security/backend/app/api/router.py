"""汇总全部路由（统一挂载到 /api）。"""

from fastapi import APIRouter

from app.api import auth, config, monitor, projects, results, ws

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(results.router)
api_router.include_router(monitor.router)
api_router.include_router(config.router)
api_router.include_router(ws.router)
