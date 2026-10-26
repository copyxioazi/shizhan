"""闭环 E2E 测试：拉取 → 一键审查 → 回写 → 阻塞重试。"""

from __future__ import annotations

import time

import httpx
import pytest

pytestmark = pytest.mark.e2e


def call(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    payload = response.json()
    if response.status_code >= 400 or payload.get("success") is False:
        raise AssertionError(f"{path} -> {response.status_code} {payload}")
    return payload["data"]


def pull(client: httpx.Client) -> dict[str, dict]:
    items = call(
        client,
        "POST",
        "/api/tools/list_pending_contract_approvals",
        params={"limit": 50},
    )
    return {item["approval_code"]: item for item in items}


def wait_terminal(client: httpx.Client, task_id: int, timeout: float = 240.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = call(client, "GET", f"/api/tasks/{task_id}/status")
        if last["terminal"]:
            return last
        time.sleep(0.3)
    raise AssertionError(f"任务 {task_id} 未在超时内结束：{last}")


def test_full_review_high_risk_pdf(live_server: httpx.Client) -> None:
    tasks = pull(live_server)
    case_id = tasks["APV-2026-001"]["case_id"]

    started = call(live_server, "POST", f"/api/tasks/{case_id}/full-review")
    assert started["queued"] is True
    status = wait_terminal(live_server, case_id)
    assert status["task_status"] == "done"
    assert status["write_status"] == "success"
    assert status["stage"] == "done"

    detail = call(
        live_server, "GET", "/api/tools/get_contract_approval/APV-2026-001"
    )
    assert detail["parse"]["parse_status"] == "success"
    assert detail["review"]["overall_risk_level"] == "high"
    assert detail["review"]["focus_points"]

    content = call(live_server, "GET", f"/api/tasks/{case_id}/content")
    assert content["parse_status"] == "success"
    assert "设备采购合同" in content["text_content"]
    assert content["basic_info"]["contract_no"]["value"] == "CG-2026-001"
    assert content["clause_info"]["payment"]["status"] == "found"
    assert len(content["hits"]) == 4
    assert content["hits"][0]["evidence_text"]

    comments = call(
        live_server, "GET", "/mock-upstream/approvals/APV-2026-001/comments"
    )
    assert len(comments) == 1

    review_id = detail["review"]["review_id"]
    duplicate = call(
        live_server,
        "POST",
        "/api/tools/write_approval_comment",
        json={"instance_id": "APV-2026-001", "review_id": review_id},
    )
    assert duplicate["short_circuited"] is True
    comments = call(
        live_server, "GET", "/mock-upstream/approvals/APV-2026-001/comments"
    )
    assert len(comments) == 1


def test_scan_ocr_partial_low_risk(live_server: httpx.Client) -> None:
    tasks = pull(live_server)
    case_id = tasks["APV-2026-003"]["case_id"]
    call(live_server, "POST", f"/api/tasks/{case_id}/full-review")
    status = wait_terminal(live_server, case_id)
    assert status["task_status"] == "done"

    detail = call(
        live_server, "GET", "/api/tools/get_contract_approval/APV-2026-003"
    )
    assert detail["parse"]["ocr_used"] is True
    assert detail["parse"]["parse_status"] == "partial"
    assert detail["review"]["overall_risk_level"] == "low"
    assert "解析完整度不足" in detail["review"]["focus_points"][0]


def test_missing_attachment_blocked_then_retry(live_server: httpx.Client) -> None:
    tasks = pull(live_server)
    case_id = tasks["APV-2026-004"]["case_id"]

    call(live_server, "POST", f"/api/tasks/{case_id}/full-review")
    status = wait_terminal(live_server, case_id)
    assert status["task_status"] == "blocked"
    assert status["last_error_code"] == "MISSING_ATTACHMENT"
    assert status["stage"] == "download"

    call(live_server, "POST", "/mock-upstream/admin/attachments/5/restore")
    retry = call(live_server, "POST", f"/api/tasks/{case_id}/retry")
    assert retry["queued"] is True
    assert retry["resume_stage"] == "download"
    assert retry["retry_count"] == 1

    status = wait_terminal(live_server, case_id)
    assert status["task_status"] == "done"
    assert status["write_status"] == "success"


def test_content_before_parse_is_empty(live_server: httpx.Client) -> None:
    tasks = pull(live_server)
    case_id = tasks["APV-2026-002"]["case_id"]
    content = call(live_server, "GET", f"/api/tasks/{case_id}/content")
    assert content["parse_status"] is None
    assert content["text_content"] == ""
    assert content["hits"] == []


def test_concurrent_full_review_is_deduplicated(live_server: httpx.Client) -> None:
    tasks = pull(live_server)
    case_id = tasks["APV-2026-002"]["case_id"]

    first = call(live_server, "POST", f"/api/tasks/{case_id}/full-review")
    second = call(live_server, "POST", f"/api/tasks/{case_id}/full-review")
    assert [first["queued"], second["queued"]].count(True) == 1
    assert second["reason"] in {
        "already_in_progress",
        "duplicate_inflight",
        "already_done",
    }

    status = wait_terminal(live_server, case_id)
    assert status["task_status"] == "done"
