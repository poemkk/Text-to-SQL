# A²V-SQL: Generate-Validate-Repair-Select for Reliable Text-to-SQL

A²V-SQL is a research prototype for improving the reliability of LLM-based Text-to-SQL systems. Instead of treating a single LLM output as the final answer, the project wraps SQL generation in an execution-aware closed loop:

```text
generate -> validate -> repair -> select
```

The framework uses existing LLMs as candidate SQL generators and uses database execution as an external validator. It combines Schema-RAG, execution validation, error-feedback repair, multi-candidate selection, semantic evidence-aware selection, and multi-backend dialect validation.

This repository supports the experiments and prototype system described in the thesis:

> Text-to-SQL на основе крупных языковых моделей: исследование и прототипирование междоменной системы

## Key Ideas

- **Generate**: create SQL candidates with Prompt-only, BM25 Schema-RAG, Embedding Schema-RAG, LoRA-only, LoRA + RAG, or multi-LLM generation.
- **Validate**: execute candidate SQL against SQLite and record `exec_ok`, result rows, latency, and database error messages.
- **Repair**: feed execution errors or result mismatch evidence back into an LLM repair prompt, then re-validate repaired SQL.
- **Select**: choose the final SQL from original and repaired candidates using practical evidence. The project includes rule-based selectors, result-consistency voting, EASE-Selector, and LLM pairwise correction.
- **Multi-backend validation**: test selected SQLite-oriented SQL on DuckDB, PostgreSQL, and MySQL, then apply dialect-aware normalization, repair, and candidate selection.
- **Cross-task A²V transfer**: demonstrate the generate-validate-repair idea on Python and Java code-generation tasks.

## Repository Structure

```text
.
├── configs/                         # experiment configuration templates
├── data/                            # local Spider dataset location, ignored by git
├── demo_backend/                    # FastAPI prototype backend
├── demo_frontend/                   # React + Vite prototype frontend
├── docs/                            # thesis/prototype notes and method documentation
├── runs/                            # local experiment cache/output directory, ignored by git
├── scripts/                         # setup, RAG, LoRA, analysis, and demo helper scripts
├── src/a2v/                         # A²V-SQL experiment pipeline
├── run_demo.sh                      # one-command local prototype launcher
└── README.md
```

The most important pipeline scripts are:

```text
src/a2v/01_build_candidates.py                  # build candidate pools
src/a2v/02_validate_candidates.py               # SQLite execution validation
src/a2v/03_score_candidates.py                  # score candidates against execution result
src/a2v/04_select_candidates.py                 # rule-based selector
src/a2v/04b_select_candidates_vote.py           # result-consistency selector
src/a2v/06c_repair_strong_candidates.py         # stronger error-feedback repair
src/a2v/07c_select_after_strong_repair_practical.py
src/a2v/09_multibackend_duckdb.py               # DuckDB validation
src/a2v/09b_multibackend_postgres.py            # PostgreSQL validation
src/a2v/09c_multibackend_mysql.py               # MySQL validation
src/a2v/10_duckdb_dialect_repair.py             # DuckDB dialect repair + candidate select
src/a2v/10b_postgres_dialect_repair.py          # PostgreSQL dialect repair + candidate select
src/a2v/10c_mysql_dialect_repair.py             # MySQL dialect repair + candidate select
src/a2v/12_multibackend_final_summary.py        # multi-backend summary table
src/a2v/12b_multibackend_select.py              # cross-backend evidence selector
src/a2v/17_learned_selector.py                  # EASE selector training/diagnostics
src/a2v/18_build_semantic_selector_data.py      # pairwise selector data builder
src/a2v/19_train_semantic_selector.py           # semantic selector training
src/a2v/20_select_semantic_selector.py          # semantic selector inference
src/a2v/21_llm_pairwise_correction_selector.py  # LLM pairwise correction selector
```

## Environment Setup

Python 3.11 is recommended.

```bash
cd Text-to-SQL
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

Install the core Python dependencies used by the prototype and experiments:

```bash
python -m pip install \
  fastapi uvicorn pydantic \
  numpy pandas scikit-learn scipy \
  sentence-transformers transformers datasets accelerate peft torch \
  duckdb psycopg2-binary pymysql cryptography openai
