"""完整闭环演示。

流程：去重拉取 → 一键审查四类合同 → 阻塞恢复重试 → 幂等回写 → 汇总。
脚本会复用已运行的服务；若目标地址无服务，则自动启动一个 uvicorn 进程。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def _call(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError(f"{path} 返回非 JSON：{response.status_code}")
    if response.status_code >= 400 or payload.get("success") is False:
        raise RuntimeError(f"{path} -> {response.status_code} {payload}")
    return payload.get("data", payload)


def _health(client: httpx.Client) -> bool:
    try:
        return client.get("/health").status_code == 200
    except Exception:
        return False


def _wait_server(client: httpx.Client, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _health(client):
            return
        time.sleep(0.3)
    raise RuntimeError("服务启动超时")


def _poll(client: httpx.Client, task_id: int, timeout: float = 240.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = _call(client, "GET", f"/api/tasks/{task_id}/status")
        if status["terminal"]:
            return status
        time.sleep(0.5)
    raise RuntimeError(f"任务 {task_id} 未在超时内结束")


def _review(
    client: httpx.Client,
    case_id: int,
    approval_code: str,
    expected_risk: str,
    expected_parse: str,
) -> dict:
    _call(client, "POST", f"/api/tasks/{case_id}/full-review")
    status = _poll(client, case_id)
    if status["task_status"] != "done":
        raise RuntimeError(
            f"{approval_code} 未完成：{status['task_status']} "
            f"{status['last_error_code']} {status['last_error']}"
        )
    detail = _call(client, "GET", f"/api/tools/get_contract_approval/{approval_code}")
    review = detail.get("review") or {}
    parse = detail.get("parse") or {}
    if review.get("overall_risk_level") != expected_risk:
        raise RuntimeError(
            f"{approval_code} 风险不符：{review.get('overall_risk_level')} != {expected_risk}"
        )
    if parse.get("parse_status") != expected_parse:
        raise RuntimeError(
            f"{approval_code} 解析状态不符：{parse.get('parse_status')} != {expected_parse}"
        )
    print(
        f"  {approval_code}: {status['task_status']} / {status['write_status']} "
        f"| parse={parse.get('parse_status')} ocr={parse.get('ocr_used')} "
        f"| risk={review.get('overall_risk_level')} "
        f"| focus={len(review.get('focus_points') or [])}"
    )
    return detail


def run_demo(base_url: str = "http://127.0.0.1:8000", reset: bool = True) -> dict:
    process: subprocess.Popen | None = None
    if reset:
        from init_db import init_databases

        print("重置演示数据（本地库 + Mock 库 + 示例合同）…")
        init_databases(reset=True, seed_rule_data=True, seed_mock=True, generate=True)

    with httpx.Client(base_url=base_url, timeout=120, trust_env=False) as client:
        if not _health(client):
            port = urlparse(base_url).port or 8000
            env = dict(os.environ, UPSTREAM_BASE_URL=base_url)
            print(f"启动服务 {base_url} …")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                ],
                cwd=str(ROOT),
                env=env,
            )
            _wait_server(client)

        try:
            print("\n[1] 连续拉取两次，验证去重")
            first = _call(
                client,
                "POST",
                "/api/tools/list_pending_contract_approvals",
                params={"limit": 50},
            )
            second = _call(
                client,
                "POST",
                "/api/tools/list_pending_contract_approvals",
                params={"limit": 50},
            )
            created_first = sum(1 for item in first if item["created"])
            created_second = sum(1 for item in second if item["created"])
            if created_first != 4 or created_second != 0:
                raise RuntimeError(
                    f"去重结果不符：first={created_first}, second={created_second}"
                )
            tasks = {item["approval_code"]: item["case_id"] for item in first}
            print(f"  新增 {created_first} 个，第二次新增 {created_second} 个")

            print("\n[2] 一键审查 4 类合同")
            detail_001 = _review(
                client, tasks["APV-2026-001"], "APV-2026-001", "high", "success"
            )
            _review(client, tasks["APV-2026-002"], "APV-2026-002", "medium", "partial")
            _review(client, tasks["APV-2026-003"], "APV-2026-003", "low", "partial")

            print("\n[3] 缺失附件 → blocked → restore → retry")
            case_004 = tasks["APV-2026-004"]
            _call(client, "POST", f"/api/tasks/{case_004}/full-review")
            blocked = _poll(client, case_004)
            if blocked["last_error_code"] != "MISSING_ATTACHMENT":
                raise RuntimeError(f"APV-2026-004 未按预期阻塞：{blocked}")
            print(
                f"  APV-2026-004: {blocked['task_status']} / {blocked['last_error_code']}"
            )
            _call(client, "POST", "/mock-upstream/admin/attachments/5/restore")
            retry = _call(client, "POST", f"/api/tasks/{case_004}/retry")
            print(f"  重试入队：resume={retry['resume_stage']} retry={retry['retry_count']}")
            done = _poll(client, case_004)
            if done["task_status"] != "done":
                raise RuntimeError(f"APV-2026-004 重试失败：{done}")
            print(f"  APV-2026-004: {done['task_status']} / {done['write_status']}")

            print("\n[4] 重复回写，验证幂等")
            review_id = detail_001["review"]["review_id"]
            duplicate = _call(
                client,
                "POST",
                "/api/tools/write_approval_comment",
                json={"instance_id": "APV-2026-001", "review_id": review_id},
            )
            comments = _call(
                client, "GET", "/mock-upstream/approvals/APV-2026-001/comments"
            )
            if not duplicate.get("short_circuited") or len(comments) != 1:
                raise RuntimeError("回写幂等校验失败")
            print(f"  本地短路={duplicate['short_circuited']}，上游评论数={len(comments)}")

            print("\n[5] 最终任务表")
            rows = _call(client, "GET", "/api/tasks")
            for row in sorted(rows, key=lambda item: item["id"]):
                print(
                    f"  #{row['id']} {row['approval_code']} "
                    f"{row['task_status']}/{row['write_status']} stage={row['stage']}"
                )

            total_comments = sum(
                len(
                    _call(
                        client,
                        "GET",
                        f"/mock-upstream/approvals/{item['approval_code']}/comments",
                    )
                )
                for item in rows
            )
            print(f"\nMock 评论总数：{total_comments}")
            return {
                "tasks": len(rows),
                "comments": total_comments,
                "deduplicated": created_second == 0,
            }
        finally:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description="合同审批审查完整闭环演示")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--no-reset", action="store_true", help="不重置演示数据")
    args = parser.parse_args()
    try:
        result = run_demo(args.base_url, reset=not args.no_reset)
    except Exception as exc:  # noqa: BLE001 - 演示脚本失败需非零退出
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
    print("\n演示完成：" + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
