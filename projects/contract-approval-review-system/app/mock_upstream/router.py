"""Mock 审批系统 HTTP 路由。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.mock_upstream import service

router = APIRouter(prefix="/mock-upstream", tags=["mock-upstream"])

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


class CommentPayload(BaseModel):
    content: str
    idempotency_key: str


class FaultPayload(BaseModel):
    scope: str  # detail | download | comment
    enabled: bool = True
    http_status: int = 500


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mock-upstream", "stage": "ready"}


@router.get("/approvals/pending")
def list_pending(limit: int = 50) -> dict:
    return {"success": True, "data": service.list_pending(limit)}


@router.get("/approvals/{instance_id}")
def get_approval(instance_id: str) -> dict:
    return {"success": True, "data": service.get_approval(instance_id)}


@router.get("/approvals/{instance_id}/attachments/{attachment_id}/file")
def get_attachment_file(instance_id: str, attachment_id: int) -> FileResponse:
    info = service.get_attachment_file(instance_id, attachment_id)
    return FileResponse(
        path=info["path"],
        media_type=MEDIA_TYPES.get(info["file_type"], "application/octet-stream"),
        filename=info["file_name"],
        headers={
            "X-Checksum-SHA256": info["sha256"],
            "X-Attachment-Id": str(info["attachment_id"]),
        },
    )


@router.post("/approvals/{instance_id}/comments")
def add_comment(instance_id: str, payload: CommentPayload) -> dict:
    return {
        "success": True,
        "data": service.add_comment(
            instance_id, payload.content, payload.idempotency_key
        ),
    }


@router.get("/approvals/{instance_id}/comments")
def list_comments(instance_id: str) -> dict:
    return {"success": True, "data": service.list_comments(instance_id)}


@router.post("/admin/attachments/{attachment_id}/restore")
def restore_attachment(attachment_id: int) -> dict:
    return {"success": True, "data": service.restore_attachment(attachment_id)}


@router.post("/admin/faults")
def set_fault(payload: FaultPayload) -> dict:
    return {
        "success": True,
        "data": service.set_fault(payload.scope, payload.enabled, payload.http_status),
    }


@router.post("/admin/reset")
def reset() -> dict:
    return {"success": True, "data": service.reset()}
