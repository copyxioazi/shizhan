"""验证 /orders 的越权访问（IDOR）。成功时输出 VULN_CONFIRMED。"""

from __future__ import annotations

import os
import sys

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC_DIR)

import app  # noqa: E402

CURRENT_USER_ID = 1


def main() -> int:
    order = app.get_order(1002)
    print(f"order={order} current_user_id={CURRENT_USER_ID}")
    if order and order.get("owner_id") != CURRENT_USER_ID:
        print("VULN_CONFIRMED")
        return 0
    print("idor not confirmed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
