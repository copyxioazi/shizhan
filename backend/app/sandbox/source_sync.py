"""Windows -> Linux VM 源码同步（tar over SFTP）与完整性指纹。

同步流程：
1. 把 Windows source_path 打包为 tar；
2. 通过 SFTP 上传到 VM /tmp；
3. SSH 执行 ``tar -xf`` 解压到 ``workspace/{project_id}/{run_no}/src``；
4. 分别计算本地与远端源码树 SHA-256 指纹并比对。

Windows 源目录全程只读，不做任何写入。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import paramiko

from app.core.config import settings
from app.core.errors import ApiError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target"}


class SourceSyncError(Exception):
    pass


def workspace_dir_for(project_id: int, run_no: int) -> str:
    return f"{settings.vm_workspace_dir.rstrip('/')}/{project_id}/{run_no}"


def _ssh_client() -> paramiko.SSHClient:
    target = settings.ssh_target
    if target is None:
        raise SourceSyncError("DOCKER_HOST 未配置为 ssh://user@host")
    host, user, port = target
    client = paramiko.SSHClient()
    # 演示环境使用自动接受；生产可改为 RejectPolicy 并预置 known_hosts
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs: dict[str, Any] = {
        "hostname": host,
        "port": port,
        "username": user,
        "timeout": 20,
    }
    key_path = settings.docker_ssh_key
    if key_path:
        key_file = Path(key_path)
        if not key_file.exists():
            raise SourceSyncError(f"SSH 私钥不存在：{key_path}")
        for loader in (
            paramiko.Ed25519Key,
            paramiko.RSAKey,
            paramiko.ECDSAKey,
        ):
            try:
                connect_kwargs["pkey"] = loader.from_private_key_file(str(key_file))
                break
            except paramiko.SSHException:
                continue
        else:
            raise SourceSyncError("无法识别 SSH 私钥格式")
    client.connect(**connect_kwargs)
    return client


def _run(client: paramiko.SSHClient, command: str) -> tuple[int, str, str]:
    _, stdout, stderr = client.exec_command(command, timeout=120)
    exit_code = stdout.channel.recv_exit_status()
    return (
        exit_code,
        stdout.read().decode("utf-8", errors="replace"),
        stderr.read().decode("utf-8", errors="replace"),
    )


def _local_fingerprint(root: Path) -> tuple[str, int]:
    """按相对路径字典序计算源码树指纹。"""
    entries: list[tuple[str, str]] = []
    file_count = 0
    root = root.resolve()
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for filename in sorted(filenames):
            path = Path(current) / filename
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            digest = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError:
                continue
            entries.append((relative, digest.hexdigest()))
            file_count += 1
    entries.sort(key=lambda item: item[0])
    joined = "".join(f"{digest}  ./{relative}\n" for relative, digest in entries)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest(), file_count


def _build_tar(source: Path) -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".tar", delete=False)
    handle.close()
    tar_path = Path(handle.name)
    with tarfile.open(tar_path, "w") as tar:
        for entry in sorted(source.iterdir(), key=lambda p: p.name):
            if entry.name in SKIP_DIRS:
                continue
            tar.add(entry, arcname=entry.name, recursive=True)
    return tar_path


def sync_source_blocking(project_id: int, run_no: int, source_path: str) -> dict[str, Any]:
    source = Path(source_path)
    if not source.is_dir():
        raise SourceSyncError(f"源码目录不存在：{source_path}")

    local_digest, file_count = _local_fingerprint(source)
    workspace = workspace_dir_for(project_id, run_no)
    source_dir = f"{workspace}/src"
    tmp_dir = f"{workspace}/tmp"

    client = _ssh_client()
    try:
        # tmp 需要让容器内 uid 1000 写入；src 只需可读
        code, _, err = _run(
            client, f"mkdir -p {source_dir} {tmp_dir} && chmod 0777 {tmp_dir}"
        )
        if code != 0:
            raise SourceSyncError(f"创建 VM 工作区失败：{err.strip()}")

        # 清理上一轮同步残留（同一 run_no 不会重复，但重试时可能残留）
        code, _, err = _run(client, f"find {source_dir} -mindepth 1 -delete")
        if code != 0:
            raise SourceSyncError(f"清空 VM 源码目录失败：{err.strip()}")

        tar_path = _build_tar(source)
        remote_tar = f"/tmp/ase-sync-{project_id}-{run_no}.tar"
        try:
            sftp = client.open_sftp()
            try:
                sftp.put(str(tar_path), remote_tar)
            finally:
                sftp.close()

            code, _, err = _run(client, f"tar -xf {remote_tar} -C {source_dir}")
            if code != 0:
                raise SourceSyncError(f"解压源码失败：{err.strip()}")
            # 容器以 uid 1000 运行，需要能读取源码副本
            _run(client, f"chmod -R a+rX {source_dir}")
        finally:
            _run(client, f"rm -f {remote_tar}")
            tar_path.unlink(missing_ok=True)

        remote_command = (
            f"cd {source_dir} && "
            "find . -type f -print0 | LC_ALL=C sort -z | "
            "xargs -0 sha256sum 2>/dev/null | sha256sum | cut -d' ' -f1"
        )
        code, out, err = _run(client, remote_command)
        if code != 0 or not out.strip():
            raise SourceSyncError(f"计算远端源码指纹失败：{err.strip()}")
        remote_digest = out.strip()

        if remote_digest != local_digest:
            raise SourceSyncError(
                "源码同步完整性校验失败：" f"local={local_digest} remote={remote_digest}"
            )
    finally:
        client.close()

    return {
        "source_dir": source_dir,
        "tmp_dir": tmp_dir,
        "workspace_dir": workspace,
        "fingerprint": local_digest,
        "file_count": file_count,
    }


async def sync_source(project_id: int, run_no: int, source_path: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            sync_source_blocking, project_id, run_no, source_path
        )
    except SourceSyncError as exc:
        raise ApiError(500, ErrorCode.SOURCE_SYNC_FAILED, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise ApiError(
            500, ErrorCode.SOURCE_SYNC_FAILED, f"源码同步失败：{exc}"
        ) from exc


def remove_remote_workspace_blocking(project_id: int) -> None:
    client = _ssh_client()
    try:
        code, _, err = _run(
            client, f"rm -rf {settings.vm_workspace_dir.rstrip('/')}/{project_id}"
        )
        if code != 0:
            raise SourceSyncError(err.strip() or "删除 VM 工作区失败")
    finally:
        client.close()


async def remove_remote_workspace(project_id: int) -> None:
    await asyncio.to_thread(remove_remote_workspace_blocking, project_id)


def cleanup_remote_tmp_blocking(project_id: int, run_no: int) -> None:
    workspace = workspace_dir_for(project_id, run_no)
    tmp_dir = f"{workspace}/tmp"
    client = _ssh_client()
    try:
        # 工作区可能已被删除项目的并发操作移除；此时不要重新创建目录
        code, _, err = _run(
            client,
            f"if [ -d {tmp_dir} ]; then find {tmp_dir} -mindepth 1 -delete; fi",
        )
        if code != 0:
            raise SourceSyncError(err.strip() or "清理 VM 工作区临时文件失败")
    finally:
        client.close()


async def cleanup_remote_tmp(project_id: int, run_no: int) -> None:
    """任务结束后清理容器可写工作区中的临时文件（best-effort）。"""
    try:
        await asyncio.to_thread(cleanup_remote_tmp_blocking, project_id, run_no)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cleanup remote tmp failed for %s/%s: %s", project_id, run_no, exc)
