"""管理端规则 CRUD 测试。"""

from __future__ import annotations

import time

import httpx
import pytest

pytestmark = pytest.mark.integration


def call(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    payload = response.json()
    if response.status_code >= 400 or payload.get("success") is False:
        raise AssertionError(f"{path} -> {response.status_code} {payload}")
    return payload["data"]


def wait_terminal(client: httpx.Client, task_id: int, timeout: float = 240.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = call(client, "GET", f"/api/tasks/{task_id}/status")
        if status["terminal"]:
            return status
        time.sleep(0.3)
    raise AssertionError("任务未在超时内结束")


def test_rule_crud(live_server: httpx.Client) -> None:
    rules = call(live_server, "GET", "/api/admin/rules")
    assert len(rules) == 14

    payload = {
        "rule_code": "R900",
        "rule_name": "测试关键词规则",
        "risk_level": "low",
        "rule_status": "enabled",
        "match_mode": "keyword",
        "match_text": "测试关键词",
        "suggestion_text": "测试建议",
        "category": "测试",
        "sort_order": 900,
    }
    created = call(live_server, "POST", "/api/admin/rules", json=payload)
    rule_id = created["id"]
    assert created["match_text"] == "测试关键词"

    updated_payload = dict(payload, risk_level="high", rule_status="disabled")
    updated = call(
        live_server, "PUT", f"/api/admin/rules/{rule_id}", json=updated_payload
    )
    assert updated["risk_level"] == "high"
    assert updated["rule_status"] == "disabled"

    response = live_server.delete(f"/api/admin/rules/{rule_id}")
    assert response.status_code == 204
    rules = call(live_server, "GET", "/api/admin/rules")
    assert all(rule["id"] != rule_id for rule in rules)


def test_invalid_rule_is_rejected(live_server: httpx.Client) -> None:
    payload = {
        "rule_code": "R901",
        "rule_name": "非法正则",
        "risk_level": "high",
        "match_mode": "regex",
        "match_text": "(",
        "suggestion_text": "测试",
    }
    response = live_server.post("/api/admin/rules", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_RULE"


def test_referenced_rule_cannot_be_hard_deleted(live_server: httpx.Client) -> None:
    pull = call(
        live_server,
        "POST",
        "/api/tools/list_pending_contract_approvals",
        params={"limit": 50},
    )
    tasks = {item["approval_code"]: item for item in pull}
    case_id = tasks["APV-2026-001"]["case_id"]
    call(live_server, "POST", f"/api/tasks/{case_id}/full-review")
    assert wait_terminal(live_server, case_id)["task_status"] == "done"

    rules = call(live_server, "GET", "/api/admin/rules")
    rule = next(item for item in rules if item["rule_code"] == "R001")
    response = live_server.delete(f"/api/admin/rules/{rule['id']}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RULE_IN_USE"
