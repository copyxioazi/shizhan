# 闭环演示步骤

## 一键运行

```bash
.venv/Scripts/python.exe scripts/demo_closed_loop.py
```

脚本会：

1. 重置本地库、Mock 库并确定性生成示例合同；
2. 若 `http://127.0.0.1:8000` 没有服务，自动启动 uvicorn，结束后关闭；
3. 依次执行拉取、审查、阻塞恢复、幂等回写，并校验预期结果；
4. 任一步不符合预期时以非零退出码结束。

已有服务时可复用当前数据：

```bash
.venv/Scripts/python.exe scripts/demo_closed_loop.py --no-reset
```

## 目标流程

1. 连续拉取两次，验证按 `approval_code` 去重（4 个新增，第二次 0 个）。
2. 审查 `APV-2026-001`（PDF 高风险）：预付款 60%、账期 90 天、自动续约、对方管辖。
3. 审查 `APV-2026-002`（DOCX 中风险）：账期 75 天、自动续约、保密缺失。
4. 审查 `APV-2026-003`（扫描 PNG）：RapidOCR、`partial`、低风险。
5. 审查 `APV-2026-004`：附件不可用导致 `blocked + MISSING_ATTACHMENT`。
6. 调用 Mock restore 恢复附件 5，重试到 `done`。
7. 重复回写同一 `review_id`，本地短路，上游仍只有一条评论。
8. 打印最终任务表与 Mock 评论总数。

## 预期输出（节选）

```text
[1] 连续拉取两次，验证去重
  新增 4 个，第二次新增 0 个

[2] 一键审查 4 类合同
  APV-2026-001: done / success | parse=success ocr=False | risk=high | focus=4
  APV-2026-002: done / success | parse=partial ocr=False | risk=medium | focus=4
  APV-2026-003: done / success | parse=partial ocr=True | risk=low | focus=2

[3] 缺失附件 → blocked → restore → retry
  APV-2026-004: blocked / MISSING_ATTACHMENT
  重试入队：resume=download retry=1
  APV-2026-004: done / success

[4] 重复回写，验证幂等
  本地短路=True，上游评论数=1
```

## 手动演示

```bash
.venv/Scripts/python.exe scripts/init_db.py --reset
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000/ui/>：

1. 点「拉取待办」；
2. 对 `APV-2026-001` 点「一键审查」，等待状态变为 `已完成`；
3. 对 `APV-2026-004` 点「一键审查」，观察 `已阻塞`；
4. 在 Mock 面板把附件 ID 设为 5，点「恢复附件」，再点「重试」；
5. 观察任务变为 `已完成 / 已回写`。

## 验收对应

| 验收项 | 演示步骤 |
|---|---|
| 拉取去重 | 1 |
| 附件下载/校验 | 2、3、5 |
| 文档与扫描件解析 | 2、3、4 |
| 规则命中与风险 | 2、3、4 |
| 结果保存与回写 | 2、3、4、7 |
| 阻塞与分阶段重试 | 5、6 |
| 启动恢复 | `tests/test_recovery.py` |
| 完整闭环 | 全部 |
