"""暴露给模型的安全工具定义（OpenAI tool calling 格式）。

只包含只读或受限执行能力；``run_command`` 等基础设施工具不在此列，
由 worker 代码直接使用，避免模型获得任意命令执行入口。
"""

from __future__ import annotations

from typing import Any

MODEL_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出只读源码目录中的文本文件及其大小。",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_files": {
                        "type": "integer",
                        "description": "最多返回的文件数，默认 5000。",
                        "minimum": 1,
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取只读源码目录中的单个文件内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对源码根目录的文件路径，例如 app.py。",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "在只读源码中按关键字搜索，返回命中位置。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "要搜索的关键字。"},
                    "max_hits": {
                        "type": "integer",
                        "description": "最多返回的命中数，默认 200。",
                        "minimum": 1,
                    },
                },
                "required": ["keyword"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "syntax_check",
            "description": "对 /src 下的 Python 文件做语法检查，不执行代码。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，可带 /src/ 前缀。",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
)

MODEL_TOOL_NAMES = frozenset(
    item["function"]["name"] for item in MODEL_TOOLS
)
