# Сравнение подходов Text-to-SQL на базе LLM (Spider Thesis)

Этот проект реализует и воспроизводит экспериментальный фреймворк из работы по сравнению методов Text-to-SQL на датасете Spider:

- `Prompt-only`
- `BM25 Schema-RAG`
- `Embedding Schema-RAG`
- `LoRA-only`
- `LoRA + RAG`

Оценка проводится по двум метрикам:
- `Exec Rate` (доля исполнимых SQL)
- `Exec Acc` (доля SQL с корректным результатом выполнения)

## 1. Структура проекта

```text
.
├── src/
│   ├── demo/                 # FastAPI backend (/ask)
│   ├── prompting/            # Prompt / RAG inference scripts
│   ├── rag/                  # BM25 и embedding retrieval
│   ├── lora/                 # LoRA train/inference
│   ├── eval/                 # Оценка по выполнению SQL
│   └── spider/               # Загрузка Spider и schema-документы
├── demo_frontend/            # Vite + React frontend
├── runs/
│   ├── cache/                # Индексы и кэши
│   └── outputs/              # Предсказания и отчеты
├── scripts/                  # Вспомогательные скрипты
└── run_demo.sh               # Запуск frontend+backend одной командой
```

## 2. Подготовка окружения

```bash
cd <project_root>
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install fastapi uvicorn numpy sentence-transformers torch transformers peft datasets accelerate
```

Frontend:

```bash
cd <project_root>/demo_frontend
npm install
```

## 3. Данные и индексы

Ожидаемые пути Spider:
- `data/spider/tables.json`
- `data/spider/train_spider.json`
- `data/spider/dev.json`
- `data/spider/database/*/*.sqlite`

Проверка:

```bash
cd <project_root>
bash scripts/01_check_data.sh
```

Построение schema docs + BM25:

```bash
cd <project_root>
bash scripts/02_build_rag_index.sh
```

Embedding index (опционально):

```bash
python3 src/rag/build_embeddings.py \
  --docs runs/cache/spider_schema_docs.jsonl \
  --out runs/cache/embed_schema \
  --model intfloat/e5-small-v2
```

## 4. Prompt/RAG запуск

Требуется ключ API:

```bash
export DEEPSEEK_API_KEY="your_key_here"
```

Prompt-only:

```bash
python3 src/prompting/run_api_prompt.py \
  --dev_json data/spider/dev.json \
  --out runs/outputs/pred_dev_promptonly.jsonl \
  --limit 1034 \
  --api_key "$DEEPSEEK_API_KEY" \
  --model deepseek-chat \
  --no_rag
```

BM25-RAG:

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

Embedding-RAG:

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

Оценка:

```bash
python3 src/eval/eval_exec.py \
  --pred_jsonl runs/outputs/pred_dev_bm25rag.jsonl \
  --db_root data/spider/database \
  --out runs/outputs/eval_dev_bm25rag.json
```

## 5. LoRA

LoRA-only training:

```bash
python3 src/lora/build_loraonly_cache.py \
  --train_json data/spider/train_spider.json \
  --dev_json data/spider/dev.json \
  --out_train runs/cache/loraonly_train_all8659.jsonl \
  --out_dev runs/cache/loraonly_dev_1034.jsonl

python3 src/lora/train_t5_lora_spider_loraonly.py \
  --train_cache_jsonl runs/cache/loraonly_train_all8659.jsonl \
  --dev_cache_jsonl runs/cache/loraonly_dev_1034.jsonl \
  --out_dir runs/outputs/loraonly_flan_t5_base_all8659_ep3
```

LoRA+RAG inference:

```bash
python3 src/lora/infer_t5_lora_spider.py \
  --dev_json data/spider/dev.json \
  --bm25_index runs/cache/bm25_schema \
  --adapter_dir runs/outputs/lora_flan_t5_base_spider_all8659_allowed_cache \
  --api_key "$DEEPSEEK_API_KEY" \
  --out runs/outputs/pred_dev_lora_rag.jsonl \
  --limit 1034
```

## 6. Результаты (Spider dev, n=1034)

| Метод | Exec Rate | Exec Acc |
|---|---:|---:|
| Prompt-only | 0.1441 | 0.1141 |
| BM25 Schema-RAG | 0.9420 | 0.6422 |
| Embedding Schema-RAG | 0.9971 | 0.7340 |
| LoRA-only | 0.1306 | 0.0783 |
| LoRA + RAG | 0.9855 | 0.5996 |

## 7. Demo

Одна команда:

```bash
cd <project_root>
./run_demo.sh
```

Адреса:
- Frontend: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:8000`
