import argparse
import json
import os
import re
import time
from pathlib import Path

from openai import OpenAI


DEFAULT_MODELS = [
    "gpt-5.4-mini",
    "gemini-3.1-flash-lite-preview",
    "grok-4-fast",
    "claude-haiku-4-5-20251001",
]


SCHEMA_DOCS_PATH = Path("runs/cache/spider_schema_docs.jsonl")


def read_json(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def read_existing_indices(path):
    done = set()

    path = Path(path)
    if not path.exists():
        return done

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            try:
                row = json.loads(line)
                done.add(row.get("idx"))
            except Exception:
                continue

    return done


def load_schema_docs(path=SCHEMA_DOCS_PATH):
    by_db = {}

    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            row = json.loads(line)
            db_id = row["db_id"]
            by_db.setdefault(db_id, []).append(row)

    return by_db


def build_schema_context(schema_docs_by_db, db_id, max_docs=120):
    docs = schema_docs_by_db.get(db_id, [])

    type_order = {
        "table": 1,
        "fk": 2,
        "column": 3,
    }

    docs = sorted(
        docs,
        key=lambda x: type_order.get(x.get("type"), 99)
    )

    texts = []
    for doc in docs[:max_docs]:
        text = doc.get("text", "").strip()
        if text:
            texts.append(text)

    return "\n\n".join(texts)


def clean_sql(text):
    if text is None:
        return None

    s = str(text).strip()

    # JSON output support
    try:
        data = json.loads(s)
        if isinstance(data, dict) and "sql" in data:
            s = str(data["sql"]).strip()
    except Exception:
        pass

    # Remove markdown code fences
    s = re.sub(r"^```sql\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^```\s*", "", s)
    s = re.sub(r"\s*```$", "", s)

    # Remove common prefixes
    s = re.sub(r"^\s*SQL\s*:\s*", "", s, flags=re.IGNORECASE)

    # Extract SQL starting from SELECT/WITH
    match = re.search(r"(SELECT|WITH)\s+.*", s, flags=re.IGNORECASE | re.DOTALL)
    if match:
        s = match.group(0).strip()

    # Cut after first semicolon
    if ";" in s:
        s = s.split(";")[0].strip() + ";"

    # Remove trailing explanation if no semicolon
    lines = []
    for line in s.splitlines():
        if line.strip().lower().startswith(("explanation", "note:", "this query")):
            break
        lines.append(line)

    s = "\n".join(lines).strip()

    if not s:
        return None

    return s


def build_prompt(question, db_id, schema_context):
    return f"""
You are a Text-to-SQL system.

Generate exactly one SQLite SQL query for the given natural language question.

Database id:
{db_id}

Schema context:
{schema_context}

Question:
{question}

Rules:
- Use ONLY tables and columns from the schema context.
- Generate SQLite-compatible SQL.
- Do not invent table or column names.
- Do not explain.
- Do not use markdown.
- Return only the SQL query.
""".strip()


def call_model_with_retry(
    client,
    model,
    question,
    db_id,
    schema_context,
    retries=2,
    sleep=1.0,
):
    prompt = build_prompt(
        question=question,
        db_id=db_id,
        schema_context=schema_context,
    )

    last_error = None

    for attempt in range(1, retries + 2):
        start = time.time()

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
            )

            latency_ms = round((time.time() - start) * 1000, 3)
            content = response.choices[0].message.content
            sql = clean_sql(content)

            return {
                "pred": sql,
                "raw_response": content,
                "latency_ms": latency_ms,
                "error": None,
                "attempts": attempt,
            }

        except Exception as e:
            last_error = str(e)
            latency_ms = round((time.time() - start) * 1000, 3)

            if attempt <= retries:
                time.sleep(sleep * attempt)
            else:
                return {
                    "pred": None,
                    "raw_response": None,
                    "latency_ms": latency_ms,
                    "error": last_error,
                    "attempts": attempt,
                }


