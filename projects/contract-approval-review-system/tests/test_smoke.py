"""框架冒烟测试：常量、资产、应用启动。"""

from __future__ import annotations

import json

import pytest

from app.config import settings
from app.status import ErrorCode, ParseStatus, Stage, TaskStatus, WriteStatus


def test_status_values_match_requirements() -> None:
    assert {item.value for item in TaskStatus} == {
        "pending",
        "parsing",
        "reviewing",
        "blocked",
        "done",
    }
    assert {item.value for item in WriteStatus} == {
        "not_written",
        "writing",
        "success",
        "failed",
    }
    assert Stage.QUEUED.value == "queued"
    assert ParseStatus.PARTIAL.value == "partial"
    assert ErrorCode.SERVICE_INTERRUPTED.value == "SERVICE_INTERRUPTED"


def test_schema_and_seed_assets_exist() -> None:
    assert (settings.base_dir / "app" / "schema.sql").exists()
    assert (settings.base_dir / "app" / "mock_upstream" / "schema.sql").exists()
    rules = json.loads(
        (settings.base_dir / "app" / "seed" / "rules.json").read_text(encoding="utf-8")
    )["rules"]
    assert len(rules) == 14
    categories = {rule["category"] for rule in rules}
    required = {
        "预付款比例",
        "付款周期",
        "自动续约",
        "违约责任",
        "管辖地",
        "主体信息缺失",
        "金额缺失",
        "保密缺失",
        "数据处理",
        "知识产权",
        "验收标准缺失",
    }
    assert required <= categories


def test_app_starts_and_health_works() -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("jinja2")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        page = client.get("/web/pending")
        assert page.status_code == 200
        assert "待办列表" in page.text
