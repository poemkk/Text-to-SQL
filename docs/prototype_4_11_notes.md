# A²V Prototype Notes for Section 4.11

## 1. Prototype goal

The prototype demonstrates an executable-task workflow for large-language-model outputs. It is not a training system and does not rerun large experiments. It wraps existing cached experiment artifacts and deterministic demo fallbacks into a web system that can be shown during thesis defense or screenshotted for Section 4.11.

## 2. Relation to thesis title

Thesis title:

Text-to-SQL на основе крупных языковых моделей: исследование и прототипирование междоменной системы

The SQL part is the main Text-to-SQL line of the thesis. Python and Java are migration modules that show the same validation-centered workflow can be transferred from database queries to general code-generation tasks.

## 3. System architecture

The prototype has two layers:

- FastAPI backend in `demo_backend/`
- React + Vite frontend in `demo_frontend/`

The backend reads:

- Spider schema and SQLite databases from `data/spider/`
- SQL A²V cached outputs from `runs/outputs/a2v/` and `runs/outputs/pred_dev*.jsonl`
- Python APPS-500 summaries and examples from `runs/final_results/python/` and `runs/outputs/a2v_python/`
- Java MBPP-Java-386 summaries and examples from `runs/final_results/java/` and `runs/outputs/a2v_java/`

When a matching cached prediction is unavailable, the backend returns deterministic demo fallbacks. No external LLM API is called.

## 4. A²V framework steps

The displayed route follows nine steps:

1. Input Task
2. Task Routing
3. Context Building
4. Candidate Generation
5. Validation Environment
6. Error-feedback Repair
7. Re-validation / Re-testing
8. Final Selection
9. Metrics Evaluation

This supports the thesis claim that generated executable artifacts should be evaluated by execution and repaired with feedback from the validation environment.

## 5. SQL pipeline

The SQL module is the primary Text-to-SQL prototype. It supports:

- database selection from Spider
- schema visualization from `tables.json`
- question examples from fixed demo prompts and `dev.json`
- generation method selection: prompt-only, BM25 RAG, embedding RAG, LoRA, LoRA+RAG, rule selector, and A²V strong repair
- cached prediction lookup by `db_id + question`
- SQLite execution against `data/spider/database/{db_id}/{db_id}.sqlite`
- deterministic repair demo, such as replacing `singers` with `singer`

The SQL demo shows the full A²V loop: schema context, candidate SQL, execution validation, error feedback, repair, re-execution, and result table.

## 6. Python pipeline

The Python module demonstrates transferability on APPS-500. It displays model-level results:

- initial pass rate
- number of attempted repairs
- repair success rate
- final pass rate
- improvement after repair

Examples are read from `runs/outputs/a2v_python/*.jsonl` when available. The validation environment is unit tests. The frontend shows initial code, initial error, final code, and final pass status.

## 7. Java pipeline

The Java module demonstrates transferability on MBPP-Java-386. It displays the same A²V logic using a Java-specific validation environment:

- javac compilation
- test execution
- repair from compiler/test feedback
- re-testing

Examples are read from `runs/outputs/a2v_java/*.jsonl` when available.

## 8. Backend APIs

Implemented endpoints:

- `GET /api/health`
- `GET /api/framework`
- `POST /api/route_task`
- `GET /api/sql/databases`
- `GET /api/sql/examples`
- `GET /api/sql/schema`
- `POST /api/sql/generate`
- `POST /api/sql/execute`
- `POST /api/sql/repair_demo`
- `GET /api/python/summary`
- `GET /api/python/examples`
- `POST /api/python/repair_demo`
- `GET /api/java/summary`
- `GET /api/java/examples`
- `POST /api/java/repair_demo`
- `GET /api/metrics/overview`

## 9. Frontend modules

The frontend has five main tabs:

- Framework Overview
- SQL Text-to-SQL Demo
- Python APPS-500 Demo
- Java MBPP-Java-386 Demo
- Metrics Overview

Reusable components include flow visualization, task routing, validation panels, repair panels, result tables, and metrics cards.

## 10. Demo scenario

A typical SQL demo scenario:

1. Open SQL Text-to-SQL Demo.
2. Select `concert_singer`.
3. Select `embedding_rag`.
4. Choose `How many singers do we have?`.
5. Generate SQL.
6. Execute SQL and show the result `[[6]]`.
7. Click Demo Repair to show how `SELECT count(*) FROM singers;` is corrected to `SELECT count(*) FROM singer;`.

Python and Java demo scenarios show initial validation status, repair status, and final pass status for cached APPS-500 and MBPP-Java-386 examples.

## 11. How this prototype supports Section 4.11

Section 4.11 can present this prototype as the practical integration of the thesis experiments. It connects the Text-to-SQL main experiment with cross-domain executable-task validation. The prototype makes three contributions visible:

- A unified A²V architecture for SQL, Python, and Java.
- A working Text-to-SQL demo backed by Spider schema and SQLite execution.
- A compact evaluation dashboard showing that repair improves final executable correctness across domains.

The system is intentionally lightweight: it uses cached experiment outputs and deterministic repair rules so that the prototype is stable, reproducible, and suitable for academic demonstration.