def model_to_filename(model):
    safe = model.replace("/", "_").replace(":", "_").replace(" ", "_")
    return safe


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dev_file",
        type=str,
        default="data/spider/dev.json",
    )
    parser.add_argument(
        "--out_dir",
        type=str,
        default="runs/outputs/a2v/multillm",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
    )
    parser.add_argument(
        "--models",
        type=str,
        default=",".join(DEFAULT_MODELS),
        help="Comma-separated model names.",
    )
    parser.add_argument(
        "--max_schema_docs",
        type=int,
        default=120,
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
    )
    parser.add_argument(
        "--progress_every",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip examples already present in output files.",
    )
    parser.add_argument(
        "--base_url",
        type=str,
        default="https://yunwu.ai/v1",
    )

    args = parser.parse_args()

    api_key = os.environ.get("YUNWU_API_KEY")
    if not api_key:
        raise RuntimeError("YUNWU_API_KEY is not set.")

    models = [m.strip() for m in args.models.split(",") if m.strip()]

    client = OpenAI(
        api_key=api_key,
        base_url=args.base_url,
        timeout=120,
    )

    dev_rows = read_json(args.dev_file)[: args.limit]
    schema_docs_by_db = load_schema_docs()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_files = {}
    done_by_model = {}

    for model in models:
        safe_model = model_to_filename(model)
        out_path = out_dir / f"pred_spider{args.limit}_{safe_model}.jsonl"
        out_files[model] = out_path
        done_by_model[model] = read_existing_indices(out_path) if args.resume else set()

    handles = {
        model: out_files[model].open("a" if args.resume else "w", encoding="utf-8")
        for model in models
    }

    stats = {
        model: {
            "ok": 0,
            "error": 0,
            "skipped": 0,
            "latencies": [],
        }
        for model in models
    }

    start_all = time.time()

    try:
        for idx, item in enumerate(dev_rows):
            db_id = item["db_id"]
            question = item["question"]
            gold = item["query"]

            schema_context = build_schema_context(
                schema_docs_by_db=schema_docs_by_db,
                db_id=db_id,
                max_docs=args.max_schema_docs,
            )

            for model in models:
                if args.resume and idx in done_by_model[model]:
                    stats[model]["skipped"] += 1
                    continue

                result = call_model_with_retry(
                    client=client,
                    model=model,
                    question=question,
                    db_id=db_id,
                    schema_context=schema_context,
                    retries=args.retries,
                    sleep=args.sleep,
                )

                row = {
                    "idx": idx,
                    "db_id": db_id,
                    "question": question,
                    "gold": gold,
                    "pred": result["pred"],
                    "raw_response": result["raw_response"],
                    "model": model,
                    "latency_ms": result["latency_ms"],
                    "attempts": result["attempts"],
                    "error": result["error"],
                }

                handles[model].write(json.dumps(row, ensure_ascii=False) + "\n")
                handles[model].flush()

                if result["error"] is None and result["pred"]:
                    stats[model]["ok"] += 1
                    stats[model]["latencies"].append(result["latency_ms"])
                else:
                    stats[model]["error"] += 1

                time.sleep(args.sleep)

            if idx == 0 or (idx + 1) % args.progress_every == 0 or idx + 1 == args.limit:
                elapsed = time.time() - start_all
                speed = (idx + 1) / elapsed if elapsed > 0 else 0
                eta = (args.limit - idx - 1) / speed if speed > 0 else 0

                print(
                    f"[PROGRESS] examples={idx + 1}/{args.limit} "
                    f"| elapsed={elapsed:.1f}s "
                    f"| eta={eta:.1f}s"
                )

                for model in models:
                    s = stats[model]
                    avg_lat = (
                        sum(s["latencies"]) / len(s["latencies"])
                        if s["latencies"]
                        else 0.0
                    )
                    print(
                        f"  - {model}: ok={s['ok']} "
                        f"err={s['error']} skipped={s['skipped']} "
                        f"avg_latency_ms={avg_lat:.1f}"
                    )

    finally:
        for h in handles.values():
            h.close()

    print("\n[OK] Multi-LLM generation finished.")
    for model in models:
        print(f"[OK] {model}: {out_files[model]}")

    print("\n=== Final Generation Stats ===")
    for model in models:
        s = stats[model]
        avg_lat = (
            sum(s["latencies"]) / len(s["latencies"])
            if s["latencies"]
            else 0.0
        )
        print(
            f"{model}: ok={s['ok']}, error={s['error']}, "
            f"skipped={s['skipped']}, avg_latency_ms={avg_lat:.1f}"
        )


if __name__ == "__main__":
    main()