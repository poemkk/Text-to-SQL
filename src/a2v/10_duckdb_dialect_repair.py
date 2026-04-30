import argparse
import json
import os
import re
import sqlite3
import time
from pathlib import Path

import duckdb
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
    return "\n\n".join(doc["text"] for doc in docs[:max_docs])


def sqlite_type_to_duckdb(sqlite_type):
    t = str(sqlite_type).lower()

    if "int" in t or "number" in t or "numeric" in t:
        return "DOUBLE"

    if "real" in t or "float" in t or "double" in t or "decimal" in t:
        return "DOUBLE"

    if "char" in t or "text" in t or "varchar" in t:
        return "VARCHAR"

    return "VARCHAR"


def safe_sqlite_connect(sqlite_path):
    conn = sqlite3.connect(str(sqlite_path))
    conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    return conn


def sqlite_tables(sqlite_path):
    conn = safe_sqlite_connect(sqlite_path)
    cur = conn.cursor()
    tables = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table';"
    ).fetchall()
    conn.close()

    return [t[0] for t in tables if not str(t[0]).startswith("sqlite_")]


def clean_value_for_duckdb(value, duckdb_type):
    if value is None:
        return None

    if duckdb_type == "DOUBLE":
        if value == "":
            return None

        try:
            return float(value)
        except Exception:
            return None

    return str(value)


def clean_rows_for_duckdb(rows, col_types):
    cleaned = []

    for row in rows:
        new_row = []
        for value, dtype in zip(row, col_types):
            new_row.append(clean_value_for_duckdb(value, dtype))
        cleaned.append(new_row)

    return cleaned


def load_sqlite_to_duckdb(sqlite_path, verbose=False):
    con = duckdb.connect(database=":memory:")
    tables = sqlite_tables(sqlite_path)

    if verbose:
        print(f"[LOAD] {sqlite_path.name}: {len(tables)} tables")

    for table in tables:
        sqlite_conn = safe_sqlite_connect(sqlite_path)

        try:
            rows = sqlite_conn.execute(f'SELECT * FROM "{table}"').fetchall()
            cols_info = sqlite_conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        finally:
            sqlite_conn.close()

        col_names = [c[1] for c in cols_info]
        col_types = [sqlite_type_to_duckdb(c[2]) for c in cols_info]

        if not col_names:
            continue

        col_defs = ", ".join(
            [f'"{name}" {dtype}' for name, dtype in zip(col_names, col_types)]
        )

        try:
            con.execute(f'CREATE TABLE "{table}" ({col_defs});')
        except Exception as e:
            print(f"[WARN] failed to create DuckDB table: {sqlite_path.name}::{table} | {e}")
            continue

        if rows:
            placeholders = ", ".join(["?"] * len(col_names))
            cleaned_rows = clean_rows_for_duckdb(rows, col_types)

            try:
                con.executemany(
                    f'INSERT INTO "{table}" VALUES ({placeholders});',
                    cleaned_rows,
                )
            except Exception as e:
                print(f"[WARN] failed to insert table into DuckDB: {sqlite_path.name}::{table} | {e}")

    return con


def execute_duckdb(con, sql):
    start = time.time()

    if not sql or not isinstance(sql, str):
        return {
            "exec_ok": False,
            "exec_error": "empty_or_invalid_sql",
            "result": None,
            "latency_ms": 0.0,
        }

    try:
        rows = con.execute(sql).fetchall()
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


