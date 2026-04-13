# 基于大语言模型的 Text-to-SQL 方法比较研究（Spider Thesis）

本项目实现并复现了论文中的 Text-to-SQL 对比实验框架，重点比较以下技术路线在 Spider 数据集上的表现：

- `Prompt-only`（仅提示）
- `BM25 Schema-RAG`（稀疏检索增强）
- `Embedding Schema-RAG`（向量语义检索增强）
- `LoRA-only`（参数高效微调，不使用显式 schema 检索）
- `LoRA + RAG`（LoRA 与 schema 检索结合）

系统支持从自然语言问题生成 SQLite SQL，并以“可执行率（Exec Rate）+执行准确率（Exec Acc）”进行评估。

俄语版本文档见：`README.ru.md`

## 1. 项目结构

```text
.
├── src/
│   ├── demo/                 # FastAPI 后端（/ask）
│   ├── prompting/            # Prompt / RAG 推理脚本
│   ├── rag/                  # BM25 与向量检索构建、检索
│   ├── lora/                 # LoRA 训练与推理
│   ├── eval/                 # 执行级评估
│   └── spider/               # Spider 数据加载与 schema 文档构建
├── demo_frontend/            # Vite + React 前端
├── runs/
│   ├── cache/                # 检索索引、LoRA cache
│   └── outputs/              # 预测结果与评估结果
├── scripts/                  # 数据检查、索引构建等脚本
└── run_demo.sh               # 一键启动前后端
```

## 2. 环境准备

建议 Python 3.10+，并在项目根目录使用虚拟环境：

```bash
cd <project_root>
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install fastapi uvicorn numpy sentence-transformers torch transformers peft datasets accelerate
```

前端依赖：

```bash
cd <project_root>/demo_frontend
npm install
```

## 3. 数据准备与检查

项目默认使用 Spider 数据路径：

- `data/spider/tables.json`
- `data/spider/train_spider.json`
- `data/spider/dev.json`
- `data/spider/database/*/*.sqlite`

检查数据完整性：

```bash
cd <project_root>
bash scripts/01_check_data.sh
```

## 4. 构建 schema 检索索引

先构建 schema 文档和 BM25 索引：

```bash
cd <project_root>
bash scripts/02_build_rag_index.sh
```

可选：构建向量检索索引（Embedding-RAG）：

```bash
python3 src/rag/build_embeddings.py \
  --docs runs/cache/spider_schema_docs.jsonl \
  --out runs/cache/embed_schema \
  --model intfloat/e5-small-v2
```

## 5. Prompt / RAG 推理与评估

`src/prompting/run_api_prompt.py` 支持三种模式：

- `--no_rag`：Prompt-only
- `--retriever bm25`：BM25-RAG
- `--retriever embed`：Embedding-RAG

需要 DeepSeek API Key（示例）：

```bash
export DEEPSEEK_API_KEY="your_key_here"
```

### 5.1 Prompt-only

```bash
python3 src/prompting/run_api_prompt.py \
  --dev_json data/spider/dev.json \
  --out runs/outputs/pred_dev_promptonly.jsonl \
  --limit 1034 \
  --api_key "$DEEPSEEK_API_KEY" \
  --model deepseek-chat \
  --no_rag
```

### 5.2 BM25-RAG

```bash
python3 src/prompting/run_api_prompt.py \
  --dev_json data/spider/dev.json \
  --bm25_index runs/cache/bm25_schema \
  --out runs/outputs/pred_dev_bm25rag.jsonl \
  --limit 1034 \
  --api_key "$DEEPSEEK_API_KEY" \
  --model deepseek-chat \
  --retriever bm25
```

### 5.3 Embedding-RAG

```bash
python3 src/prompting/run_api_prompt.py \
  --dev_json data/spider/dev.json \
  --embed_index runs/cache/embed_schema \
  --out runs/outputs/pred_dev_embedrag.jsonl \
  --limit 1034 \
  --api_key "$DEEPSEEK_API_KEY" \
  --model deepseek-chat \
  --retriever embed
```

### 5.4 评估（Exec Rate / Exec Acc）

```bash
python3 src/eval/eval_exec.py \
  --pred_jsonl runs/outputs/pred_dev_bm25rag.jsonl \
  --db_root data/spider/database \
  --out runs/outputs/eval_dev_bm25rag.json
```

