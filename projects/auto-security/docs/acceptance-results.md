# 验收结果记录

- 日期：2026-10-22
- 环境：Windows 后端 `127.0.0.1:8001`，前端 `5173`；Linux VM `<VM_IP>`，Docker 沙箱镜像 `ase-sandbox:1.0`；PostgreSQL 16 位于 VM `5433`。
- 示例项目：`examples/vuln-demo`

## 已通过

| 验收项 | 方法 | 结果 |
| --- | --- | --- |
| 登录与系统状态 | `POST /api/system/login`、`GET /api/system/status` | `initialized=true`，JWT 正常签发 |
| 创建/启动/四阶段 | API 创建项目并启动 | `environment_scan → code_analysis → vulnerability_verify → report_generate`，最终 `completed` |
| 漏洞与验证 | `vuln-demo` 完整运行 | 5 条漏洞：4 `verified`、1 `skipped`；报告可下载 |
| 关键字搜索（FR-EXEC-03） | 分析阶段日志 | 8 个关键字执行搜索，命中数量与 `file:line` 写入日志 |
| 命令审计（FR-EXEC-05） | 日志查询 | 每条 `exec`/`helper` 均记录命令、`cwd=/workspace`、退出码、耗时、输出摘要 |
| 语法检查（FR-VULN-03） | 修改验证脚本为非法语法 | 对应漏洞 `failed`，日志“验证代码语法检查失败：invalid syntax（行 1）” |
| 1 GB 配额（FR-EXEC-06） | 验证脚本写入 1.1 GB | 在 1.00 GB 处被进程组终止（`exit=125`），写入 error 日志，后续验证被阻断 |
| 路径穿越（FR-EXEC-01） | `helper.py read ../../etc/passwd` | `exit=3`，stderr 包含“路径越界” |
| 命令白名单（FR-EXEC-04） | 执行 `sh -c echo hi` | 抛出 `SandboxCommandNotAllowed`，未执行 |
| 命令超时（FR-EXEC-04） | `sleep(10)`，超时 2 秒 | 抛出 `SandboxCommandTimeout`，进程被终止 |
| 输出截断（FR-EXEC-04） | 输出 100 KB，限制 8 KB | 返回长度 8206 字节，以 `...[truncated]` 结尾 |
| 网络隔离（AC-09） | 容器内连接 `8.8.8.8:53` | `OSError: Network is unreachable` |
| 源码只读/工作区可写（AC-09） | 写 `/src`、`/workspace` | `/src` 失败（Read-only file system），`/workspace` 成功 |
| 容器约束（AC-09） | `docker inspect` | `NetworkMode=none`、`CapDrop=[ALL]`、`no-new-privileges`、`user=1000:1000`、PIDs 128、1 CPU、512 MB |
| 重启清理（FR-ENV-04） | 停止后再次启动 | 先销毁 `r1` 容器，再创建 `r2`，上一轮工作区保留 |
| 临时文件清理（FR-EXEC-06） | 项目完成后检查 `tmp/` | 目录存在且为空 |
| 删除清理（AC-06） | 删除项目 | 容器、VM 工作区、日志/报告目录被删除 |
| 并发限制 | 连续启动 3 个项目 | 前两个 `200`，第三个 `409/2003` |
| WebSocket 鉴权（NFR-SEC-05） | 无效 Token 连接 | 关闭码 `4401` |
| JWT 鉴权 | 无效 JWT 调 `/api/system/me` | `401` |
| 管理员接口权限 | 普通用户调 `/api/system/users` | `403` |
| 默认隔离类型（FR-CONF-05） | 创建项目不传 `isolation_type` | 使用 `isolation.default_type=docker` |
| 镜像缺失（FR-ENV-05） | 临时将 `sandbox.image` 改为不存在的镜像 | 项目 `failed`，日志“沙箱镜像不存在：ase-sandbox:missing”；配置已恢复 |
| 沙箱容器中断 | 运行中只 `docker stop` 当前项目的沙箱容器 | 项目 `failed`，日志“沙箱容器不可用：container ... is not running”，不会生成空报告 |
| Docker/SSH 不可达 | 临时 8002 后端，`DOCKER_HOST=ssh://eval@127.0.0.1:2222` | 项目 `failed`，日志“源码同步失败：Unable to connect to port 2222 on 127.0.0.1” |
| AC-08 在线修改并发 | 临时管理员将并发改为 1，启动两个项目 | 第一个 `200`，第二个 `409/2003`；恢复并发后第二个可启动 |
| 管理员用户列表 | 临时管理员调用 `GET /api/system/users` | `200`，返回 3 个账号 |
| 创建人筛选 | 管理员按 `created_by` 查询项目 | 返回项全部属于该创建人 |
| API Key 脱敏/清空 | 写入 `<test-api-key>` 后读取，再写空字符串 | 读取为脱敏值；清空后为 `""` |
| JWT 过期 | 使用已过期 Token 调 REST/WS | REST `401`；WS 关闭码 `4401` |
| 30 天保留清理 | 插入 31 天前的日志/消息/资源后执行清理 | 旧数据全部删除，新数据保留 |

## 尚未覆盖

- VM Docker daemon 整体停止：需要 root 中断服务，会同时影响 VM 上其他系统；已用不可达 `DOCKER_HOST` 模拟连接失败。
- JWT 自然等待 24 小时：已用过期 Token 验证同一校验路径。
- 真实 LLM 服务：此前用本地 OpenAI 兼容 mock 验证了 LLM 模式与失败降级，未验证外部供应商。
- 前端 UI 的视觉交互（聊天分组、创建人下拉）通过 `tsc` 与生产构建验证，未做浏览器自动化截图。
