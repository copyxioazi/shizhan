# 掌柜智库 Qwen3-8B QLoRA 微调方案

> 本文是唯一设计文档。原始需求见 [智库微调.md](智库微调.md)，保留不动。

## 1. 背景与目标

按 `智库微调.md` 的五项能力，为「掌柜智库」知识库问答构建 Qwen3-8B 的 grounded SFT 数据与 QLoRA 训练链路：

- 4.1.1 行业术语与回答格式适配
- 4.1.2 检索内容忠实回答
- 4.1.3 多片段信息整合
- 4.1.4 证据引用与出处标注
- 4.1.5 资料不足时拒答

真实项目 `d:\pythoncode\kb` 已有 RAG 链路：PDF 导入 → 标题感知切分（250/50）→ BGE-M3 混合检索 → RRF → qwen3-rerank → DeepSeek 生成；上下文格式为 `[n][source][title][url]`。但仓库没有 grounded QA、SFT 数据或引用标注，因此需要合成数据。

硬件边界：

- 本机 RTX 3050 Ti 4GB，无法训练 8B；数据生成与判分在本机 CPU 完成。
- 训练在 ModelScope 免费 24GB GPU（CUDA 13.0.3）完成。
- 不做本地部署，不合并 8B；adapter 是最终产物。

## 2. 需求追溯

| 需求 | 样本占比 | 数据字段 | 评测指标 |
|---|---|---|---|
| 4.1.1 术语/格式 | 15% | `format_template`、`terminology_used`、答案模板 | format_pass、term_accuracy、structure_match |
| 4.1.2 忠实回答 | 45%（与 4.1.4 共用） | `claims`、`evidence`、`expected_behavior=answer` | claim_support_rate、hallucinated_number_rate、answer_correctness |
| 4.1.3 多片段整合 | 20% | 2–3 个 evidence，跨 doc/section | evidence_coverage、integration_completeness |
| 4.1.4 引用标注 | 所有回答类 | `citations`、`contexts`、`[n]` + `【参考来源】` | citation_precision、citation_recall、format_valid |
| 4.1.5 拒答 | 20% | `expected_behavior=refuse/partial/conflict`、`missing_info`、`conflict_values` | refusal_accuracy、false_refusal_rate、missing_info_quality、conflict_both_sides、conflict_neutral |

## 3. 关键决策

- 基座：`Qwen/Qwen3-8B`，非思考模式（`enable_thinking=False`，目标不含 ` thinking`）。
- 语料：掌柜智库 HAK180 手册 + 万用表 PDF 为种子，同域合成扩充到约 200 chunk，冻结。
- 数据契约：45% 忠实+引用 / 20% 拒答 / 20% 多片段 / 15% 术语格式；行内 `[n]` + `【参考来源】`；分级拒答；事实以检索原文为准；训练与推理 prompt 同构。
- 规模：5,000 train / 500 dev / 500 test + 200 条人工抽检金标。
- API：仅 DeepSeek。生成用 `GENERATOR_MODEL`，判分用 `JUDGE_MODEL`（如 `deepseek-reasoner`）+ 确定性规则 + 人工金标校准。
- 工程：`local/` 与 `cloud/` 两个独立 Python 项目，各自 `pyproject.toml`；`shared/` 只放模板与 schema。

## 4. 工作流

```
阶段 A（本机 CPU，一次性）
  种子语料 + 合成文档 → 清洗/切分 → 冻结 corpus
  → 检索构造上下文 → DeepSeek 生成候选 → 规则 + 判分筛选
  → 去重/切分 → data/splits/*.jsonl + 200 金标 + manifest/hash

阶段 B（云端 GPU，只读静态数据）
  上传冻结数据 + Qwen3-8B → 环境探针 → 200 步 smoke
  → 全量 QLoRA（不调 API、不生成数据）→ adapter

阶段 C（评测）
  云端 base/adapter 各跑一遍 test → predictions.jsonl
  本机规则 + DeepSeek 判分 + 200 金标校准 → report
```

