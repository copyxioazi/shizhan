#!/usr/bin/env python3
"""调用 POST /api/system/init 创建管理员账号（仅标准库）。

用法：
    python scripts/init_system.py --username admin --password 'Admin@12345'
    python scripts/init_system.py --username admin --password '...' --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化自动化安全评估系统管理员")
    parser.add_argument("--username", default="admin", help="管理员用户名（3–64 字符）")
    parser.add_argument("--password", required=True, help="管理员密码（8–72 字符）")
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:8000", help="后端地址"
    )
    args = parser.parse_args()

    body = json.dumps(
        {"username": args.username, "password": args.password}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{args.base_url.rstrip('/')}/api/system/init",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
            print("初始化成功：", json.dumps(payload, ensure_ascii=False))
            return 0
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"初始化失败：HTTP {exc.code} {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"无法连接后端：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