## 6. LoRA 训练与推理

### 6.1 LoRA-only（不使用 RAG）

先构建 LoRA-only cache：

```bash
python3 src/lora/build_loraonly_cache.py \
  --train_json data/spider/train_spider.json \
  --dev_json data/spider/dev.json \
  --out_train runs/cache/loraonly_train_all8659.jsonl \
  --out_dev runs/cache/loraonly_dev_1034.jsonl
```

训练：

```bash
python3 src/lora/train_t5_lora_spider_loraonly.py \
  --train_cache_jsonl runs/cache/loraonly_train_all8659.jsonl \
  --dev_cache_jsonl runs/cache/loraonly_dev_1034.jsonl \
  --out_dir runs/outputs/loraonly_flan_t5_base_all8659_ep3
```

推理：

```bash
python3 src/lora/infer_t5_lora_spider_loraonly.py \
  --dev_json data/spider/dev.json \
  --adapter_dir runs/outputs/loraonly_flan_t5_base_all8659_ep3 \
  --out runs/outputs/pred_dev_loraonly.jsonl \
  --limit 1034
```

### 6.2 LoRA + RAG（论文主线）

使用已有 cache 训练（示例）：

```bash
python3 src/lora/train_t5_lora_spider.py \
  --train_cache_jsonl runs/cache/lora_train_all_allowed.jsonl \
  --dev_cache_jsonl runs/cache/lora_dev_500_allowed.jsonl \
  --out_dir runs/outputs/lora_flan_t5_base_spider_all8659_allowed_cache
```

推理（含执行反馈候选 + aggressive repair）：

```bash
python3 src/lora/infer_t5_lora_spider.py \
  --dev_json data/spider/dev.json \
  --bm25_index runs/cache/bm25_schema \
  --adapter_dir runs/outputs/lora_flan_t5_base_spider_all8659_allowed_cache \
  --api_key "$DEEPSEEK_API_KEY" \
  --out runs/outputs/pred_dev_lora_rag.jsonl \
  --limit 1034
```

## 7. 论文复现实验结果（Spider dev，n=1034）

以下为当前仓库 `runs/outputs` 中对应结果文件的指标：

| 方法 | Exec Rate | Exec Acc | 结果文件 |
|---|---:|---:|---|
| Prompt-only | 0.1441 | 0.1141 | `eval_dev1034_promptonly_20260120_080337.json` |
| BM25 Schema-RAG | 0.9420 | 0.6422 | `eval_dev1034_bm25rag_20260120_080337.json` |
| Embedding Schema-RAG | 0.9971 | 0.7340 | `eval_dev1034_embedrag_20260120_080337.json` |
| LoRA-only | 0.1306 | 0.0783 | `eval_dev1034_loraonly_ep3_20260120_143003.json` |
| LoRA + RAG | 0.9855 | 0.5996 | `eval_dev1034_lora_all8659_egs_aggrrepair_20260120_175500.json` |

## 8. Demo 系统运行

### 8.1 一键启动前后端

```bash
cd <project_root>
./run_demo.sh
```

启动后访问：

- Frontend: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:8000`

### 8.2 手动启动

后端：

```bash
cd <project_root>
source .venv/bin/activate
python -m uvicorn src.demo.api:app --reload --host 127.0.0.1 --port 8000
```

前端：

```bash
cd <project_root>/demo_frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

## 9. API 说明（Demo）

后端核心接口：

- `POST /ask`

请求体示例：

```json
{
  "question": "How many singers do we have?",
  "db_id": "concert_singer",
  "method": "embed-rag"
}
```

`method` 支持：

- `prompt-only`
- `bm25-rag`
- `embed-rag`
- `lora-only`
- `lora-rag`

## 10. 注意事项

- 本项目部分实验依赖 DeepSeek API，需准备有效 API Key。
- `Embedding-RAG` 首次构建向量索引会下载 embedding 模型。
- `LoRA` 训练对显存/内存有要求，建议先小规模 (`--limit`) 验证流程再跑全量。
- 评估指标为执行级指标（基于 SQLite 执行结果比较），更贴近可用性。