数据先构建、冻结、抽检，再训练。训练阶段不构建数据；数据变化必须回到阶段 A 重新冻结。

## 5. 目录结构

```
model_train/
  DESIGN.md
  智库微调.md

  local/                             # 本机 CPU：语料 + 数据
    pyproject.toml
    src/kb_sft_data/                 # config io_utils llm_client schema templates
                                     # chunking corpus retriever sampler renderer
                                     # verifier judge dedup splitter
    scripts/00_probe_env.py 01_convert_pdf.py 02_generate_docs.py
            03_build_corpus.py 04_embed_corpus.py 05_freeze_corpus.py
            06_retrieve_sim.py 07_generate_qa.py 08_verify_rule.py
            09_judge.py 10_build_dataset.py 11_dedup_split.py 12_validate_dataset.py
    prompts/                         # 文档生成、四类 QA、judge、支持性核验
    tests/

  cloud/                             # 云端 GPU：训练 + 评测推理
    pyproject.toml                   # 必须；固定环境
    src/kb_sft_train/                # config schema tokenize renderer train_utils evaluate
    scripts/00_probe_cloud.py 13_train_qlora.py 14_smoke_test.py
            15_eval.py 16_report.py
    configs/train_qlora.yaml eval.yaml
    tests/test_template_isomorphism.py
    notebooks/modelscope_train.ipynb

  shared/                            # 非代码包
    templates/system_prompt.txt user_template.txt qwen3_nonthinking.jinja
    schema/sample.schema.json

  data/                              # 本机生成、上传云端
    raw/hak180/ raw/multimeter/
    corpus/docs/*.md corpus/corpus.jsonl corpus/embeddings.npz corpus/freeze.lock
    canon/fact_registry.yaml terminology_glossary.tsv doc_outlines/*.yaml
    candidates/ verified/ rejected/ raw_responses/<run_id>/
    splits/train.jsonl dev.jsonl test.jsonl
    splits/gold_dev_100.jsonl gold_test_100.jsonl split_manifest.json

  runs/ reports/
```

## 6. 语料

共 23 个文档 / 约 200 chunks：

| Split | 文档 | ~chunks |
|---|---|---|
| train | HAK180 真实；烫金耗材与存储；烫金日常维护；LM-200 安全手册/操作说明；TP-300 操作指南/耗材规格；工业设备维护通用规范；术语与口径表；保修政策 2024/2025（冲突对） | 100–105 |
| dev | FL-450 操作/故障排除；HT-600 安全/维护；售后服务政策；返修换货 SOP | 48–52 |
| test | RS-12 万用表真实 PDF；RS-12 校准安全；BM-100 操作/故障；CT-320 安全手册；保修与延保 2026 | 45–50 |

规则：

- 合成文档每篇 1,800–3,600 字，含标题、小节、警告、表格、版本/生效日期；只使用事实卡，不复制网页文本。
- 事实注册表保证同一事实只有一个值；仅允许两组声明冲突（train 内 2024 vs 2025 保修政策；dev/test 内一对），冲突对不拆 split。
- 清洗：MinIO 图片 → `[图片说明：alt]`；空 chunk 删除；乱码 chunk 标 `quality=low`；全半角数字归一化。
- PDF：PyMuPDF 优先，扫描件回退 MinerU。
- 切分：移植 kb 的标题分节 + `RecursiveCharacterTextSplitter(250, 50)`，table chunk 不切分；`chunk_id = doc_id:section_idx:part`。
- 冻结：`freeze.lock` 记录 corpus.jsonl 与各文档 sha256。

## 7. 检索模拟

- 默认 BGE-M3 dense+sparse（kb venv，CPU，缓存 `embeddings.npz`）：实体过滤 80% → dense/sparse 0.8/0.2 → top10 → HyDE 第二路 → RRF `1/(60+rank)` → 动态截断 3–10 → 打乱上下文顺序。
- 回退：纯 Python BM25（字符 bigram，numpy 倒排）。
- 池策略：train 只检索 train 文档；dev/test 只检索 dev+test 文档。
- 特殊构造：evidence 缺失时注入 rank 3–8；30% distractor；15% 改数字近重复；multi 强制跨 doc/section；no-evidence 经支持性核验；partial = 可答 + 缺失；conflict 强制两篇冲突文档进上下文。

