import argparse
import json
import os
import re
import sqlite3
import time
from difflib import get_close_matches
from pathlib import Path

from openai import OpenAI


SCHEMA_DOCS_PATH = Path("runs/cache/spider_schema_docs.jsonl")


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_schema_docs(path=SCHEMA_DOCS_PATH):
    by_db = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            by_db.setdefault(row["db_id"], []).append(row)
    return by_db


def build_schema_context(schema_docs_by_db, db_id, max_docs=120):
    docs = schema_docs_by_db.get(db_id, [])

    type_order = {
        "table": 1,
        "fk": 2,
        "column": 3,
    }

    docs = sorted(docs, key=lambda x: type_order.get(x.get("type"), 99))
    texts = [doc["text"] for doc in docs[:max_docs]]
    return "\n\n".join(texts)


def execute_sql(db_path, sql):
    start = time.time()

    if not sql or not isinstance(sql, str):
        return {
            "exec_ok": False,
            "exec_error": "empty_or_invalid_sql",
            "result": None,
            "latency_ms": 0.0,
        }

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()

        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "exec_ok": True,
            "exec_error": None,
            "result": rows,
            "latency_ms": latency_ms,
        }

    except Exception as e:
        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "exec_ok": False,
            "exec_error": str(e),
            "result": None,
            "latency_ms": latency_ms,
        }


def normalize_result(result):
    if result is None:
        return None

    normalized = []
    for row in result:
        normalized.append(tuple(str(x) for x in row))

    return sorted(normalized)


def extract_string_literals(sql):
    if not sql:
        return []

    literals = re.findall(r"'([^']+)'", sql)
    literals += re.findall(r'"([^"]+)"', sql)

    cleaned = []
    for x in literals:
        x = x.strip()
        if x and x not in cleaned:
            cleaned.append(x)

    return cleaned


def get_text_columns(db_path):
    columns = []

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        tables = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()

        for (table_name,) in tables:
            if table_name.startswith("sqlite_"):
                continue

            info = cur.execute(f'PRAGMA table_info("{table_name}")').fetchall()

            for col in info:
                col_name = col[1]
                col_type = str(col[2]).lower()

                if "char" in col_type or "text" in col_type or col_type == "":
                    columns.append((table_name, col_name))

        conn.close()

    except Exception:
        return []

    return columns


def build_value_hints(db_path, sql, max_values_per_literal=8):
    literals = extract_string_literals(sql)

    if not literals:
        return "No string literals found in the SQL."

    text_columns = get_text_columns(db_path)

    if not text_columns:
        return "No text columns found."

    hints = []

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        for literal in literals:
            literal_hints = []
            literal_lower = literal.lower()

            for table, column in text_columns:
                try:
                    query = f'SELECT DISTINCT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL LIMIT 200'
                    values = cur.execute(query).fetchall()
                except Exception:
                    continue

                values = [str(v[0]) for v in values if v and v[0] is not None]

                exact_or_contains = [
                    v for v in values
                    if literal_lower in v.lower() or v.lower() in literal_lower
                ]

                close = get_close_matches(literal, values, n=5, cutoff=0.45)

                candidates = []
                for v in exact_or_contains + close:
                    if v not in candidates:
                        candidates.append(v)

                if candidates:
                    literal_hints.append(
                        f"- SQL literal '{literal}' may correspond to {table}.{column}: {candidates[:max_values_per_literal]}"
                    )

            if literal_hints:
                hints.extend(literal_hints)
            else:
                hints.append(f"- No close database value found for SQL literal '{literal}'.")

        conn.close()

    except Exception as e:
        return f"Failed to build value hints: {e}"

    return "\n".join(hints[:40])


def should_repair_candidate(cand, repair_mode):
    exec_ok = cand.get("exec_ok", False)
    result = cand.get("result")
    sql = cand.get("sql") or ""

    if repair_mode == "failed_only":
        return not exec_ok

    if repair_mode == "strong":
        if not exec_ok:
            return True

        if exec_ok and result == []:
            return True

        if exec_ok and extract_string_literals(sql):
            return True

        return False

    raise ValueError(f"Unknown repair_mode: {repair_mode}")


def build_repair_signal(cand):
    if not cand.get("exec_ok"):
        return f"Execution failed with error:\n{cand.get('exec_error')}"

    result = cand.get("result")

    if result == []:
        return "The SQL query was executable, but it returned an empty result. This may indicate wrong filtering value, wrong condition, or wrong join path."

    if extract_string_literals(cand.get("sql") or ""):
        return "The SQL query was executable, but it contains string literals. Check whether the string values match the actual database values."

    return "The SQL query may contain semantic issues. Please check schema usage, join path, filtering values, aggregation, sorting, and nesting."


