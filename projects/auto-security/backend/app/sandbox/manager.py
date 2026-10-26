"""Docker 沙箱管理（Docker SDK over SSH）。

所有 Docker 调用都是阻塞的，统一通过 ``asyncio.to_thread`` 执行。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shlex
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound, NotFound

from app.core.config import settings
from app.core.errors import ApiError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

# FR-EXEC-06：单项目工作区占用上限 1 GB
WORKSPACE_QUOTA_BYTES = 1024 * 1024 * 1024


class SandboxCommandTimeout(Exception):
    pass


class SandboxCommandNotAllowed(Exception):
    pass


class SandboxQuotaExceeded(Exception):
    """工作区占用超过 1 GB（FR-EXEC-06）。"""


class SandboxUnavailable(Exception):
    """沙箱容器或 Docker daemon 不可用。"""


UNAVAILABLE_MARKERS = (
    "is not running",
    "no such container",
    "cannot connect to the docker daemon",
    "is the docker daemon running",
)


def _looks_unavailable(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in UNAVAILABLE_MARKERS)


@dataclass
class SandboxSpec:
    project_id: int
    run_no: int
    image: str
    source_dir_vm: str
    workspace_dir_vm: str
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def container_name(self) -> str:
        return f"ase-sandbox-{self.project_id}-r{self.run_no}"


class SandboxManager:
    def __init__(self) -> None:
        self._client: docker.DockerClient | None = None
        self._lock = asyncio.Lock()

    def _make_client(self) -> docker.DockerClient:
        if not settings.docker_host:
            raise ApiError(
                503,
                ErrorCode.ENVIRONMENT_UNAVAILABLE,
                "未配置 DOCKER_HOST，无法连接 Linux VM 上的 Docker",
            )
        try:
            # use_ssh_client=True 使用系统 OpenSSH；DOCKER_SSH_KEY 需在
            # ~/.ssh/config 的 IdentityFile 中引用，或由 ssh-agent 提供。
            return docker.DockerClient(
                base_url=settings.docker_host,
                use_ssh_client=True,
                timeout=30,
            )
        except DockerException as exc:
            raise ApiError(
                503, ErrorCode.ENVIRONMENT_UNAVAILABLE, f"Docker 连接失败：{exc}"
            ) from exc

    async def _get_client(self) -> docker.DockerClient:
        async with self._lock:
            if self._client is None:
                self._client = await asyncio.to_thread(self._make_client)
            return self._client

    async def close(self) -> None:
        if self._client is not None:
            try:
                await asyncio.to_thread(self._client.close)
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    async def ping(self) -> bool:
        client = await self._get_client()
        try:
            return bool(await asyncio.to_thread(client.ping))
        except DockerException as exc:
            raise ApiError(
                503, ErrorCode.ENVIRONMENT_UNAVAILABLE, f"Docker daemon 不可达：{exc}"
            ) from exc

    async def image_exists(self, image: str) -> bool:
        client = await self._get_client()
        try:
            await asyncio.to_thread(client.images.get, image)
            return True
        except ImageNotFound:
            return False

    async def create_and_start(self, spec: SandboxSpec) -> str:
        client = await self._get_client()
        name = spec.container_name
        cfg = spec.config

        def _create() -> str:
            try:
                client.images.get(spec.image)
            except ImageNotFound as exc:
                raise ApiError(
                    500,
                    ErrorCode.ENVIRONMENT_CREATE_FAILED,
                    f"沙箱镜像不存在：{spec.image}，请先在 VM 上构建或拉取",
                ) from exc

            try:
                old = client.containers.get(name)
                old.remove(force=True)
            except NotFound:
                pass

            volumes = {
                spec.source_dir_vm: {"bind": "/src", "mode": "ro"},
                spec.workspace_dir_vm: {"bind": "/workspace", "mode": "rw"},
            }
            network_enabled = bool(cfg.get("sandbox.network_enabled", False))
            container = client.containers.create(
                image=spec.image,
                name=name,
                command=["sleep", "infinity"],
                detach=True,
                labels={"ase.project_id": str(spec.project_id)},
                network_mode="bridge" if network_enabled else "none",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                pids_limit=int(cfg.get("sandbox.pids_limit", 128)),
                nano_cpus=int(float(cfg.get("sandbox.cpu_limit", 1.0)) * 1_000_000_000),
                mem_limit=f"{int(cfg.get('sandbox.memory_limit_mb', 512))}m",
                user="1000:1000",
                working_dir="/workspace",
                volumes=volumes,
                tmpfs={"/tmp": "rw,size=64m"},
            )
            container.start()
            return name

        try:
            return await asyncio.to_thread(_create)
        except ApiError:
            raise
        except DockerException as exc:
            raise ApiError(
                500, ErrorCode.ENVIRONMENT_CREATE_FAILED, f"创建沙箱容器失败：{exc}"
            ) from exc

    async def stop(self, name: str) -> None:
        client = await self._get_client()

        def _stop() -> None:
            try:
                container = client.containers.get(name)
                container.stop(timeout=10)
            except NotFound:
                return

        try:
            await asyncio.to_thread(_stop)
        except DockerException as exc:
            logger.warning("stop sandbox %s failed: %s", name, exc)

    async def remove(self, name: str) -> None:
        client = await self._get_client()

        def _remove() -> None:
            try:
                client.containers.get(name).remove(force=True)
            except NotFound:
                return

        try:
            await asyncio.to_thread(_remove)
        except DockerException as exc:
            logger.warning("remove sandbox %s failed: %s", name, exc)

    async def remove_project_containers(self, project_id: int) -> list[str]:
        client = await self._get_client()

        def _remove() -> list[str]:
            removed: list[str] = []
            containers = client.containers.list(
                all=True, filters={"label": f"ase.project_id={project_id}"}
            )
            for container in containers:
                container.remove(force=True)
                removed.append(container.name)
            return removed

        try:
            return await asyncio.to_thread(_remove)
        except DockerException as exc:
            logger.warning("remove project containers failed: %s", exc)
            return []

    async def cleanup_orphans(self, existing_project_ids: set[int]) -> list[str]:
        """删除标签指向不存在项目的孤儿容器（FR-ENV-06）。"""
        client = await self._get_client()

        def _cleanup() -> list[str]:
            removed: list[str] = []
            containers = client.containers.list(
                all=True, filters={"label": "ase.project_id"}
            )
            for container in containers:
                raw = (container.labels or {}).get("ase.project_id", "")
                try:
                    project_id = int(raw)
                except ValueError:
                    continue
                if project_id not in existing_project_ids:
                    container.remove(force=True)
                    removed.append(container.name)
            return removed

        try:
            return await asyncio.to_thread(_cleanup)
        except DockerException as exc:
            logger.warning("orphan container cleanup failed: %s", exc)
            return []

    @staticmethod
    def _truncate(payload: bytes, limit: int) -> str:
        text = payload.decode("utf-8", errors="replace")
        if len(text.encode("utf-8")) <= limit:
            return text
        # 按字节截断后解码，避免超出上限
        truncated = text.encode("utf-8")[:limit].decode("utf-8", errors="ignore")
        return truncated + "...[truncated]"

    def _ssh_base_argv(self) -> list[str]:
        target = settings.ssh_target
        if target is None:
            raise ApiError(
                503,
                ErrorCode.ENVIRONMENT_UNAVAILABLE,
                "沙箱命令执行需要 DOCKER_HOST=ssh://user@host",
            )
        host, user, port = target
        argv = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "LogLevel=ERROR",
        ]
        if settings.docker_ssh_key:
            argv.extend(["-i", settings.docker_ssh_key, "-o", "IdentitiesOnly=yes"])
        if port != 22:
            argv.extend(["-p", str(port)])
        argv.extend([f"{user}@{host}"])
        return argv

    async def _run_ssh(
        self, remote_command: str, timeout_seconds: int
    ) -> tuple[int, bytes, bytes]:
        """执行远程命令。

        docker-py 的 exec_run 在 SSH 连接上会挂起，因此命令执行走系统
        OpenSSH + ``docker exec``；参数使用 shlex.quote，避免 shell 注入。
        """
        proc = await asyncio.create_subprocess_exec(
            *self._ssh_base_argv(),
            remote_command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds + 10
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            raise SandboxCommandTimeout(
                f"命令执行超过 {timeout_seconds} 秒"
            ) from exc
        return int(proc.returncode or 0), stdout, stderr

    async def exec_command(
        self,
        name: str,
        argv: list[str],
        *,
        allowlist: list[str],
        timeout_seconds: int = 60,
        output_limit: int = 8192,
    ) -> dict[str, Any]:
        if not argv:
            raise SandboxCommandNotAllowed("命令为空")
        executable = argv[0].replace("\\", "/").rsplit("/", 1)[-1]
        if executable not in allowlist:
            raise SandboxCommandNotAllowed(f"命令不在白名单内：{executable}")

        started = time.monotonic()
        wrapped = [
            "timeout",
            "--signal=KILL",
            str(max(1, int(timeout_seconds))),
            *argv,
        ]
        remote_command = (
            "docker exec --user 1000:1000 --workdir /workspace "
            + shlex.quote(name)
            + " "
            + " ".join(shlex.quote(arg) for arg in wrapped)
        )
        exit_code, stdout, stderr = await self._run_ssh(
            remote_command, timeout_seconds
        )
        if exit_code in (124, 137):
            raise SandboxCommandTimeout(
                f"命令执行超过 {timeout_seconds} 秒，已被终止"
            )
        elapsed = time.monotonic() - started
        stdout_text = self._truncate(stdout, output_limit)
        used = len(stdout_text.encode("utf-8"))
        remaining = max(0, output_limit - used)
        stderr_text = self._truncate(stderr, remaining) if remaining else ""
        return {
            "command": " ".join(argv),
            "exit_code": exit_code,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "duration_seconds": round(elapsed, 2),
        }

    async def helper(
        self,
        name: str,
        args: list[str],
        *,
        allowlist: list[str],
        timeout_seconds: int = 60,
        output_limit: int = 8 * 1024 * 1024,
    ) -> Any:
        import json

        result = await self.exec_command(
            name,
            ["python", "/opt/sandbox/helper.py", *args],
            allowlist=allowlist,
            timeout_seconds=timeout_seconds,
            output_limit=output_limit,
        )
        if result["exit_code"] != 0:
            raise RuntimeError(
                f"helper 执行失败（exit={result['exit_code']}）：{result['stderr']}"
            )
        try:
            return json.loads(result["stdout"])
        except json.JSONDecodeError as exc:
            raise RuntimeError("helper 输出不是合法 JSON") from exc

    @staticmethod
    def _parse_memory_mb(text: str) -> float:
        current = text.split("/")[0].strip()
        units = {
            "B": 1 / (1024 * 1024),
            "KiB": 1 / 1024,
            "MiB": 1,
            "GiB": 1024,
            "kB": 1 / 1000,
            "MB": 1,
            "GB": 1000,
        }
        for unit in sorted(units, key=len, reverse=True):
            if current.endswith(unit):
                value = float(current[: -len(unit)].strip())
                return round(value * units[unit], 2)
        return 0.0

    async def workspace_usage(self, name: str) -> int:
        """返回容器内 /workspace 的字节占用（FR-EXEC-06）。"""
        remote = (
            "docker exec --user 1000:1000 "
            + shlex.quote(name)
            + " du -sb /workspace"
        )
        exit_code, stdout, stderr = await self._run_ssh(remote, 15)
        if exit_code != 0:
            raise RuntimeError(
                f"读取工作区占用失败：{stderr.decode('utf-8', errors='replace').strip()}"
            )
        try:
            return int(stdout.split()[0])
        except (IndexError, ValueError) as exc:
            raise RuntimeError("无法解析工作区占用") from exc

    async def stats(self, name: str) -> dict[str, float]:
        remote = (
            "docker stats --no-stream --format "
            + shlex.quote("{{json .}}")
            + " "
            + shlex.quote(name)
        )
        try:
            exit_code, stdout, _ = await self._run_ssh(remote, 10)
            if exit_code != 0 or not stdout.strip():
                return {"cpu_usage": 0.0, "memory_usage": 0.0}
            payload = json.loads(stdout.decode("utf-8").strip().splitlines()[-1])
            cpu = float(str(payload.get("CPUPerc", "0%")).strip().rstrip("%"))
            memory = self._parse_memory_mb(str(payload.get("MemUsage", "0B")))
            return {"cpu_usage": round(cpu, 2), "memory_usage": memory}
        except Exception as exc:  # noqa: BLE001 - 采样失败不应中断任务
            logger.debug("stats failed for %s: %s", name, exc)
            return {"cpu_usage": 0.0, "memory_usage": 0.0}

    async def wait_ready(self, name: str, timeout_seconds: int = 30) -> bool:
        client = await self._get_client()

        def _check() -> bool:
            container = client.containers.get(name)
            container.reload()
            return container.status == "running"

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if await asyncio.to_thread(_check):
                return True
            await asyncio.sleep(0.5)
        return False


class SandboxRuntime:
    """某一轮运行的沙箱句柄，供 worker 使用。"""

    def __init__(
        self,
        manager: SandboxManager,
        container_name: str,
        image: str,
        source_dir_vm: str,
        workspace_dir_vm: str,
        config: dict[str, Any],
        *,
        project_id: int,
    ) -> None:
        self.manager = manager
        self.container_name = container_name
        self.image = image
        self.source_dir_vm = source_dir_vm
        self.workspace_dir_vm = workspace_dir_vm
        self.config = config
        self.project_id = project_id
        self.stage_id: int | None = None
        self.worker_task_id: int | None = None
        self.token_count = 0
        self._run_token = uuid.uuid4().hex

    @property
    def allowlist(self) -> list[str]:
        return list(self.config.get("sandbox.command_allowlist", ["python", "python3"]))

    def bind_worker(
        self, stage_id: int | None, worker_task_id: int | None
    ) -> None:
        """绑定当前角色，供命令审计日志（FR-EXEC-05）使用。"""
        self.stage_id = stage_id
        self.worker_task_id = worker_task_id

    async def _audit(
        self,
        argv: list[str],
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        level: str | None = None,
        output_summary: str | None = None,
    ) -> None:
        """每条命令写 runtime_logs：命令、工作目录、退出码、耗时、输出摘要。"""
        from app.services.monitor_service import add_log

        command = " ".join(argv)
        if result is not None:
            if output_summary is None:
                output = (
                    (result.get("stdout") or "") + (result.get("stderr") or "")
                ).strip()
                output_summary = " ".join(output.split())[:200] or "(空)"
            log_level = level or (
                "info" if result.get("exit_code") == 0 else "warn"
            )
            content = (
                f"命令执行：{command} | cwd=/workspace | "
                f"exit={result.get('exit_code')} | "
                f"耗时={result.get('duration_seconds')}s | "
                f"输出摘要={output_summary}"
            )
        else:
            log_level = level or "error"
            content = (
                f"命令执行失败：{command} | cwd=/workspace | 原因={error or '未知'}"
            )
        await add_log(
            self.project_id,
            log_level,
            content,
            stage_id=self.stage_id,
            worker_task_id=self.worker_task_id,
        )

    async def _check_quota(self, argv: list[str]) -> None:
        try:
            usage = await self.manager.workspace_usage(self.container_name)
        except Exception as exc:  # noqa: BLE001
            if _looks_unavailable(str(exc)):
                raise SandboxUnavailable(f"沙箱容器不可用：{exc}") from exc
            raise
        if usage > WORKSPACE_QUOTA_BYTES:
            message = (
                f"项目工作区占用 {usage / (1024 ** 3):.2f} GB，超过 1 GB 上限，"
                f"已终止命令：{' '.join(argv)[:200]}"
            )
            await self._audit(argv, error=message, level="error")
            raise SandboxQuotaExceeded(message)

    async def exec(
        self, argv: list[str], timeout_seconds: int | None = None
    ) -> dict[str, Any]:
        if not argv:
            raise SandboxCommandNotAllowed("命令为空")
        executable = argv[0].replace("\\", "/").rsplit("/", 1)[-1]
        if executable not in self.allowlist:
            raise SandboxCommandNotAllowed(f"命令不在白名单内：{executable}")

        await self._check_quota(argv)
        timeout = timeout_seconds or int(
            self.config.get("sandbox.command_timeout_seconds", 60)
        )
        # 由 helper 监控工作区并控制超时，超限时杀死整个进程组（FR-EXEC-06）
        wrapped = [
            "python",
            "/opt/sandbox/helper.py",
            "run",
            "--timeout",
            str(timeout),
            "--",
            *argv,
        ]
        try:
            result = await self.manager.exec_command(
                self.container_name,
                wrapped,
                allowlist=self.allowlist,
                timeout_seconds=timeout + 5,
                output_limit=int(self.config.get("sandbox.output_limit_bytes", 8192)),
            )
        except SandboxCommandTimeout as exc:
            await self._audit(argv, error=f"超时：{exc}", level="error")
            raise
        except SandboxCommandNotAllowed as exc:
            await self._audit(argv, error=f"命令不在白名单：{exc}", level="error")
            raise
        except Exception as exc:  # noqa: BLE001
            await self._audit(argv, error=f"执行异常：{exc}", level="error")
            raise

        stderr = result.get("stderr") or ""
        if result.get("exit_code") == 125 and "ASE_QUOTA_EXCEEDED" in stderr:
            usage = 0
            for token in stderr.split():
                if token.isdigit():
                    usage = int(token)
                    break
            usage_text = f"{usage / (1024 ** 3):.2f} GB" if usage else "超过 1 GB"
            message = (
                f"项目工作区占用 {usage_text}，超过 1 GB 上限，"
                f"命令已被终止：{' '.join(argv)[:200]}"
            )
            await self._audit(
                argv,
                result=result,
                level="error",
                output_summary=message,
            )
            raise SandboxQuotaExceeded(message)

        if result.get("exit_code") != 0 and _looks_unavailable(
            result.get("stderr") or ""
        ):
            message = (
                "沙箱容器不可用："
                + (result.get("stderr") or "").strip()[:300]
            )
            await self._audit(
                argv, result=result, level="error", output_summary=message
            )
            raise SandboxUnavailable(message)

        await self._audit(argv, result=result)
        return result

    async def helper(self, args: list[str]) -> Any:
        argv = ["python", "/opt/sandbox/helper.py", *args]
        try:
            result = await self.manager.exec_command(
                self.container_name,
                argv,
                allowlist=self.allowlist,
                timeout_seconds=int(
                    self.config.get("sandbox.command_timeout_seconds", 60)
                ),
                output_limit=8 * 1024 * 1024,
            )
        except SandboxCommandTimeout as exc:
            await self._audit(argv, error=f"超时：{exc}", level="error")
            raise
        except SandboxCommandNotAllowed as exc:
            await self._audit(argv, error=f"命令不在白名单：{exc}", level="error")
            raise
        except Exception as exc:  # noqa: BLE001
            await self._audit(argv, error=f"执行异常：{exc}", level="error")
            raise
        # helper 输出可能包含源码，审计日志只记录字节数
        await self._audit(
            argv,
            result=result,
            output_summary=f"helper 输出 {len(result.get('stdout') or '')} 字节",
        )
        if result["exit_code"] != 0:
            if _looks_unavailable(result.get("stderr") or ""):
                raise SandboxUnavailable(
                    "沙箱容器不可用："
                    + (result.get("stderr") or "").strip()[:300]
                )
            raise RuntimeError(
                f"helper 执行失败（exit={result['exit_code']}）：{result['stderr']}"
            )
        try:
            return json.loads(result["stdout"])
        except json.JSONDecodeError as exc:
            raise RuntimeError("helper 输出不是合法 JSON") from exc

    async def stats(self) -> dict[str, float]:
        return await self.manager.stats(self.container_name)

    async def stop(self) -> None:
        await self.manager.stop(self.container_name)

    async def close(self) -> None:
        await self.manager.close()
