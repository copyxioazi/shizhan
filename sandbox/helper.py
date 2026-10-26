#!/usr/bin/env python3
"""沙箱内文件访问 helper。

仅使用 Python 标准库，固定根目录 /src：
  list   [--max-files N] [--max-depth N]
  read   <relative-path>
  search <keyword> [--max-hits N]
  syntax <relative-path>
  run    --timeout N -- <argv...>

``syntax`` 使用 ast.parse 做只读语法检查（FR-VULN-03），不会生成 .pyc。
``run`` 在 /workspace 中执行命令并监控工作区占用，超过 1 GB 时杀死
进程组并返回 125（FR-EXEC-06）；超时返回 124。

所有路径规范化后必须仍在 /src 内，拒绝绝对路径、``..`` 与符号链接逃逸。
"""

from __future__ import annotations

import ast
import json
import os
import resource
import signal
import subprocess
import sys
import time

QUOTA_BYTES = 1024 * 1024 * 1024

ROOT = "/src"
MAX_FILE_BYTES = 2 * 1024 * 1024
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
}
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".pdf", ".zip", ".gz", ".tar", ".7z", ".rar", ".exe", ".dll",
    ".so", ".dylib", ".pyc", ".class", ".jar", ".woff", ".woff2",
    ".ttf", ".eot", ".mp3", ".mp4", ".avi", ".mov",
}


def fail(message: str, code: int = 2) -> None:
    sys.stderr.write(message + "\n")
    raise SystemExit(code)


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")


def resolve_in_root(raw: str) -> str:
    if raw.startswith(("/", "\\")):
        fail("拒绝绝对路径", 3)
    candidate = os.path.realpath(os.path.join(ROOT, raw))
    root = os.path.realpath(ROOT)
    if candidate != root and not candidate.startswith(root + os.sep):
        fail("路径越界", 3)
    if not os.path.exists(candidate):
        fail("文件不存在", 4)
    return candidate


def is_binary(path: str, sample: bytes | None = None) -> bool:
    if os.path.splitext(path)[1].lower() in BINARY_EXTENSIONS:
        return True
    if sample is None:
        with open(path, "rb") as handle:
            sample = handle.read(8192)
    return b"\x00" in sample


def iter_text_files(max_depth: int = 20):
    root = os.path.realpath(ROOT)
    for current, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(current, root)
        depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
        if depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for filename in sorted(filenames):
            path = os.path.join(current, filename)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                continue
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            yield path, relative, size


def cmd_list(args: list[str]) -> None:
    max_files = 5000
    max_depth = 20
    index = 0
    while index < len(args):
        if args[index] == "--max-files" and index + 1 < len(args):
            max_files = int(args[index + 1])
            index += 2
        elif args[index] == "--max-depth" and index + 1 < len(args):
            max_depth = int(args[index + 1])
            index += 2
        else:
            index += 1

    files = []
    truncated = False
    for path, relative, size in iter_text_files(max_depth):
        if len(files) >= max_files:
            truncated = True
            break
        try:
            binary = is_binary(path)
        except OSError:
            continue
        if binary:
            continue
        files.append({"path": relative, "size": size})
    files.sort(key=lambda item: item["path"])
    emit({"root": ROOT, "files": files, "truncated": truncated, "count": len(files)})


def cmd_read(args: list[str]) -> None:
    if not args:
        fail("缺少文件路径")
    path = resolve_in_root(args[0])
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        sample = handle.read(min(size, 8192))
        binary = is_binary(path, sample)
        if binary:
            emit({"path": args[0], "size": size, "binary": True, "content": ""})
            return
        handle.seek(0)
        content = handle.read(MAX_FILE_BYTES)
    truncated = size > MAX_FILE_BYTES
    text = content.decode("utf-8", errors="replace")
    emit(
        {
            "path": args[0],
            "size": size,
            "binary": False,
            "truncated": truncated,
            "content": text,
        }
    )


def cmd_search(args: list[str]) -> None:
    if not args:
        fail("缺少搜索关键字")
    keyword = args[0]
    max_hits = 200
    if "--max-hits" in args:
        idx = args.index("--max-hits")
        if idx + 1 < len(args):
            max_hits = int(args[idx + 1])

    needle = keyword.lower()
    hits = []
    truncated = False
    for path, relative, _size in iter_text_files():
        try:
            if is_binary(path):
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for line_no, line in enumerate(handle, start=1):
                    if needle in line.lower():
                        if len(hits) >= max_hits:
                            truncated = True
                            break
                        snippet = line.strip()[:200]
                        hits.append(
                            {
                                "file_path": relative,
                                "line_no": line_no,
                                "snippet": snippet,
                            }
                        )
        except OSError:
            continue
        if truncated:
            break
    emit({"keyword": keyword, "hits": hits, "truncated": truncated, "count": len(hits)})


def cmd_syntax(args: list[str]) -> None:
    if not args:
        fail("缺少文件路径")
    relative = args[0]
    path = resolve_in_root(relative)
    try:
        with open(path, "rb") as handle:
            source = handle.read(MAX_FILE_BYTES).decode("utf-8", errors="replace")
    except OSError as exc:
        fail(f"读取文件失败：{exc}")
    try:
        ast.parse(source, filename=relative)
    except SyntaxError as exc:
        emit(
            {
                "ok": False,
                "error": f"{exc.msg}（行 {exc.lineno}）",
            }
        )
        return
    emit({"ok": True})


def workspace_bytes() -> int:
    total = 0
    for current, _dirnames, filenames in os.walk("/workspace"):
        for filename in filenames:
            try:
                total += os.path.getsize(os.path.join(current, filename))
            except OSError:
                continue
    return total


def _limit_file_size() -> None:
    # 单个文件不得超过配额；超限时内核发送 SIGXFSZ
    resource.setrlimit(resource.RLIMIT_FSIZE, (QUOTA_BYTES, QUOTA_BYTES))


def cmd_run(args: list[str]) -> None:
    timeout = 60
    if args[:1] == ["--timeout"] and len(args) > 1:
        timeout = max(1, int(args[1]))
        args = args[2:]
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        fail("缺少待执行命令")

    proc = subprocess.Popen(
        args,
        cwd="/workspace",
        start_new_session=True,
        preexec_fn=_limit_file_size,
    )
    started = time.monotonic()
    while True:
        usage = workspace_bytes()
        if usage >= QUOTA_BYTES:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            sys.stderr.write(f"ASE_QUOTA_EXCEEDED {usage}\n")
            raise SystemExit(125)
        returncode = proc.poll()
        if returncode is not None:
            if returncode == -signal.SIGXFSZ or usage >= QUOTA_BYTES:
                sys.stderr.write(f"ASE_QUOTA_EXCEEDED {usage}\n")
                raise SystemExit(125)
            raise SystemExit(returncode if returncode >= 0 else 128 - returncode)
        if time.monotonic() - started > timeout:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            sys.stderr.write("ASE_TIMEOUT\n")
            raise SystemExit(124)
        time.sleep(0.02)


def main() -> None:
    if len(sys.argv) < 2:
        fail("用法: helper.py <list|read|search|syntax|run> ...")
    command, args = sys.argv[1], sys.argv[2:]
    if command == "list":
        cmd_list(args)
    elif command == "read":
        cmd_read(args)
    elif command == "search":
        cmd_search(args)
    elif command == "syntax":
        cmd_syntax(args)
    elif command == "run":
        cmd_run(args)
    else:
        fail(f"未知命令：{command}")


if __name__ == "__main__":
    main()
