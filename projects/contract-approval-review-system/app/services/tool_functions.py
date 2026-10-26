"""需求 2.4.10 的 7 个同步工具函数。

工具保持同步签名，REST 层直接调用；异步只用于“一键审查”流水线。
"""

from __future__ import annotations

from app.services import attachments as attachment_service
from app.services import approvals as approval_service
from app.services import comments as comment_service
from app.services import review as review_service


def list_pending_contract_approvals(limit: int) -> list[dict]:
    """拉取待处理审批单，按 approval_code 去重入库，返回本地任务摘要。"""
    return approval_service.pull_pending(limit)


def get_contract_approval(instance_id: str) -> dict:
    """返回单个审批单详情：审批信息、表单数据、附件信息、当前处理状态。"""
    return approval_service.get_detail(instance_id)


def download_contract_attachment(
    instance_id: str, attachment_id: int, file_name: str
) -> dict:
    """按审批编号和上游附件编号下载合同附件，返回本地路径与校验信息。"""
    return attachment_service.download_attachment(
        instance_id, attachment_id, file_name
    )


def parse_contract_document(document_id: int) -> dict:
    """解析本地附件，输出基本信息、条款、原文片段与位置。"""
    from app.services.parser.service import parse_document

    return parse_document(document_id)


def run_contract_rules(case_id: int) -> dict:
    """执行规则审查，返回命中列表、总风险等级和关注点。"""
    from app.services.rules.engine import run_rules

    return run_rules(case_id)


def save_review_result(
    case_id: int,
    overall_risk_level: str,
    summary_text: str,
    focus_points_json: str | list,
    comment_text: str,
) -> dict:
    """保存审查结果、命中规则和摘要信息。"""
    return review_service.save_review(
        case_id,
        {
            "overall_risk_level": overall_risk_level,
            "summary_text": summary_text,
            "focus_points": focus_points_json,
            "comment_text": comment_text,
        },
    )


def write_approval_comment(instance_id: str, review_id: int) -> dict:
    """将审查意见幂等写回审批评论区，返回回写结果。"""
    return comment_service.write_comment(instance_id, review_id)
