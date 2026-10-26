"""工具执行层：worker 与 Agent 节点共用的沙箱入口。

这一层只做三件事：

1. 把“工具名 + 参数”翻译成沙箱 ``helper``/``exec`` 调用；
2. 记录轻量的调用轨迹（不含源码与命令正文）；
3. 原样透传沙箱异常，保证超时、白名单、配额语义不变。
"""

from __future__ import annotations

import time
from typing import Any

from app.sandbox.manager import SandboxRuntime


class ToolExecutor:
    def __init__(
        self,
        sandbox: SandboxRuntime,
        *,
        trace: list[dict[str, Any]] | None = None,
    ) -> None:
        self._sandbox = sandbox
        self.trace: list[dict[str, Any]] = trace if trace is not None else []

    # ------------------------------------------------------------------
    # 沙箱基础信息
    # ------------------------------------------------------------------
    @property
    def container_name(self) -> str:
        return self._sandbox.container_name

    @property
    def image(self) -> str:
        return self._sandbox.image

    def bind_worker(self, stage_id: int | None, worker_task_id: int | None) -> None:
        self._sandbox.bind_worker(stage_id, worker_task_id)

    async def docker_ping(self) -> bool:
        return await self._sandbox.manager.ping()

    async def image_exists(self, image: str) -> bool:
        return await self._sandbox.manager.image_exists(image)

    async def stats(self) -> dict[str, float]:
        return await self._sandbox.stats()

    # ------------------------------------------------------------------
    # 源码与命令工具
    # ------------------------------------------------------------------
    async def list_files(self, max_files: int) -> dict[str, Any]:
        return await self._helper(
            "list_files",
            {"max_files": max_files},
            ["list", "--max-files", str(max_files)],
        )

    async def read_file(self, path: str) -> dict[str, Any]:
        return await self._helper("read_file", {"path": path}, ["read", path])

    async def search_code(self, keyword: str, max_hits: int = 200) -> dict[str, Any]:
        return await self._helper(
            "search_code",
            {"keyword": keyword, "max_hits": max_hits},
            ["search", keyword, "--max-hits", str(max_hits)],
        )

    async def syntax_check(self, path: str) -> dict[str, Any]:
        relative = path[len("/src/") :] if path.startswith("/src/") else path.lstrip("/")
        return await self._helper(
            "syntax_check",
            {"path": path},
            ["syntax", relative],
        )

    async def run_command(self, argv: list[str]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            result = await self._sandbox.exec(argv)
        except Exception as exc:  # noqa: BLE001 - 记录后原样抛出
            self._record(
                "run_command",
                {"executable": argv[0] if argv else "", "args": max(0, len(argv) - 1)},
                started,
                ok=False,
                error=exc,
            )
            raise
        self._record(
            "run_command",
            {"executable": argv[0] if argv else "", "args": max(0, len(argv) - 1)},
            started,
            ok=True,
            result=result,
        )
        return result

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    async def _helper(
        self, tool: str, public_args: dict[str, Any], helper_args: list[str]
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            result = await self._sandbox.helper(helper_args)
        except Exception as exc:  # noqa: BLE001 - 记录后原样抛出
            self._record(tool, public_args, started, ok=False, error=exc)
            raise
        self._record(tool, public_args, started, ok=True, result=result)
        return result

    def _record(
        self,
        tool: str,
        args: dict[str, Any],
        started: float,
        *,
        ok: bool,
        result: Any = None,
        error: Exception | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "tool": tool,
            "args": args,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "ok": ok,
        }
        if result is not None:
            entry["result_bytes"] = _result_bytes(result)
        if error is not None:
            entry["error"] = str(error)[:200]
        self.trace.append(entry)


def _result_bytes(result: Any) -> int:
    """只记录结果规模，不把源码或命令输出放进状态。"""
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, str):
            return len(content)
        stdout = result.get("stdout")
        if isinstance(stdout, str):
            return len(stdout)
    return 0
