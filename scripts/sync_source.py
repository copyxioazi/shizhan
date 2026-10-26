#!/usr/bin/env python3
"""手动将 Windows 源码目录同步到 Linux VM（复用后端 source_sync 实现）。

需要在仓库根目录 .env 中配置：
    DOCKER_HOST=ssh://eval@vm-ip
    DOCKER_SSH_KEY=C:/Users/you/.ssh/ase_eval_key
    VM_WORKSPACE_DIR=/home/eval/workspace

用法（使用后端 venv，确保 paramiko 已安装）：
    backend/.venv/Scripts/python.exe scripts/sync_source.py \
        examples/vuln-demo --project-id 1 --run-no 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
# 仅同步源码，不需要 JWT；避免 config 校验阻塞脚本
os.environ.setdefault("JWT_SECRET", "sync-only-" + "0" * 32)


def main() -> int:
    parser = argparse.ArgumentParser(description="同步源码到 VM 沙箱工作区")
    parser.add_argument("source_path", help="Windows 源码目录（绝对或相对路径）")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--run-no", type=int, default=1)
    args = parser.parse_args()

    source = Path(args.source_path).resolve()
    if not source.is_dir():
        print(f"源码目录不存在：{source}", file=sys.stderr)
        return 1

    from app.sandbox.source_sync import sync_source_blocking

    try:
        result = sync_source_blocking(args.project_id, args.run_no, str(source))
    except Exception as exc:  # noqa: BLE001
        print(f"同步失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
