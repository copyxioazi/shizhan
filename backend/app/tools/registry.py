"""工具注册表：把模型返回的 ``tool_calls`` 映射到 ``ToolExecutor``。"""

from __future__ import annotations

from typing import Any

from app.tools.definitions import MODEL_TOOLS, MODEL_TOOL_NAMES
from app.tools.executor import ToolExecutor


class ToolRegistry:
    def __init__(self, executor: ToolExecutor) -> None:
        self.executor = executor

    def openai_tools(self) -> list[dict[str, Any]]:
        """返回可交给模型的工具定义（深拷贝，避免调用方修改常量）。"""
        return [
            {
                "type": item["type"],
                "function": {
                    **item["function"],
                    "parameters": {
                        **item["function"]["parameters"],
                    },
                },
            }
            for item in MODEL_TOOLS
        ]

    async def call(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> Any:
        args = arguments or {}
        if name not in MODEL_TOOL_NAMES:
            raise ValueError(f"未知或不允许的工具：{name}")

        if name == "list_files":
            return await self.executor.list_files(
                _positive_int(args.get("max_files", 5000), "max_files")
            )
        if name == "read_file":
            return await self.executor.read_file(_required_text(args, "path"))
        if name == "search_code":
            return await self.executor.search_code(
                _required_text(args, "keyword"),
                _positive_int(args.get("max_hits", 200), "max_hits"),
            )
        if name == "syntax_check":
            return await self.executor.syntax_check(_required_text(args, "path"))
        raise ValueError(f"未实现的工具：{name}")


def _required_text(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"参数 {key} 必须是非空字符串")
    return value.strip()


def _positive_int(value: Any, key: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"参数 {key} 必须是整数") from exc
    if parsed < 1:
        raise ValueError(f"参数 {key} 必须大于 0")
    return parsed
