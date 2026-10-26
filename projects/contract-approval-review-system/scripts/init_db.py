"""初始化本地审查库与 Mock 上游库。

用法：
    .venv/Scripts/python.exe scripts/init_db.py
    .venv/Scripts/python.exe scripts/init_db.py --reset --seed-rules
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.db import executescript_file, table_names


def _remove_sqlite_files(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()


def seed_rules(conn: sqlite3.Connection) -> int:
    data = json.loads((ROOT / "app" / "seed" / "rules.json").read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for item in data["rules"]:
        match_text: Any = item["match_text"]
        if not isinstance(match_text, str):
            match_text = json.dumps(match_text, ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO review_rules
                (rule_code, rule_name, risk_level, rule_status, match_mode,
                 match_text, suggestion_text, updated_at, category, created_at, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_code) DO UPDATE SET
                rule_name = excluded.rule_name,
                risk_level = excluded.risk_level,
                rule_status = excluded.rule_status,
                match_mode = excluded.match_mode,
                match_text = excluded.match_text,
                suggestion_text = excluded.suggestion_text,
                category = excluded.category,
                sort_order = excluded.sort_order,
                updated_at = excluded.updated_at
            """,
            (
                item["rule_code"],
                item["rule_name"],
                item["risk_level"],
                item.get("rule_status", "enabled"),
                item["match_mode"],
                match_text,
                item["suggestion_text"],
                now,
                item.get("category"),
                now,
                item.get("sort_order", 0),
            ),
        )
        count += 1
    return count


def samples_ready() -> bool:
    manifest_path = settings.sample_dir / "manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError:
        return False
    if not manifest.get("generated"):
        return False
    return all(
        (settings.sample_dir / item["file"]).is_file()
        for item in manifest.get("files", [])
    )


def init_databases(
    reset: bool = False,
    seed_rule_data: bool = True,
    seed_mock: bool = True,
    generate: bool = True,
) -> dict:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if reset:
        _remove_sqlite_files(settings.local_db_path)
        _remove_sqlite_files(settings.mock_db_path)

    sample_result = {"generated": False}
    if generate and (reset or not samples_ready()):
        scripts_dir = str(ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from generate_samples import generate_samples

        sample_result = generate_samples(settings.sample_dir)

    mock = sqlite3.connect(settings.mock_db_path)
    try:
        executescript_file(mock, ROOT / "app" / "mock_upstream" / "schema.sql")
        mock.commit()
        mock_tables = sorted(table_names(mock))
    finally:
        mock.close()

    mock_seed = {"seeded": False}
    if seed_mock:
        from app.mock_upstream.seed import seed_mock_data

        mock_seed = seed_mock_data(reset=reset)

    local = sqlite3.connect(settings.local_db_path)
    try:
        executescript_file(local, ROOT / "app" / "schema.sql")
        local.commit()
        local_tables = sorted(table_names(local))
        rule_count = seed_rules(local) if seed_rule_data else 0
        local.commit()
    finally:
        local.close()

    return {
        "local_db": str(settings.local_db_path),
        "local_tables": local_tables,
        "rules_seeded": rule_count,
        "mock_db": str(settings.mock_db_path),
        "mock_tables": mock_tables,
        "samples": sample_result,
        "mock_seed": mock_seed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化合同审批审查系统数据库")
    parser.add_argument("--reset", action="store_true", help="删除现有数据库后重建")
    parser.add_argument(
        "--seed-rules", dest="seed_rules", action="store_true", default=True,
        help="写入 14 条种子规则（默认开启）",
    )
    parser.add_argument(
        "--no-seed-rules", dest="seed_rules", action="store_false",
        help="不写入种子规则",
    )
    parser.add_argument(
        "--seed-mock", dest="seed_mock", action="store_true", default=True,
        help="写入 4 个 Mock 审批单（默认开启）",
    )
    parser.add_argument(
        "--no-seed-mock", dest="seed_mock", action="store_false",
        help="不写入 Mock 种子数据",
    )
    parser.add_argument(
        "--skip-samples", dest="generate", action="store_false", default=True,
        help="不检查/生成示例合同",
    )
    args = parser.parse_args()
    result = init_databases(
        reset=args.reset,
        seed_rule_data=args.seed_rules,
        seed_mock=args.seed_mock,
        generate=args.generate,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
