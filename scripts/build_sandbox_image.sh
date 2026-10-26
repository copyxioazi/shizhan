#!/usr/bin/env bash
# 在 Linux VM 上构建沙箱镜像 ase-sandbox:1.0
# 用法：bash scripts/build_sandbox_image.sh [镜像标签]
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_TAG="${1:-ase-sandbox:1.0}"

cd "$ROOT_DIR"
echo "==> 构建沙箱镜像 ${IMAGE_TAG}"
docker build -f sandbox/Dockerfile -t "$IMAGE_TAG" .
echo "==> 完成"
docker image inspect "$IMAGE_TAG" --format '{{.Id}} {{.RepoTags}}'
