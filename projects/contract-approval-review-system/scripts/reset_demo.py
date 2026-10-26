"""清空并重建演示数据。"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.config import settings
from init_db import init_databases


def main() -> None:
    attachments = settings.data_dir / "attachments"
    if attachments.exists():
        shutil.rmtree(attachments)
    result = init_databases(reset=True, seed_rule_data=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