## 8. 数据契约

System prompt（`shared/templates/system_prompt.txt`）规则：

1. 只用【参考内容】，不编造事实、数字、条款或结论。
2. 关键结论后用 `[n]` 标注依据，编号必须与参考内容一致。
3. 不足以回答时明确拒答并列出缺失信息。
4. 只能支持部分时，只答有依据部分并列出无法确认的部分。
5. 证据冲突时并列呈现两种说法及来源，不裁定。
6. 简洁专业中文，优先资料术语；操作步骤用有序列表。
7. 末尾附 `【参考来源】`，只列正文实际引用，格式 `[n] 来源文件名 | 标题 | 链接`。
8. 不输出思考过程或 `<think>`。

User 模板与 kb packing 同构：

```
【参考内容】
[{n}][{source}][{file_title}][{url}]
{content}

【相关实体】
{item_names}

【用户问题】
{question}

请回答：
```

Assistant 类型：

- 忠实：结论 `[n]` + 来源块。
- 拒答：无来源块，列出缺失信息与建议补充。
- 部分：引用已支持部分 + “无法确认的部分”。
- 冲突：两种说法 + 各自 `[n]`，不裁定。

JSONL 字段：`messages`（唯一训练输入）+ `contexts` + `evidence` + `claims` + `citations` + `expected_behavior` + `metadata`。user 文本必须能由 contexts + item_names + question 逐字节重建。

数量：

| Split | faithful | refusal | multi | term/format |
|---|---|---|---|---|
| train | 2250 | 1000 | 1000 | 750 |
| dev | 225 | 100 | 100 | 75 |
| test | 225 | 100 | 100 | 75 |

Qwen3：预渲染 `prompt`（`enable_thinking=False`，以空 ` thinking` 块结尾）与 `completion`（answer + `<|im_end|>`），训练用 `completion_only_loss=True`。`cloud/tests/test_template_isomorphism.py` 断言 token IDs 一致。

## 9. 生成、校验、去重、切分

- 文档生成：outline + fact card → 结构化 JSON；逐数字/日期对事实卡；MinHash 5-gram ≥0.7 重生成。
- QA 生成：1–3 个 evidence bundle，稳定标签 `[C1]`；每次 3 个候选；生成器不写 URL 和来源块；renderer 确定性映射 `[C1]` → `[n]` 并拼来源块。
- 并发：AsyncOpenAI + Semaphore(8)，120s 超时，5 次退避，幂等键，50 条 checkpoint，`DATA_BUDGET_USD` 上限；先 `--dry-run 20`。
- 硬规则：schema/无 think；`[n]` 与来源块双向一致；元数据一致；数字/日期/型号必须在被引用 chunk；gold evidence ⊆ contexts；拒答/部分/冲突结构；禁止裁定措辞；模板格式；prompt ≤3500 / answer ≤700 tokens。
- 判分：DeepSeek 变体，temperature 0；faithfulness/citation/completeness/format/refusal_correct/conflict_neutral；阈值见 `configs`；目标接受率 70–80%，不降阈值。
- 去重：exact hash、3-gram Jaccard ≥0.8、BGE 余弦 ≥0.93；每 `(chunk, fact)` ≤6 条、每 chunk ≤30 条；跨 split 近重复 >0.6 丢弃。
- 切分：按文档/产品族分配；样本 split 由 evidence 文档决定；冲突对同 split；manifest 记录 doc→split、样本数、语料 sha256、seed。最终断言 5000/500/500、200 金标、无跨 split 泄漏、引用格式 100%。

## 10. QLoRA 训练

`cloud/configs/train_qlora.yaml`：

