"""异步任务、轮询与管理入口。"""

from __future__ import annotations

from fastapi import APIRouter

from app.services import contract_content as content_service
from app.services import tasks as task_service

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
def list_tasks() -> dict:
    return {"success": True, "data": task_service.list_tasks()}


@router.get("/{task_id}")
def get_task(task_id: int) -> dict:
    return {"success": True, "data": task_service.get_task(task_id)}


@router.get("/{task_id}/status")
def get_task_status(task_id: int) -> dict:
    return {"success": True, "data": task_service.get_task_status(task_id)}


@router.get("/{task_id}/content")
def get_task_content(task_id: int) -> dict:
    """解析后的合同全文、基本信息、条款和命中位置。"""
    return {
        "success": True,
        "data": content_service.get_contract_content(task_id),
    }


@router.post("/{task_id}/full-review", status_code=202)
def full_review(task_id: int) -> dict:
    return {"success": True, "data": task_service.enqueue_full_review(task_id)}


@router.post("/{task_id}/retry", status_code=202)
def retry(task_id: int) -> dict:
    return {"success": True, "data": task_service.enqueue_retry(task_id)}
