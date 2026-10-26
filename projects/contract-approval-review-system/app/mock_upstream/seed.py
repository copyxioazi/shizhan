"""Mock 审批单与附件种子数据。

附件元数据来自 ``sample_contracts/`` 下由 ``scripts/generate_samples.py``
确定性生成的文件；种子只记录路径、SHA-256 与大小，不复制文件。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import BASE_DIR, settings
from app.db import transaction
from app.errors import ToolError

FIXED_TIME = "2026-03-01T09:00:00+00:00"

APPROVALS: list[dict] = [
    {
        "approval_code": "APV-2026-001",
        "approval_title": "设备采购合同审批",
        "applicant_name": "张伟",
        "applied_at": "2026-03-01T09:00:00+00:00",
        "status": "pending",
        "form_data": {
            "department": "采购部",
            "contract_type": "设备采购",
            "counterparty": "苏州远方设备制造有限公司",
            "budget_amount": "1200000",
            "currency": "CNY",
        },
        "attachments": [
            {
                "file_name": "设备采购合同.pdf",
                "sample": "apv_2026_001_purchase.pdf",
                "file_type": "pdf",
                "sort_order": 1,
                "available": 1,
            },
            {
                "file_name": "报价单.pdf",
                "sample": "apv_2026_001_quotation.pdf",
                "file_type": "pdf",
                "sort_order": 2,
                "available": 1,
            },
        ],
    },
    {
        "approval_code": "APV-2026-002",
        "approval_title": "技术服务合同审批",
        "applicant_name": "李娜",
        "applied_at": "2026-04-02T10:30:00+00:00",
        "status": "pending",
        "form_data": {
            "department": "数字化中心",
            "contract_type": "技术服务",
            "counterparty": "南京云图信息技术有限公司",
            "budget_amount": "480000",
            "currency": "CNY",
        },
        "attachments": [
            {
                "file_name": "技术服务合同.docx",
                "sample": "apv_2026_002_service.docx",
                "file_type": "docx",
                "sort_order": 1,
                "available": 1,
            }
        ],
    },
    {
        "approval_code": "APV-2026-003",
        "approval_title": "保密协议审批",
        "applicant_name": "王强",
        "applied_at": "2026-04-10T14:00:00+00:00",
        "status": "pending",
        "form_data": {
            "department": "研发中心",
            "contract_type": "保密协议",
            "counterparty": "上海青禾咨询有限公司",
            "budget_amount": "50000",
            "currency": "CNY",
            "note": "对方仅提供扫描件",
        },
        "attachments": [
            {
                "file_name": "保密协议扫描件.png",
                "sample": "apv_2026_003_scan.png",
                "file_type": "png",
                "sort_order": 1,
                "available": 1,
            }
        ],
    },
    {
        "approval_code": "APV-2026-004",
        "approval_title": "系统运维合同审批",
        "applicant_name": "赵敏",
        "applied_at": "2026-04-15T11:15:00+00:00",
        "status": "pending",
        "form_data": {
            "department": "信息部",
            "contract_type": "运维服务",
            "counterparty": "杭州衡远网络科技有限公司",
            "budget_amount": "360000",
            "currency": "CNY",
            "note": "演示附件缺失与恢复",
        },
        "attachments": [
            {
                "file_name": "系统运维合同.docx",
                "sample": "apv_2026_004_hidden.docx",
                "file_type": "docx",
                "sort_order": 1,
                "available": 0,
            }
        ],
    },
]

FILE_TYPES = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpeg",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sample_path(sample: str) -> Path:
    path = settings.sample_dir / sample
    if not path.is_file():
        raise ToolError(
            f"示例合同缺失：{path.name}，请先运行 scripts/generate_samples.py",
            code="SAMPLE_MISSING",
            sample=str(path),
        )
    return path


def seed_mock_data(reset: bool = False) -> dict:
    """写入 4 个审批单、附件元数据和故障开关。"""
    with transaction(settings.mock_db_path) as conn:
        if reset:
            for table in (
                "upstream_comments",
                "upstream_faults",
                "upstream_attachments",
                "upstream_approvals",
            ):
                conn.execute(f"DELETE FROM {table}")
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN "
                "('upstream_comments','upstream_attachments')"
            )
        else:
            existing = conn.execute(
                "SELECT COUNT(*) FROM upstream_approvals"
            ).fetchone()[0]
            if existing:
                return {
                    "seeded": False,
                    "reason": "Mock 审批单已存在，跳过种子写入",
                    "approvals": existing,
                }

    now = _now()
    approval_count = 0
    attachment_count = 0
    with transaction(settings.mock_db_path) as conn:
        for item in APPROVALS:
            conn.execute(
                """
                INSERT INTO upstream_approvals
                    (approval_code, approval_title, applicant_name, applied_at,
                     form_data_json, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(approval_code) DO UPDATE SET
                    approval_title = excluded.approval_title,
                    applicant_name = excluded.applicant_name,
                    applied_at = excluded.applied_at,
                    form_data_json = excluded.form_data_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    item["approval_code"],
                    item["approval_title"],
                    item["applicant_name"],
                    item["applied_at"],
                    json.dumps(item["form_data"], ensure_ascii=False),
                    item["status"],
                    now,
                ),
            )
            approval_count += 1
            for attachment in item["attachments"]:
                sample_path = _sample_path(attachment["sample"])
                stored_path = sample_path.relative_to(BASE_DIR).as_posix()
                conn.execute(
                    """
                    INSERT INTO upstream_attachments
                        (approval_code, file_name, file_type, stored_path,
                         sha256, file_size, sort_order, available, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["approval_code"],
                        attachment["file_name"],
                        attachment.get("file_type")
                        or FILE_TYPES.get(sample_path.suffix.lower(), "unknown"),
                        stored_path,
                        _sha256(sample_path),
                        sample_path.stat().st_size,
                        attachment["sort_order"],
                        attachment["available"],
                        now,
                    ),
                )
                attachment_count += 1

        for scope in ("detail", "download", "comment"):
            conn.execute(
                """
                INSERT INTO upstream_faults (scope, enabled, http_status)
                VALUES (?, 0, 500)
                ON CONFLICT(scope) DO NOTHING
                """,
                (scope,),
            )

    return {
        "seeded": True,
        "approvals": approval_count,
        "attachments": attachment_count,
        "seeded_at": FIXED_TIME,
    }