def call_dialect_repair(client, model, db_id, schema_context, sqlite_sql, duckdb_error):
    prompt = f"""
You are a SQL dialect repair expert.

The following SQL query is valid or executable in SQLite, but failed in DuckDB.
Your task is to rewrite it into DuckDB-compatible SQL while preserving the same meaning.

Database id:
{db_id}

Schema context:
{schema_context}

Original SQLite SQL:
{sqlite_sql}

DuckDB execution error:
{duckdb_error}

Repair rules:
- Return ONE DuckDB-compatible SQL query.
- Preserve the original query meaning as much as possible.
- Use ONLY tables and columns from the schema context.
- If DuckDB complains about GROUP BY, add the required non-aggregated selected columns to GROUP BY or use an equivalent DuckDB-compatible form.
- If DuckDB complains about type comparison, add explicit CAST only where necessary.
- If DuckDB complains about AVG/SUM over VARCHAR, cast the column to DOUBLE only where necessary.
- Do not change the task meaning.
- Do not explain.

Output format:
Return ONLY a valid JSON object with exactly one key: "sql".

Example:
{{"sql": "SELECT COUNT(*) FROM singer;"}}
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
        default="runs/outputs/a2v/multibackend_duckdb_spider100_typed.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/multibackend_duckdb_spider100_dialect_repaired.jsonl",
    )
    parser.add_argument(
        "--db_root",
        type=str,
        default="data/spider/database",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="deepseek-chat",
    )
    parser.add_argument(
        "--max_repairs",
        type=int,
        default=20,
    )
    parser.add_argument(
        "--progress_every",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--verbose_load",
        action="store_true",
        help="Print DuckDB loading details.",
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

    duckdb_cache = {}

    total = 0
    before_ok = 0
    before_same = 0

    repair_attempted = 0
    repair_ok = 0
    repair_same = 0

    start_all = time.time()

    with out_path.open("w", encoding="utf-8") as out:
        for row_idx, item in enumerate(rows, start=1):
            total += 1

            if item.get("duckdb_exec_ok"):
                before_ok += 1

            if item.get("crossdb_same_result"):
                before_same += 1

            item["dialect_repair_attempted"] = False
            item["dialect_repair_sql"] = None
            item["dialect_repair_raw_response"] = None
            item["dialect_repair_exec_ok"] = False
            item["dialect_repair_exec_error"] = None
            item["dialect_repair_result"] = None
            item["dialect_repair_same_result"] = False

            # 只修 DuckDB 失败的 SQL
            if item.get("duckdb_exec_ok"):
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
                out.flush()
                continue

            if repair_attempted >= args.max_repairs:
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
                out.flush()
                continue

            db_id = item["db_id"]
            sqlite_sql = item.get("selected_sql")
            duckdb_error = item.get("duckdb_exec_error")
            sqlite_result = item.get("selected", {}).get("result")
            sqlite_path = Path(args.db_root) / db_id / f"{db_id}.sqlite"

            if db_id not in duckdb_cache:
                print(f"[LOAD] loading db {db_id} ({sqlite_path})")
                duckdb_cache[db_id] = load_sqlite_to_duckdb(
                    sqlite_path,
                    verbose=args.verbose_load,
                )

            con = duckdb_cache[db_id]
            schema_context = build_schema_context(schema_docs_by_db, db_id)

            repaired_sql, raw_response = call_dialect_repair(
                client=client,
                model=args.model,
                db_id=db_id,
                schema_context=schema_context,
                sqlite_sql=sqlite_sql,
                duckdb_error=duckdb_error,
            )

            repair_attempted += 1

            validation = execute_duckdb(con, repaired_sql)

            same_result = (
                validation["exec_ok"]
                and normalize_result(sqlite_result) == normalize_result(validation["result"])
            )

            item["dialect_repair_attempted"] = True
            item["dialect_repair_sql"] = repaired_sql
            item["dialect_repair_raw_response"] = raw_response
            item["dialect_repair_exec_ok"] = validation["exec_ok"]
            item["dialect_repair_exec_error"] = validation["exec_error"]
            item["dialect_repair_result"] = validation["result"]
            item["dialect_repair_latency_ms"] = validation["latency_ms"]
            item["dialect_repair_same_result"] = same_result

            if validation["exec_ok"]:
                repair_ok += 1

            if same_result:
                repair_same += 1

            out.write(json.dumps(item, ensure_ascii=False) + "\n")
            out.flush()

            if (
                repair_attempted == 1
                or repair_attempted % args.progress_every == 0
                or repair_attempted == args.max_repairs
            ):
                elapsed = time.time() - start_all
                print(
                    f"[PROGRESS] dialect repairs={repair_attempted}/{args.max_repairs} "
                    f"| row={row_idx}/{len(rows)} "
                    f"| idx={item.get('idx')} "
                    f"| db_id={db_id} "
                    f"| repair_ok={repair_ok}/{repair_attempted} "
                    f"| repair_same={repair_same}/{repair_attempted} "
                    f"| elapsed={elapsed:.1f}s"
                )

    after_ok = before_ok + repair_ok
    after_same = before_same + repair_same

    print("=== DuckDB Dialect Repair Summary ===")
    print(f"total examples: {total}")
    print(f"before DuckDB executable: {before_ok}/{total} = {before_ok / total:.3f}")
    print(f"before same result: {before_same}/{total} = {before_same / total:.3f}")
    print(f"repair attempted: {repair_attempted}")
    if repair_attempted > 0:
        print(f"dialect repair executable: {repair_ok}/{repair_attempted} = {repair_ok / repair_attempted:.3f}")
        print(f"dialect repair same result: {repair_same}/{repair_attempted} = {repair_same / repair_attempted:.3f}")
    print(f"after DuckDB executable: {after_ok}/{total} = {after_ok / total:.3f}")
    print(f"after same result: {after_same}/{total} = {after_same / total:.3f}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()