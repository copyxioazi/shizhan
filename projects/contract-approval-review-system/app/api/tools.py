"""7 个同步工具的 REST 包装。"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services import tool_functions as svc

router = APIRouter(prefix="/api/tools", tags=["tools"])


class DownloadAttachmentRequest(BaseModel):
    instance_id: str
    attachment_id: int
    file_name: str


class ParseDocumentRequest(BaseModel):
    document_id: int


class RunRulesRequest(BaseModel):
    case_id: int


class SaveReviewRequest(BaseModel):
    case_id: int
    overall_risk_level: str
    summary_text: str
    focus_points_json: list[str] | str
    comment_text: str


class WriteCommentRequest(BaseModel):
    instance_id: str
    review_id: int


@router.post("/list_pending_contract_approvals")
def list_pending_contract_approvals(
    limit: int = Query(default=50, ge=1, le=200)
) -> dict:
    return {"success": True, "data": svc.list_pending_contract_approvals(limit)}


@router.get("/get_contract_approval/{instance_id}")
def get_contract_approval(instance_id: str) -> dict:
    return {"success": True, "data": svc.get_contract_approval(instance_id)}


@router.post("/download_contract_attachment")
def download_contract_attachment(payload: DownloadAttachmentRequest) -> dict:
    return {
        "success": True,
        "data": svc.download_contract_attachment(
            payload.instance_id, payload.attachment_id, payload.file_name
        ),
    }


@router.post("/parse_contract_document")
def parse_contract_document(payload: ParseDocumentRequest) -> dict:
    return {"success": True, "data": svc.parse_contract_document(payload.document_id)}


@router.post("/run_contract_rules")
def run_contract_rules(payload: RunRulesRequest) -> dict:
    return {"success": True, "data": svc.run_contract_rules(payload.case_id)}


@router.post("/save_review_result")
def save_review_result(payload: SaveReviewRequest) -> dict:
    return {
        "success": True,
        "data": svc.save_review_result(
            payload.case_id,
            payload.overall_risk_level,
            payload.summary_text,
            payload.focus_points_json,
            payload.comment_text,
        ),
    }


@router.post("/write_approval_comment")
def write_approval_comment(payload: WriteCommentRequest) -> dict:
    return {
        "success": True,
        "data": svc.write_approval_comment(payload.instance_id, payload.review_id),
    }
