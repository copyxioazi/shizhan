# Docker 部署

## 部署结构

本项目使用 **SQLite 文件数据库**，不是独立的数据库服务，因此不需要
MySQL/PostgreSQL 容器。Docker 中只运行一个应用容器：

```text
contract-review 容器
  ├─ FastAPI + 前端 /ui
  ├─ /app/data/app.db             ← 挂载到宿主机 ./data
  ├─ /app/data/mock_upstream.db   ← 挂载到宿主机 ./data
  ├─ /app/data/attachments/       ← 挂载到宿主机 ./data
  └─ /app/sample_contracts/       ← 已打进镜像
```

数据持久化通过 `./data:/app/data` 完成。容器重建、升级镜像都不会丢数据。

相关文件：

- `Dockerfile`：运行镜像。
- `.dockerignore`：构建上下文排除项。
- `docker-compose.yml`：服务、端口、数据卷、健康检查。

## 快速启动

在放置 `docker-compose.yml` 的目录执行：

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f contract-review
```

访问：

- 前端：`http://<虚拟机IP>:8000/ui/`
- API 文档：`http://<虚拟机IP>:8000/docs`
- 健康检查：`http://<虚拟机IP>:8000/health`

首次启动会自动执行 `scripts/init_db.py`（幂等）：

- 创建本地库与 Mock 库；
- 写入 14 条规则；
- 写入 4 个 Mock 审批单；
- 检查示例合同（镜像内已包含，通常无需重新生成）。

## 填写数据库地址

项目当前使用 SQLite，数据库地址就是**容器内的文件路径**。二选一：

**方式 A：使用配置模板（推荐）**

```bash
cp docker.env.example docker.env
# 编辑 docker.env 中的 DATA_DIR / LOCAL_DB_PATH / MOCK_DB_PATH
docker compose --env-file docker.env up -d --build
```

**方式 B：直接修改 `docker-compose.yml`**

```yaml
environment:
  LOCAL_DB_PATH: "/app/data/app.db"
  MOCK_DB_PATH: "/app/data/mock_upstream.db"
volumes:
  - "./data:/app/data"
```

对应关系：

| 变量 | 含义 | 示例 |
|---|---|---|
| `DATA_DIR` | 宿主机上的数据目录 | `./data` 或 `/srv/contract-review` |
| `LOCAL_DB_PATH` | 容器内审查库路径 | `/app/data/app.db` |
| `MOCK_DB_PATH` | 容器内 Mock 库路径 | `/app/data/mock_upstream.db` |

如果数据库文件要放到其他容器目录，需要同时在 `volumes` 中挂载该目录，例如：

```yaml
environment:
  LOCAL_DB_PATH: "/app/db/app.db"
  MOCK_DB_PATH: "/app/db/mock_upstream.db"
volumes:
  - "/srv/contract-review-db:/app/db"
```

`DATABASE_URL` 只是为将来迁移 PostgreSQL/MySQL 预留的占位，当前代码不会读取。

## 数据持久化与迁移

默认挂载：

```text
./data  →  /app/data
```

`./data` 中包含：

```text
app.db               # 审查任务、解析、命中、结果、日志
mock_upstream.db     # Mock 审批单、附件、评论、故障开关
attachments/         # 下载的合同文件
```

### 从本机迁移已有数据

把本机项目的 `data/` 目录整体复制到虚拟机上的 compose 文件同级目录：

```bash
scp -r ./data user@vm:/path/to/project/
```

然后启动容器即可继续使用原有任务和附件。

SQLite 文件跨 Windows/Linux 通用；附件路径在库中保存为相对路径。

### 备份

```bash
docker compose stop contract-review
tar czf contract-review-data-$(date +%F).tgz data
docker compose start contract-review
```

### 重置演示数据

```bash
docker compose exec contract-review python scripts/init_db.py --reset
```

或者彻底清空：

```bash
docker compose down
rm -rf data
docker compose up -d
```

## 端口与路径

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_PORT` | `8000` | 宿主机端口 |
| `DATA_DIR` | `./data` | SQLite 与附件目录 |
| `QUEUE_MAXSIZE` | `100` | 异步队列长度 |
| `WORKER_CONCURRENCY` | `2` | worker 数量 |
| `OCR_TEXT_MIN_CHARS` | `40` | PDF 文本层少于该值时转 OCR |

例如换端口和数据目录：

```bash
APP_PORT=8080 DATA_DIR=/srv/contract-review-data docker compose up -d
```

## LLM 配置

`docker-compose.yml` 会读取项目根目录 `.env` 中的 `${LLM_*}`，也支持直接用
shell 环境变量覆盖：

```dotenv
LLM_ENABLED=true
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_MODEL=qwen2.5:7b
LLM_API_KEY=
```

注意：

- `UPSTREAM_BASE_URL` 必须保持 `http://127.0.0.1:8000`，这是容器内 Mock 上游的回环地址，不要改成宿主机地址。
- 如果 LLM 服务运行在宿主机，使用 `host.docker.internal`；compose 已添加
  `host.docker.internal:host-gateway` 映射。
- 如果 LLM 是另一个 compose 服务，把 `LLM_BASE_URL` 改成 `http://<服务名>:<端口>/v1`。
- LLM 默认关闭，失败会自动回退模板。

## 在容器内跑闭环演示

```bash
docker compose exec contract-review python scripts/demo_closed_loop.py
```

脚本会重置演示数据，并复用容器内已经在运行的 8000 服务。

## 重新构建

```bash
docker compose build --pull
docker compose up -d
```

`./data` 数据不会受影响。

## 排查

**端口被占用**

```bash
APP_PORT=8080 docker compose up -d
```

**查看日志**

```bash
docker compose logs -f --tail=200 contract-review
```

**健康检查**

```bash
docker compose exec contract-review python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
```

**数据目录权限**

容器默认以 root 运行，通常可写入 `./data`。如果使用自定义 `DATA_DIR` 且出现
权限错误，先确保该目录可写：

```bash
sudo mkdir -p /srv/contract-review-data
sudo chown -R 0:0 /srv/contract-review-data
```

**OCR 导入失败**

镜像已安装 `libgl1`、`libglib2.0-0`、`libgomp1`。如果自行修改基础镜像，
需要保留这些系统库。

## 安全说明

系统没有认证，当前定位是内网演示工具。部署到虚拟机时：

- 不要直接把 8000 端口暴露到公网；
- 用防火墙限制来源 IP；
- 如需多人使用，先在前面加一层带认证的反向代理。

## 关于“数据库容器”

如果后续要换成 PostgreSQL/MySQL，需要修改数据库访问层（当前使用标准库
`sqlite3` 与本地 SQL），再在 compose 中增加 `db` 服务并迁移数据。当前版本
不建议为了“有数据库容器”而引入独立的 SQLite 服务，SQLite 本身不是 C/S 架构。
