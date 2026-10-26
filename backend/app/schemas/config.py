from __future__ import annotations

from typing import Any

from pydantic import RootModel


class ConfigUpdate(RootModel[dict[str, Any]]):
    """部分更新：请求体为 config_key -> value 的扁平对象。"""

    root: dict[str, Any] = {}
