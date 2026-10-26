"""7 个工具 REST 路由与 Mock 上游闭环测试。

使用临时数据库和真实 uvicorn 回环，验证接口层到服务层的调用边界。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration


def _pull(client: httpx.Client) -> list[dict]:
    response = client.post(
        "/api/tools/list_pending_contract_approvals", params={"limit": 50}
    )
    assert response.status_code == 200
    return response.json()["data"]


def test_pull_is_idempotent(live_server: httpx.Client) -> None:
    first = _pull(live_server)
    second = _pull(live_server)
    assert len(first) == 4
    assert all(item["created"] for item in first)
    assert not any(item["created"] for item in second)
    assert [item["case_id"] for item in first] == [
        item["case_id"] for item in second
    ]


def test_detail_and_download(live_server: httpx.Client) -> None:
    _pull(live_server)
    detail = live_server.get(
        "/api/tools/get_contract_approval/APV-2026-001"
    ).json()["data"]
    assert detail["pulled"] is True
    assert [item["attachment_id"] for item in detail["attachments"]] == [1, 2]

    manifest = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "sample_contracts"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    expected = next(
        item for item in manifest["files"] if item["file"] == "apv_2026_001_purchase.pdf"
    )

    response = live_server.post(
        "/api/tools/download_contract_attachment",
        json={
            "instance_id": "APV-2026-001",
            "attachment_id": 1,
            "file_name": "设备采购合同.pdf",
        },
    )
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["download_status"] == "success"
    assert result["sha256"] == expected["sha256"]
    assert result["file_size"] == expected["file_size"]
    assert result["is_primary"] is True

    secondary = live_server.post(
        "/api/tools/download_contract_attachment",
        json={
            "instance_id": "APV-2026-001",
            "attachment_id": 2,
            "file_name": "报价单.pdf",
        },
    )
    assert secondary.status_code == 200
    assert secondary.json()["data"]["is_primary"] is False

    detail = live_server.get(
        "/api/tools/get_contract_approval/APV-2026-001"
    ).json()["data"]
    primary = [item for item in detail["attachments"] if item["is_primary"]]
    assert [item["attachment_id"] for item in primary] == [1]


def test_missing_attachment_is_blocked(live_server: httpx.Client) -> None:
    tasks = {item["approval_code"]: item for item in _pull(live_server)}
    response = live_server.post(
        "/api/tools/download_contract_attachment",
        json={
            "instance_id": "APV-2026-004",
            "attachment_id": 5,
            "file_name": "系统运维合同.docx",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MISSING_ATTACHMENT"

    status = live_server.get(
        f"/api/tasks/{tasks['APV-2026-004']['case_id']}/status"
    ).json()["data"]
    assert status["task_status"] == "blocked"
    assert status["last_error_code"] == "MISSING_ATTACHMENT"
    assert status["stage"] == "download"


def test_save_and_write_comment_idempotent(live_server: httpx.Client) -> None:
    tasks = {item["approval_code"]: item for item in _pull(live_server)}
    case_id = tasks["APV-2026-001"]["case_id"]

    saved = live_server.post(
        "/api/tools/save_review_result",
        json={
            "case_id": case_id,
            "overall_risk_level": "high",
            "summary_text": "高风险审查结果",
            "focus_points_json": ["预付款比例过高"],
            "comment_text": "【合同审查结论】整体风险：高风险",
        },
    )
    assert saved.status_code == 200
    review_id = saved.json()["data"]["review_id"]

    first = live_server.post(
        "/api/tools/write_approval_comment",
        json={"instance_id": "APV-2026-001", "review_id": review_id},
    )
    assert first.status_code == 200
    assert first.json()["data"]["write_status"] == "success"

    second = live_server.post(
        "/api/tools/write_approval_comment",
        json={"instance_id": "APV-2026-001", "review_id": review_id},
    )
    assert second.status_code == 200
    assert second.json()["data"]["short_circuited"] is True

    comments = live_server.get(
        "/mock-upstream/approvals/APV-2026-001/comments"
    ).json()["data"]
    assert len(comments) == 1

    status = live_server.get(f"/api/tasks/{case_id}/status").json()["data"]
    assert status["task_status"] == "done"
    assert status["write_status"] == "success"


def test_comment_failure_then_retry(live_server: httpx.Client) -> None:
    tasks = {item["approval_code"]: item for item in _pull(live_server)}
    case_id = tasks["APV-2026-002"]["case_id"]
    saved = live_server.post(
        "/api/tools/save_review_result",
        json={
            "case_id": case_id,
            "overall_risk_level": "medium",
            "summary_text": "中风险审查结果",
            "focus_points_json": ["账期过长"],
            "comment_text": "【合同审查结论】整体风险：中风险",
        },
    )
    review_id = saved.json()["data"]["review_id"]

    live_server.post(
        "/mock-upstream/admin/faults",
        json={"scope": "comment", "enabled": True, "http_status": 503},
    )
    failed = live_server.post(
        "/api/tools/write_approval_comment",
        json={"instance_id": "APV-2026-002", "review_id": review_id},
    )
    assert failed.status_code == 409
    assert failed.json()["error"]["code"] == "COMMENT_WRITE_FAILED"

    status = live_server.get(f"/api/tasks/{case_id}/status").json()["data"]
    assert status["task_status"] == "blocked"
    assert status["write_status"] == "failed"

    live_server.post(
        "/mock-upstream/admin/faults",
        json={"scope": "comment", "enabled": False, "http_status": 500},
    )
    retried = live_server.post(
        "/api/tools/write_approval_comment",
        json={"instance_id": "APV-2026-002", "review_id": review_id},
    )
    assert retried.status_code == 200
    assert retried.json()["data"]["write_status"] == "success"


def test_restore_attachment_allows_download(live_server: httpx.Client) -> None:
    _pull(live_server)
    restored = live_server.post(
        "/mock-upstream/admin/attachments/5/restore"
    )
    assert restored.status_code == 200
    assert restored.json()["data"]["available"] is True

    response = live_server.post(
        "/api/tools/download_contract_attachment",
        json={
            "instance_id": "APV-2026-004",
            "attachment_id": 5,
            "file_name": "系统运维合同.docx",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["download_status"] == "success"
