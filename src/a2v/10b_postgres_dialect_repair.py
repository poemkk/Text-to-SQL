import argparse
import json
import os
import re
import sqlite3
import time
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
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


def safe_sqlite_connect(sqlite_path):
    conn = sqlite3.connect(str(sqlite_path))
    conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    return conn


def normalize_ident(name):
    return str(name).lower()


def sqlite_tables(sqlite_path):
    conn = safe_sqlite_connect(sqlite_path)
    cur = conn.cursor()
    tables = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table';"
    ).fetchall()
    conn.close()
    return [t[0] for t in tables if not str(t[0]).startswith("sqlite_")]


def sqlite_type_to_postgres(sqlite_type):
    t = str(sqlite_type).lower()

    if "int" in t or "number" in t or "numeric" in t:
        return "DOUBLE PRECISION"

    if "real" in t or "float" in t or "double" in t or "decimal" in t:
        return "DOUBLE PRECISION"

    if "char" in t or "text" in t or "varchar" in t:
        return "TEXT"

    return "TEXT"


def clean_value_for_postgres(value, pg_type):
    if value is None:
        return None

    if pg_type == "DOUBLE PRECISION":
        if value == "":
            return None
        try:
            return float(value)
        except Exception:
            return None

    return str(value)


def clean_rows_for_postgres(rows, col_types):
    cleaned = []
    for row in rows:
        cleaned.append([
            clean_value_for_postgres(value, dtype)
            for value, dtype in zip(row, col_types)
        ])
    return cleaned


def quote_ident(name):
    escaped = str(name).replace('"', '""')
    return f'"{escaped}"'


def make_schema_name(db_id):
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", db_id.lower())
    return f"a2v_{safe}"


def postgres_connect(args):
    return psycopg2.connect(
        host=args.pg_host,
        port=args.pg_port,
        dbname=args.pg_db,
        user=args.pg_user,
        password=args.pg_password,
    )


def normalize_sql_for_postgres(sql):
    if not sql:
        return sql

    s = sql
    s = s.replace("[", "").replace("]", "")
    s = re.sub(r'"([A-Za-z_][A-Za-z0-9_]*)"', r"\1", s)
    s = re.sub(r'`([A-Za-z_][A-Za-z0-9_]*)`', r"\1", s)

    return s


def load_sqlite_to_postgres(sqlite_path, db_id, args, verbose=False):
    schema = make_schema_name(db_id)
    conn = postgres_connect(args)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(f"DROP SCHEMA IF EXISTS {quote_ident(schema)} CASCADE;")
    cur.execute(f"CREATE SCHEMA {quote_ident(schema)};")

    tables = sqlite_tables(sqlite_path)

    if verbose:
        print(f"[LOAD] {sqlite_path.name}: {len(tables)} tables -> schema {schema}")

    for table in tables:
        sqlite_conn = safe_sqlite_connect(sqlite_path)

        try:
            rows = sqlite_conn.execute(f'SELECT * FROM "{table}"').fetchall()
            cols_info = sqlite_conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        finally:
            sqlite_conn.close()

        original_col_names = [c[1] for c in cols_info]
        col_names = [normalize_ident(c) for c in original_col_names]
        col_types = [sqlite_type_to_postgres(c[2]) for c in cols_info]

        if not col_names:
            continue

        pg_table = normalize_ident(table)

        col_defs = ", ".join(
            f"{quote_ident(name)} {dtype}"
            for name, dtype in zip(col_names, col_types)
        )

        try:
            cur.execute(
                f"CREATE TABLE {quote_ident(schema)}.{quote_ident(pg_table)} ({col_defs});"
            )
        except Exception as e:
            print(f"[WARN] failed to create PostgreSQL table: {db_id}::{table} | {e}")
            conn.rollback()
            continue

        if rows:
            cleaned_rows = clean_rows_for_postgres(rows, col_types)
            cols = ", ".join(quote_ident(c) for c in col_names)

            try:
                execute_values(
                    cur,
                    f"INSERT INTO {quote_ident(schema)}.{quote_ident(pg_table)} ({cols}) VALUES %s",
                    cleaned_rows,
                    page_size=1000,
                )
            except Exception as e:
                print(f"[WARN] failed to insert PostgreSQL table: {db_id}::{table} | {e}")
                conn.rollback()

    cur.close()
    conn.close()

    return schema


def execute_postgres(sql, schema, args):
    start = time.time()

    if not sql or not isinstance(sql, str):
        return {
            "exec_ok": False,
            "exec_error": "empty_or_invalid_sql",
            "result": None,
            "latency_ms": 0.0,
            "postgres_sql": sql,
        }

    pg_sql = normalize_sql_for_postgres(sql)
    conn = None

    try:
        conn = postgres_connect(args)
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute(f"SET search_path TO {quote_ident(schema)};")
        cur.execute(pg_sql)
        rows = cur.fetchall()

        cur.close()
        conn.close()

        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "exec_ok": True,
            "exec_error": None,
            "result": rows,
            "latency_ms": latency_ms,
            "postgres_sql": pg_sql,
        }

    except Exception as e:
        if conn is not None:
            conn.close()

        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "exec_ok": False,
            "exec_error": str(e),
            "result": None,
            "latency_ms": latency_ms,
            "postgres_sql": pg_sql,
        }


def normalize_result(result):
    if result is None:
        return None

    normalized = []
    for row in result:
        normalized.append(tuple(str(x) for x in row))

    return sorted(normalized)