```

Install frontend dependencies:

```bash
cd demo_frontend
npm install
cd ..
```

Create a local environment file if you want to call an online LLM API:

```bash
cp .env.example .env
```

Then edit `.env` locally:

```text
DEEPSEEK_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
```

Do not commit `.env`. It is ignored by git.

## Data Preparation

The Spider dataset is expected locally under:

```text
data/spider/tables.json
data/spider/train_spider.json
data/spider/dev.json
data/spider/database/*/*.sqlite
```

The dataset is not committed to this repository. Check the local dataset layout with:

```bash
bash scripts/01_check_data.sh
```

Build schema documents and retrieval indexes:

```bash
bash scripts/02_build_rag_index.sh
```

Optional embedding index:

```bash
python src/rag/build_embeddings.py \
  --docs runs/cache/spider_schema_docs.jsonl \
  --out runs/cache/embed_schema \
  --model intfloat/e5-small-v2
```

## Main A²V-SQL Pipeline

A typical Spider dev experiment follows this order.

### 1. Build and Validate Candidates

```bash
python src/a2v/01_build_candidates.py
python src/a2v/02_validate_candidates.py
python src/a2v/03_score_candidates.py
```

### 2. Select Initial SQL

```bash
python src/a2v/04_select_candidates.py \
  --in_file runs/outputs/a2v/scored_spider1034.jsonl \
  --out runs/outputs/a2v/selected_spider1034.jsonl

python src/a2v/04b_select_candidates_vote.py \
  --in_file runs/outputs/a2v/scored_spider1034.jsonl \
  --out runs/outputs/a2v/selected_vote_spider1034.jsonl
```

### 3. Repair and Re-select

```bash
python src/a2v/06c_repair_strong_candidates.py
python src/a2v/07c_select_after_strong_repair_practical.py
python src/a2v/11_final_metrics_summary.py
```

The important research distinction is that repair expands the candidate pool, while select decides which candidate becomes the final SQL.

## Semantic EASE Selector

EASE-Selector formulates candidate selection as evidence-aware semantic preference ranking. The selector uses only inference-time evidence, such as question text, schema text, SQL structure, execution status, result summary, result-consistency support, and repair trace. Gold SQL and gold execution results are used only to build training labels, not as selector inputs.

Build pairwise selector data:

```bash
python src/a2v/18_build_semantic_selector_data.py \
  --in_file runs/outputs/a2v/multillm/scored_multillm_spider1034.jsonl \
  --tables data/spider/tables.json \
  --out_dir runs/outputs/a2v/semantic_selector/multillm \
  --folds 5 \
  --max_pairs_per_item 80 \
  --also_write_fit_all
```

Train one fold:

```bash
python src/a2v/19_train_semantic_selector.py \
  --train_jsonl runs/outputs/a2v/semantic_selector/multillm/fold_0/train_pairs.jsonl \
  --dev_jsonl runs/outputs/a2v/semantic_selector/multillm/fold_0/dev_pairs.jsonl \
  --out_dir runs/outputs/a2v/semantic_selector/models/multillm_fold0_codebert \
  --model_name microsoft/codebert-base \
  --max_length 512 \
  --epochs 3 \
  --batch_size 8 \
  --gradient_accumulation_steps 2 \
  --lr 2e-5
```

Run selector inference:

```bash
python src/a2v/20_select_semantic_selector.py \
  --in_file runs/outputs/a2v/multillm/scored_multillm_spider1034.jsonl \
  --tables data/spider/tables.json \
  --model_dir runs/outputs/a2v/semantic_selector/models/multillm_fold0_codebert \
  --out runs/outputs/a2v/semantic_selector/selected_multillm_fold0.jsonl \
  --summary_out runs/outputs/a2v/semantic_selector/summary_multillm_fold0.md
```

## Multi-backend Validation and Dialect Repair

The project evaluates whether SQLite-oriented SQL can be validated and repaired on DuckDB, PostgreSQL, and MySQL.

### DuckDB

DuckDB runs in-process:

```bash
python src/a2v/09_multibackend_duckdb.py
python src/a2v/10_duckdb_dialect_repair.py
```

If an LLM repair run is interrupted, resume safely:

```bash
python src/a2v/10_duckdb_dialect_repair.py --resume
```

### PostgreSQL and MySQL with Docker

PostgreSQL:

```bash
docker run --name a2v-postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=a2v \
  -p 5432:5432 \
  -d postgres:16
```

MySQL:

```bash
docker run --name a2v-mysql \
  -e MYSQL_ROOT_PASSWORD=mysql \
  -p 3307:3306 \
  -d mysql:8
```

Then run:

```bash
python src/a2v/09b_multibackend_postgres.py
python src/a2v/10b_postgres_dialect_repair.py

python src/a2v/09c_multibackend_mysql.py
python src/a2v/10c_mysql_dialect_repair.py
```

Resume interrupted LLM repair runs:

```bash
python src/a2v/10b_postgres_dialect_repair.py --resume
python src/a2v/10c_mysql_dialect_repair.py --resume
```

Build the multi-backend select output and summary:

```bash
python src/a2v/12b_multibackend_select.py
python src/a2v/12_multibackend_final_summary.py
```

The summary reports the staged improvement:

```text
Before Same Result       # raw selected SQL
After First Repair Same  # first LLM repair candidate, before candidate selection
After Select Same        # best candidate after validate + select
```

## Interactive Prototype

The repository includes a local A²V-SQL prototype with a FastAPI backend and a React frontend. The UI demonstrates schema grounding, candidate SQL traces, execution validation, repair evidence, EASE final selection, and Python/Java transfer examples.

Run both backend and frontend:

```bash
./run_demo.sh
```

Open:

```text
Frontend: http://127.0.0.1:5173
Backend : http://127.0.0.1:8000
```

Manual backend/frontend startup:

```bash
python -m uvicorn --app-dir demo_backend main:app --reload --host 127.0.0.1 --port 8000

cd demo_frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

## Reported Thesis Results

The thesis reports the following high-level findings on Spider dev (`n = 1034`):

| Stage / Method | Execution Accuracy |
|---|---:|
| Prompt-only | 0.114 |
| Embedding Schema-RAG | 0.734 |
| Error-feedback repair | 0.779 |
| EASE-Selector | 0.834 |

The key conclusion is that reliability is improved not only by stronger SQL generation, but by the complete system process that validates, repairs, and selects among candidates.

## Notes on Reproducibility

- Large datasets, model checkpoints, virtual environments, and experiment outputs are intentionally ignored by git.
- `runs/` is a local cache/output directory and should be regenerated locally.
- PostgreSQL and MySQL experiments require local Docker containers or equivalent running database services.
- LLM API-based scripts require local API keys in `.env` or exported environment variables.
- Exact numeric results may vary if online LLM calls are re-run with different model versions or decoding behavior.

## Security and Safety

This is a research prototype, not a production SQL service. Do not expose it directly to untrusted users or production databases. The prototype executes generated SQL during validation, so it should be used only with local benchmark databases or disposable test databases.

## License

No license has been declared yet. If this repository is made public, add an explicit license before reuse or redistribution.
