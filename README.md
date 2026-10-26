# 项目集合

本仓库用于存放多个独立项目，每个项目位于 `projects/` 下的独立目录。

## 项目列表

- [自动化安全评估系统](projects/auto-security/README.md) — 基于 FastAPI + React + Docker 沙箱的自动化安全评估系统，支持规则引擎、LLM 多角色、ReAct 工具循环与可选的 LangGraph 编排。
- [合同审批审查系统](projects/contract-approval-review-system/README.md) — 基于 FastAPI + SQLite 的合同审批自动审查系统，支持 PDF/DOCX/OCR 解析、14 条规则的证据审查、Mock 审批系统、异步流水线与幂等评论回写。
- [掌柜智库 Qwen3-8B QLoRA 微调](projects/kb-sft-qlora/README.md) — 本地 CPU 合成 grounded SFT 数据，云端 GPU 做 Qwen3-8B QLoRA 训练，覆盖术语格式、忠实回答与引用、多片段整合与分级拒答。

## 目录约定

```text
.
├── README.md                 # 本索引
├── .gitignore                # 仓库级通用忽略规则
└── projects/
    ├── auto-security/                    # 自动化安全评估系统
    ├── contract-approval-review-system/  # 合同审批审查系统
    └── kb-sft-qlora/                     # 掌柜智库 Qwen3-8B QLoRA
        ├── local/                        # CPU 数据管线
        ├── cloud/                        # GPU QLoRA 训练/评测
        ├── shared/                       # prompt 模板与 schema
        └── README.md
```

新增项目时，在 `projects/` 下创建独立目录，并在本文件的“项目列表”中补充一行链接。

## 安全约定

- 每个项目独立维护 `.env`，不要把真实密码、Token、SSH 私钥提交到仓库。
- `.gitnexus/`、`runtime_logs/`、`reports/`、`pgdata/`、数据库备份等本地产物已在根 `.gitignore` 中排除。
- 各项目的启动方式、依赖和环境要求见项目自己的 README。