def call_deepseek_repair(
    client,
    model,
    question,
    db_id,
    schema_context,
    wrong_sql,
    repair_signal,
    value_hints,
    previous_error=None,
):
    previous_part = ""
    if previous_error:
        previous_part = f"""
Previous repair attempt still failed or was suspicious:
{previous_error}
""".strip()

    prompt = f"""
You are a senior Text-to-SQL repair expert.

Your task is to repair a SQL query for a SQLite database.

Database id:
{db_id}

Schema context:
{schema_context}

Question:
{question}

Wrong or suspicious SQL:
{wrong_sql}

Validation signal:
{repair_signal}

Database value hints:
{value_hints}

{previous_part}

Repair requirements:
- Generate ONE SQLite SQL query.
- Use ONLY tables and columns from the schema context.
- JOIN tables only when the join path is supported by the schema.
- If the original SQL uses a string value, verify it against the database value hints.
- If the error is about a missing table or missing column, replace it with the closest real schema name.
- If the query returned empty result, check whether the filtering value is expressed incorrectly.
- Do not use the gold SQL.
- Do not explain.

Output format:
Return ONLY a valid JSON object with exactly one key: "sql".

Example:
{{"sql": "SELECT count(*) FROM singer;"}}
""".strip()

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    content = response.choices[0].message.content.strip()

    try:
        data = json.loads(content)
        return data.get("sql"), content
    except Exception:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                return data.get("sql"), content
            except Exception:
                pass

        return None, content


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--in_file",
        type=str,
        default="runs/outputs/a2v/scored_spider100.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/repaired_strong_spider100.jsonl",
    )
    parser.add_argument(
        "--db_root",
        type=str,
        default="data/spider/database",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="deepseek-reasoner",
    )
    parser.add_argument(
        "--max_repairs",
        type=int,
        default=999,
    )
    parser.add_argument(
        "--max_rounds",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--repair_mode",
        type=str,
        default="strong",
        choices=["failed_only", "strong"],
    )
    parser.add_argument(
        "--progress_every",
        type=int,
        default=10,
    )
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set.")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )

    rows = read_jsonl(args.in_file)
    schema_docs_by_db = load_schema_docs()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    repaired_count = 0
    repair_exec_ok_count = 0
    repair_correct_count = 0
    repair_attempted_candidates = 0

    with out_path.open("w", encoding="utf-8") as out:
        for item in rows:
            db_id = item["db_id"]
            question = item["question"]
            db_path = Path(args.db_root) / db_id / f"{db_id}.sqlite"
            schema_context = build_schema_context(schema_docs_by_db, db_id)
            norm_gold = normalize_result(item.get("gold_result"))

            for cand in item["candidates"]:
                cand["strong_repair_attempted"] = False
                cand["strong_repair_rounds"] = []
                cand["strong_repair_final_sql"] = None
                cand["strong_repair_exec_ok"] = False
                cand["strong_repair_exec_error"] = None
                cand["strong_repair_result"] = None
                cand["strong_repair_exec_correct"] = False

                if repaired_count >= args.max_repairs:
                    continue

                if not should_repair_candidate(cand, args.repair_mode):
                    continue

                repair_attempted_candidates += 1
                cand["strong_repair_attempted"] = True

                current_sql = cand.get("sql")
                previous_error = None
                best_validation = None
                best_sql = None

                for round_id in range(1, args.max_rounds + 1):
                    if repaired_count >= args.max_repairs:
                        break

                    repair_signal = build_repair_signal(cand)
                    if previous_error:
                        repair_signal += f"\nPrevious round problem: {previous_error}"

                    value_hints = build_value_hints(db_path, current_sql)

                    repaired_sql, raw_response = call_deepseek_repair(
                        client=client,
                        model=args.model,
                        question=question,
                        db_id=db_id,
                        schema_context=schema_context,
                        wrong_sql=current_sql,
                        repair_signal=repair_signal,
                        value_hints=value_hints,
                        previous_error=previous_error,
                    )

                    repaired_count += 1

                    if repaired_count % args.progress_every == 0 or repaired_count == 1:
                        print(
                            f"[PROGRESS] repair_calls={repaired_count}/{args.max_repairs} "
                            f"| idx={item.get('idx')} | db_id={db_id} "
                            f"| source={cand.get('source')} | round={round_id}"
                        )

                    validation = execute_sql(db_path, repaired_sql)

                    exec_correct = False
                    if validation["exec_ok"]:
                        norm_repair = normalize_result(validation["result"])
                        exec_correct = norm_repair == norm_gold

                    round_record = {
                        "round": round_id,
                        "input_sql": current_sql,
                        "repair_sql": repaired_sql,
                        "raw_response": raw_response,
                        "exec_ok": validation["exec_ok"],
                        "exec_error": validation["exec_error"],
                        "result": validation["result"],
                        "latency_ms": validation["latency_ms"],
                        "exec_correct": exec_correct,
                        "value_hints": value_hints,
                    }

                    cand["strong_repair_rounds"].append(round_record)

                    best_sql = repaired_sql
                    best_validation = validation

                    if validation["exec_ok"]:
                        if exec_correct:
                            break

                        if validation["result"] not in (None, []):
                            break

                    previous_error = validation["exec_error"] or "Repair did not produce a correct or useful result."
                    current_sql = repaired_sql

                if best_validation is not None:
                    cand["strong_repair_final_sql"] = best_sql
                    cand["strong_repair_exec_ok"] = best_validation["exec_ok"]
                    cand["strong_repair_exec_error"] = best_validation["exec_error"]
                    cand["strong_repair_result"] = best_validation["result"]

                    if best_validation["exec_ok"]:
                        repair_exec_ok_count += 1

                        norm_final = normalize_result(best_validation["result"])
                        if norm_final == norm_gold:
                            cand["strong_repair_exec_correct"] = True
                            repair_correct_count += 1

            out.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"[OK] repair API calls: {repaired_count}")
    print(f"[OK] candidates attempted: {repair_attempted_candidates}")
    print(f"[OK] repair executable candidates: {repair_exec_ok_count}/{repair_attempted_candidates}")
    print(f"[OK] repair correct candidates: {repair_correct_count}/{repair_attempted_candidates}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
