# A²V-SQL: Generate-Validate-Repair-Select для надёжного Text-to-SQL

A²V-SQL — исследовательский прототип для повышения надёжности LLM-based Text-to-SQL систем. Вместо того чтобы считать одиночный ответ большой языковой модели окончательным результатом, проект помещает генерацию SQL в замкнутый цикл проверки исполнения:

```text
generate -> validate -> repair -> select
```

Фреймворк использует существующие LLM как генераторы SQL-кандидатов, а среду выполнения базы данных — как внешний валидатор. В проекте объединены Schema-RAG, execution validation, error-feedback repair, multi-candidate selection, evidence-aware semantic selection и multi-backend dialect validation.

Репозиторий содержит экспериментальный код и интерактивный прототип, связанные с магистерской работой:

> Text-to-SQL на основе крупных языковых моделей: исследование и прототипирование междоменной системы

## Основная идея

- **Generate**: формирование SQL-кандидатов с помощью Prompt-only, BM25 Schema-RAG, Embedding Schema-RAG, LoRA-only, LoRA + RAG или multi-LLM generation.
- **Validate**: выполнение SQL-кандидатов в SQLite и сохранение признаков `exec_ok`, результата выполнения, задержки и сообщения об ошибке базы данных.
- **Repair**: использование ошибки выполнения или признаков несовпадения результата как feedback-сигнала для LLM repair prompt, после чего исправленный SQL снова проходит валидацию.
- **Select**: выбор итогового SQL из исходных и исправленных кандидатов на основе практических evidence-признаков. В проекте реализованы rule-based selector, result-consistency voting, EASE-Selector и LLM pairwise correction.
- **Multi-backend validation**: проверка SQLite-ориентированных SQL на DuckDB, PostgreSQL и MySQL с последующей dialect-aware normalization, repair и candidate selection.
- **Cross-task A²V transfer**: демонстрация идеи generate-validate-repair на задачах генерации кода Python и Java.

## Структура репозитория

```text
.
├── configs/                         # шаблоны конфигураций экспериментов
├── data/                            # локальное расположение Spider dataset, не коммитится
├── demo_backend/                    # FastAPI backend интерактивного прототипа
├── demo_frontend/                   # React + Vite frontend интерактивного прототипа
├── docs/                            # заметки по прототипу, selector и методологии
├── runs/                            # локальные кэши и выходы экспериментов, не коммитятся
├── scripts/                         # вспомогательные скрипты setup, RAG, LoRA, analysis, demo
├── src/a2v/                         # основной экспериментальный pipeline A²V-SQL
├── run_demo.sh                      # запуск backend + frontend одной командой
└── README.md
```

Ключевые скрипты pipeline:

```text
src/a2v/01_build_candidates.py                  # построение candidate pool
src/a2v/02_validate_candidates.py               # execution validation в SQLite
src/a2v/03_score_candidates.py                  # оценка кандидатов по результату выполнения
src/a2v/04_select_candidates.py                 # rule-based selector
src/a2v/04b_select_candidates_vote.py           # result-consistency selector
src/a2v/06c_repair_strong_candidates.py         # усиленный error-feedback repair
src/a2v/07c_select_after_strong_repair_practical.py
src/a2v/09_multibackend_duckdb.py               # validation в DuckDB
src/a2v/09b_multibackend_postgres.py            # validation в PostgreSQL
src/a2v/09c_multibackend_mysql.py               # validation в MySQL
src/a2v/10_duckdb_dialect_repair.py             # DuckDB dialect repair + candidate select
src/a2v/10b_postgres_dialect_repair.py          # PostgreSQL dialect repair + candidate select
src/a2v/10c_mysql_dialect_repair.py             # MySQL dialect repair + candidate select
src/a2v/12_multibackend_final_summary.py        # итоговая таблица multi-backend эксперимента
src/a2v/12b_multibackend_select.py              # cross-backend evidence selector
src/a2v/17_learned_selector.py                  # обучение/диагностика EASE selector
src/a2v/18_build_semantic_selector_data.py      # построение pairwise данных для selector
src/a2v/19_train_semantic_selector.py           # обучение semantic selector
src/a2v/20_select_semantic_selector.py          # inference semantic selector
src/a2v/21_llm_pairwise_correction_selector.py  # LLM pairwise correction selector
```

