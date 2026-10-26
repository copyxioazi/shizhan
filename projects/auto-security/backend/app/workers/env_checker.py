"""环境检查角色：SSH/Docker/镜像/工作区/容器内 Python。"""

from __future__ import annotations

import re

from app.sandbox.manager import SandboxCommandNotAllowed, SandboxCommandTimeout
from app.services.monitor_service import add_chat, add_log
from app.workers.base import WorkerContext, WorkerError


async def _probe_python(ctx: WorkerContext, code: str, args: list[str] | None = None) -> dict:
    argv = ["python", "-c", code] if args is None else ["python", *args]
    return await ctx.tools.run_command(argv)


async def run_env_checker(ctx: WorkerContext) -> dict:
    issues: list[str] = []
    result = {
        "source_readable": False,
        "workspace_writable": False,
        "disk_free_mb": 0,
        "ssh_available": True,
        "docker_available": False,
        "image_available": False,
        "python_version": "",
        "chosen_env_type": "docker",
        "issues": issues,
    }

    await add_log(
        ctx.project_id,
        "info",
        "开始环境检查：Docker 连接、镜像、工作区、容器内 Python",
        stage_id=ctx.stage_id,
        worker_task_id=ctx.worker_task_id,
    )

    try:
        result["docker_available"] = await ctx.tools.docker_ping()
        if not result["docker_available"]:
            issues.append("Docker daemon 不可达")
    except Exception as exc:  # noqa: BLE001
        raise WorkerError(f"SSH/Docker 连接失败：{exc}") from exc

    image = str(ctx.config.get("sandbox.image", "ase-sandbox:1.0"))
    try:
        result["image_available"] = await ctx.tools.image_exists(image)
    except Exception as exc:  # noqa: BLE001
        raise WorkerError(f"检查镜像失败：{exc}") from exc
    if not result["image_available"]:
        raise WorkerError(f"沙箱镜像不存在：{image}，请先在 VM 上构建或拉取")

    try:
        listing = await ctx.tools.list_files(5)
        result["source_readable"] = listing.get("count", 0) >= 0
        if listing.get("count", 0) == 0:
            issues.append("源码目录为空或没有可读文本文件")
    except Exception as exc:  # noqa: BLE001
        raise WorkerError(f"读取源码目录失败：{exc}") from exc

    try:
        version = await _probe_python(ctx, "", ["--version"])
        text = (version.get("stdout") or "") + (version.get("stderr") or "")
        match = re.search(r"Python\s+(\d+\.\d+\.\d+)", text)
        if not match:
            raise WorkerError(f"无法识别容器内 Python 版本：{text.strip()}")
        result["python_version"] = match.group(1)
        major, minor = (int(part) for part in match.group(1).split(".")[:2])
        if (major, minor) < (3, 11):
            raise WorkerError(f"容器内 Python 版本过低：{match.group(1)}（要求 3.11+）")
    except SandboxCommandNotAllowed as exc:
        raise WorkerError(str(exc)) from exc
    except SandboxCommandTimeout as exc:
        raise WorkerError(f"探测 Python 版本超时：{exc}") from exc

    try:
        disk = await _probe_python(
            ctx,
            "import shutil; print(shutil.disk_usage('/workspace').free)",
        )
        free_bytes = int((disk.get("stdout") or "0").strip() or 0)
        result["disk_free_mb"] = free_bytes // (1024 * 1024)
    except (ValueError, TypeError) as exc:
        raise WorkerError(f"无法读取 VM 工作区磁盘空间：{exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise WorkerError(f"磁盘检查失败：{exc}") from exc
    if free_bytes < 1024 * 1024 * 1024:
        # FR-ENV-05：磁盘可用空间不足属于致命检查
        raise WorkerError(
            f"VM 工作区可用磁盘不足 1 GB（当前 {result['disk_free_mb']} MB）"
        )

    probe = await _probe_python(
        ctx, "open('/workspace/.ase_probe', 'w').write('ok')"
    )
    result["workspace_writable"] = probe.get("exit_code") == 0
    if not result["workspace_writable"]:
        raise WorkerError("VM 工作区不可写")

    write_source = await _probe_python(
        ctx, "open('/src/.ase_write_probe', 'w').write('should-not-happen')"
    )
    if write_source.get("exit_code") == 0:
        # 清理并判定为致命错误
        await _probe_python(
            ctx,
            "import os\np='/src/.ase_write_probe'\n"
            "os.path.exists(p) and os.remove(p)",
        )
        raise WorkerError("源码目录可写，违反只读挂载约束")

    await add_log(
        ctx.project_id,
        "info",
        f"环境检查通过：Python {result['python_version']}，磁盘 {result['disk_free_mb']} MB",
        stage_id=ctx.stage_id,
        worker_task_id=ctx.worker_task_id,
    )
    await add_chat(
        ctx.project_id,
        "env_checker",
        "conclusion",
        "环境检查完成：Docker 可达、镜像存在、源码只读、工作区可写。",
    )
    return result