def call_postgres_dialect_repair(
    client,
    model,
    db_id,
    schema_context,
    sqlite_sql,
    postgres_sql,
    postgres_error,
):
    prompt = f"""
You are a PostgreSQL dialect repair expert.

The following SQL query was originally generated for SQLite-style execution,
but it failed in PostgreSQL.

Your task is to rewrite it into PostgreSQL-compatible SQL while preserving the same meaning.

Database id:
{db_id}

Schema context:
{schema_context}

Original SQL:
{sqlite_sql}

SQL executed in PostgreSQL after light normalization:
{postgres_sql}

PostgreSQL execution error:
{postgres_error}

Repair rules:
- Return ONE PostgreSQL-compatible SQL query.
- Preserve the original query meaning as much as possible.
- Use ONLY tables and columns from the schema context.
- Table and column names in PostgreSQL are imported in lowercase.
- If PostgreSQL complains about type comparison such as double precision = text or text = double precision, add explicit CAST only where necessary.
- If PostgreSQL complains about GROUP BY, add required non-aggregated selected columns to GROUP BY or use an equivalent PostgreSQL-compatible form.
- If PostgreSQL complains about AVG/SUM over text, cast the column to DOUBLE PRECISION only where necessary.
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
        default="runs/outputs/a2v/multibackend_postgres_spider100_v2.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/multibackend_postgres_spider100_dialect_repaired.jsonl",
    )
    parser.add_argument(
        "--db_root",
        type=str,
        default="data/spider/database",
    )
    parser.add_argument("--model", type=str, default="deepseek-chat")
    parser.add_argument("--max_repairs", type=int, default=30)
    parser.add_argument("--progress_every", type=int, default=5)
    parser.add_argument("--verbose_load", action="store_true")

    parser.add_argument("--pg_host", type=str, default="localhost")
    parser.add_argument("--pg_port", type=int, default=5432)
    parser.add_argument("--pg_db", type=str, default="a2v")
    parser.add_argument("--pg_user", type=str, default="postgres")
    parser.add_argument("--pg_password", type=str, default="postgres")

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

    schema_cache = {}

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

            if item.get("postgres_exec_ok"):
                before_ok += 1

            if item.get("postgres_crossdb_same_result"):
                before_same += 1

            item["postgres_dialect_repair_attempted"] = False
            item["postgres_dialect_repair_sql"] = None
            item["postgres_dialect_repair_raw_response"] = None
            item["postgres_dialect_repair_exec_ok"] = False
            item["postgres_dialect_repair_error"] = None
            item["postgres_dialect_repair_result"] = None
            item["postgres_dialect_repair_same_result"] = False

            if item.get("postgres_exec_ok"):
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
                out.flush()
                continue

            if repair_attempted >= args.max_repairs:
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
                out.flush()
                continue

            db_id = item["db_id"]
            sqlite_sql = item.get("selected_sql")
            postgres_sql = item.get("postgres_sql") or normalize_sql_for_postgres(sqlite_sql)
            postgres_error = item.get("postgres_exec_error")
            sqlite_result = item.get("selected", {}).get("result")
            sqlite_path = Path(args.db_root) / db_id / f"{db_id}.sqlite"

            if db_id not in schema_cache:
                print(f"[LOAD] loading db {db_id} into PostgreSQL lowercase schema")
                schema_cache[db_id] = load_sqlite_to_postgres(
                    sqlite_path=sqlite_path,
                    db_id=db_id,
                    args=args,
                    verbose=args.verbose_load,
                )

            schema = schema_cache[db_id]
            schema_context = build_schema_context(schema_docs_by_db, db_id)

            repaired_sql, raw_response = call_postgres_dialect_repair(
                client=client,
                model=args.model,
                db_id=db_id,
                schema_context=schema_context,
                sqlite_sql=sqlite_sql,
                postgres_sql=postgres_sql,
                postgres_error=postgres_error,
            )

            repair_attempted += 1

            validation = execute_postgres(repaired_sql, schema, args)

            same_result = (
                validation["exec_ok"]
                and normalize_result(sqlite_result) == normalize_result(validation["result"])
            )

            item["postgres_dialect_repair_attempted"] = True
            item["postgres_dialect_repair_sql"] = repaired_sql
            item["postgres_dialect_repair_raw_response"] = raw_response
            item["postgres_dialect_repair_exec_ok"] = validation["exec_ok"]
            item["postgres_dialect_repair_error"] = validation["exec_error"]
            item["postgres_dialect_repair_result"] = validation["result"]
            item["postgres_dialect_repair_latency_ms"] = validation["latency_ms"]
            item["postgres_dialect_repair_same_result"] = same_result

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
                    f"[PROGRESS] postgres dialect repairs={repair_attempted}/{args.max_repairs} "
                    f"| row={row_idx}/{len(rows)} "
                    f"| idx={item.get('idx')} "
                    f"| db_id={db_id} "
                    f"| repair_ok={repair_ok}/{repair_attempted} "
                    f"| repair_same={repair_same}/{repair_attempted} "
                    f"| elapsed={elapsed:.1f}s"
                )

    after_ok = before_ok + repair_ok
    after_same = before_same + repair_same

    print("=== PostgreSQL Dialect Repair Summary ===")
    print(f"total examples: {total}")
    print(f"before PostgreSQL executable: {before_ok}/{total} = {before_ok / total:.3f}")
    print(f"before same result: {before_same}/{total} = {before_same / total:.3f}")
    print(f"repair attempted: {repair_attempted}")
    if repair_attempted > 0:
        print(f"postgres dialect repair executable: {repair_ok}/{repair_attempted} = {repair_ok / repair_attempted:.3f}")
        print(f"postgres dialect repair same result: {repair_same}/{repair_attempted} = {repair_same / repair_attempted:.3f}")
    print(f"after PostgreSQL executable: {after_ok}/{total} = {after_ok / total:.3f}")
    print(f"after same result: {after_same}/{total} = {after_same / total:.3f}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