## Подготовка окружения

Рекомендуется Python 3.11.

```bash
cd Text-to-SQL
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

Установите основные Python-зависимости для прототипа и экспериментов:

```bash
python -m pip install \
  fastapi uvicorn pydantic \
  numpy pandas scikit-learn scipy \
  sentence-transformers transformers datasets accelerate peft torch \
  duckdb psycopg2-binary pymysql cryptography openai
```

Установите зависимости frontend:

```bash
cd demo_frontend
npm install
cd ..
```

Если планируется запуск скриптов с online LLM API, создайте локальный `.env`:

```bash
cp .env.example .env
```

Затем укажите ключи локально:

```text
DEEPSEEK_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
```

Файл `.env` не должен попадать в Git. Он уже добавлен в `.gitignore`.

## Подготовка данных

Spider dataset ожидается локально по следующим путям:

```text
data/spider/tables.json
data/spider/train_spider.json
data/spider/dev.json
data/spider/database/*/*.sqlite
```

Датасет не включён в репозиторий. Проверить локальную структуру можно командой:

```bash
bash scripts/01_check_data.sh
```

Построить schema documents и BM25 index:

```bash
bash scripts/02_build_rag_index.sh
```

Опционально построить embedding index:

```bash
python src/rag/build_embeddings.py \
  --docs runs/cache/spider_schema_docs.jsonl \
  --out runs/cache/embed_schema \
  --model intfloat/e5-small-v2
```

## Основной A²V-SQL pipeline

Типичный эксперимент на Spider dev выполняется в следующем порядке.

### 1. Построение и валидация кандидатов

```bash
python src/a2v/01_build_candidates.py
python src/a2v/02_validate_candidates.py
python src/a2v/03_score_candidates.py
```

### 2. Первичный выбор SQL

```bash
python src/a2v/04_select_candidates.py \
  --in_file runs/outputs/a2v/scored_spider1034.jsonl \
  --out runs/outputs/a2v/selected_spider1034.jsonl

python src/a2v/04b_select_candidates_vote.py \
  --in_file runs/outputs/a2v/scored_spider1034.jsonl \
  --out runs/outputs/a2v/selected_vote_spider1034.jsonl
```

### 3. Repair и повторный select

```bash
python src/a2v/06c_repair_strong_candidates.py
python src/a2v/07c_select_after_strong_repair_practical.py
python src/a2v/11_final_metrics_summary.py
```

Важно различать два этапа: repair расширяет candidate pool, а select выбирает, какой кандидат станет итоговым SQL.

## Semantic EASE Selector

EASE-Selector формулирует candidate selection как evidence-aware semantic preference ranking. На вход selector получает только признаки, доступные во время inference: вопрос, schema text, SQL structure, execution status, result summary, result-consistency support и repair trace. Gold SQL и gold execution result используются только для построения обучающих меток, но не передаются selector как входные признаки.

Построение pairwise данных:

```bash
python src/a2v/18_build_semantic_selector_data.py \
  --in_file runs/outputs/a2v/multillm/scored_multillm_spider1034.jsonl \
  --tables data/spider/tables.json \
  --out_dir runs/outputs/a2v/semantic_selector/multillm \
  --folds 5 \
  --max_pairs_per_item 80 \
  --also_write_fit_all
```

Обучение одного fold:

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

Запуск inference:

```bash
python src/a2v/20_select_semantic_selector.py \
  --in_file runs/outputs/a2v/multillm/scored_multillm_spider1034.jsonl \
  --tables data/spider/tables.json \
  --model_dir runs/outputs/a2v/semantic_selector/models/multillm_fold0_codebert \
  --out runs/outputs/a2v/semantic_selector/selected_multillm_fold0.jsonl \
  --summary_out runs/outputs/a2v/semantic_selector/summary_multillm_fold0.md
```

## Multi-backend validation и dialect repair

Проект проверяет, насколько SQL, выбранный в SQLite-oriented pipeline, переносится на DuckDB, PostgreSQL и MySQL.

### DuckDB

DuckDB запускается in-process:

```bash
python src/a2v/09_multibackend_duckdb.py
python src/a2v/10_duckdb_dialect_repair.py
```

Если LLM repair был прерван, можно безопасно продолжить:

```bash
python src/a2v/10_duckdb_dialect_repair.py --resume
```

### PostgreSQL и MySQL через Docker

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

После запуска контейнеров:

```bash
python src/a2v/09b_multibackend_postgres.py
python src/a2v/10b_postgres_dialect_repair.py

python src/a2v/09c_multibackend_mysql.py
python src/a2v/10c_mysql_dialect_repair.py
```

Продолжить прерванные LLM repair запуски:

```bash
python src/a2v/10b_postgres_dialect_repair.py --resume
python src/a2v/10c_mysql_dialect_repair.py --resume
```

Построить multi-backend select output и итоговую таблицу:

```bash
python src/a2v/12b_multibackend_select.py
python src/a2v/12_multibackend_final_summary.py
```

Итоговая таблица показывает поэтапное улучшение:

```text
Before Same Result       # исходный выбранный SQL
After First Repair Same  # первый LLM repair кандидат, до candidate selection
After Select Same        # лучший кандидат после validate + select
```

## Интерактивный прототип

Репозиторий содержит локальный A²V-SQL prototype с FastAPI backend и React frontend. Интерфейс демонстрирует schema grounding, candidate SQL traces, execution validation, repair evidence, EASE final selection, а также перенос идеи A²V на Python и Java.

Запуск backend и frontend одной командой:

```bash
./run_demo.sh
```

Адреса:

```text
Frontend: http://127.0.0.1:5173
Backend : http://127.0.0.1:8000
```

Ручной запуск:

```bash
python -m uvicorn --app-dir demo_backend main:app --reload --host 127.0.0.1 --port 8000

cd demo_frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

## Основные результаты диссертации

В работе приводятся следующие основные результаты на Spider dev (`n = 1034`):

| Этап / метод | Execution Accuracy |
|---|---:|
| Prompt-only | 0.114 |
| Embedding Schema-RAG | 0.734 |
| Error-feedback repair | 0.779 |
| EASE-Selector | 0.834 |

Главный вывод состоит в том, что надёжность LLM-based Text-to-SQL повышается не только за счёт более сильной генерации, но и за счёт полного системного процесса, объединяющего validation, repair и selection.

## Воспроизводимость

- Большие датасеты, model checkpoints, virtual environments и experiment outputs намеренно не включаются в Git.
- `runs/` является локальной директорией для кэшей и результатов и должна пересоздаваться локально.
- PostgreSQL и MySQL эксперименты требуют Docker containers или эквивалентных локальных database services.
- Скрипты с online LLM вызовами требуют локальных API keys в `.env` или переменных окружения.
- Точные численные результаты могут немного отличаться при повторном запуске online LLM из-за изменений модели или decoding behavior.

## Безопасность

Это исследовательский прототип, а не production SQL service. Не следует открывать его для недоверенных пользователей или подключать к production databases. Прототип выполняет сгенерированные SQL во время validation, поэтому его нужно использовать только с локальными benchmark databases или одноразовыми test databases.

## Лицензия

Лицензия пока явно не указана. Если репозиторий становится публичным или используется другими людьми, следует добавить отдельный `LICENSE` файл.