| 项 | 值 |
|---|---|
| 量化 | 4-bit NF4，double quant，compute bf16（capability <8.0 → fp16） |
| LoRA | r=16，alpha=32，dropout=0.05，target q/k/v/o/gate/up/down |
| 序列 | max_length 4096，packing off，completion_only_loss on |
| 批次 | bs 1 × grad_accum 16 |
| 优化 | lr 1e-4，cosine，warmup 3%，2 epochs，paged_adamw_8bit，grad checkpointing |
| 保存 | 每 100 步，保留 3，`--resume auto`，写 `RUN_STATE.json` |

显存估算：4-bit 权重 ~5.5GB + LoRA/optimizer ~0.3GB + 激活 3–5GB + logits ~1.2GB ≈ 10–13GB。

降级链：OOM → max_length 3072/2048、grad_accum 24；bnb 失败 → compute fp16；仍失败 → Unsloth QLoRA；再失败 → bf16 LoRA 1024；TRL 不兼容 → 手写 Trainer + `-100` 掩码。不用 DeepSpeed。

## 11. 云端 runbook

1. 探针：`nvidia-smi`、`df -h`、`mount`、Python、torch CUDA/capability、`Linear4bit` 小算子、pip 联网、`/mnt/data` 持久性、会话时长。
2. `export HF_HOME=/mnt/data/hf MODELSCOPE_CACHE=/mnt/data/ms TMPDIR=/mnt/data/tmp`；`pip install -e cloud`。
3. `modelscope download --model Qwen/Qwen3-8B --local_dir /mnt/data/models/Qwen3-8B`。
4. 上传 `data/splits/*.jsonl` + `data/corpus` + `shared/`。
5. `14_smoke_test.py`（200 条 / 20 步）→ `13_train_qlora.py --resume auto`。
6. `15_eval.py` base/adapter → 预测落盘；本机判分 → `16_report.py`。
7. adapter + tokenizer + config + eval json 打 tar；不合并、不部署。

## 12. 评测与验收

指标：claim_support_rate、hallucinated_number_rate、citation precision/recall/format、refusal_accuracy、false_refusal、missing_info_quality、conflict_both_sides/neutral、evidence_coverage、integration_completeness、format_pass、term_accuracy。

综合分：0.30 faithfulness + 0.20 citation + 0.15 refusal + 0.15 multi + 0.10 format + 0.10 term。

Judge 校准：`gold_dev_100` 上算 exact/±1 一致率与 Cohen's kappa；kappa <0.6 改 rubric 或双判多数；`gold_test_100` 只做最终验收。

验收：faithfulness ≥0.95、数字幻觉 ≤1%；citation precision ≥0.95、recall ≥0.85、format 100%；refusal ≥0.90、false refusal ≤5%；multi completeness ≥0.80；format ≥0.98、term ≥0.90；conflict both-sides/neutral ≥0.95；think 泄漏 0、无效引用 0；综合分相对 base 提升 ≥10pt 且主指标下降 ≤2pt（p<0.05）。

## 13. 风险与未确认项

| 风险 | 缓解 |
|---|---|
| 合成数据自造事实 | 事实卡单一来源；数字规则；judge 只看 chunk |
| 过度拒答 | 精确 20% 配额；no-evidence 与可答低相似配对 |
| 引用/URL 幻觉 | 模型只生成 `[n]`；renderer/后处理按 contexts 重建来源块 |
| 训练/推理不同构 | 单一 shared 模板；token ID 同构测试 |
| bnb / CUDA 13 | cu128 wheel；Linear4bit 探针；fp16/Unsloth/bf16 回退 |
| ModelScope 时限/临时盘/无网 | 探针；每 100 步保存；resume；预测/判分分离 |
| judge 与生成同源 | DeepSeek 变体 + 对抗 prompt + 规则 + 200 金标校准 |
| 记忆化 | 每 chunk 上限、改写、distractor、打乱、留出文档评估 |

未确认项（云端探针先验证）：ModelScope 免费实例时长/持久盘/出网、bitsandbytes 0.50.1 对 CUDA 13.0.3、Qwen3-8B 模板与 0.6B 是否逐字一致、TRL 0.24 + transformers 5.5 的 `completion_only_loss` 行为。
