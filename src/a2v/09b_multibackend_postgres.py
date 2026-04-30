import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def safe_sqlite_connect(sqlite_path):
    conn = sqlite3.connect(str(sqlite_path))
    conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    return conn


def normalize_ident(name):
    """
    PostgreSQL folds unquoted identifiers to lowercase.
    To imitate SQLite's more permissive behavior, we import all table/column
    names as lowercase.
    """
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
    """
    Light normalization before PostgreSQL execution.
    We do NOT rewrite SQL semantics. We only remove some SQLite-style identifier
    quotes so PostgreSQL can fold identifiers to lowercase.
    """
    if not sql:
        return sql

    s = sql

    # Convert square brackets to double-quote removal style.
    s = s.replace("[", "").replace("]", "")

    # Remove double quotes around simple identifiers.
    # "Singer_ID" -> Singer_ID -> PostgreSQL folds to singer_id.
    s = re.sub(r'"([A-Za-z_][A-Za-z0-9_]*)"', r"\1", s)

    # SQLite sometimes uses backticks.
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
            "postgres_exec_ok": False,
            "postgres_exec_error": "empty_or_invalid_sql",
            "postgres_result": None,
            "postgres_latency_ms": 0.0,
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
            "postgres_exec_ok": True,
            "postgres_exec_error": None,
            "postgres_result": rows,
            "postgres_latency_ms": latency_ms,
            "postgres_sql": pg_sql,
        }

    except Exception as e:
        if conn is not None:
            conn.close()

        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "postgres_exec_ok": False,
            "postgres_exec_error": str(e),
            "postgres_result": None,
            "postgres_latency_ms": latency_ms,
            "postgres_sql": pg_sql,
        }


def normalize_result(result):
    if result is None:
        return None

    normalized = []
    for row in result:
        normalized.append(tuple(str(x) for x in row))

    return sorted(normalized)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--in_file",
        type=str,
        default="runs/outputs/a2v/selected_spider1034.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/multibackend_postgres_spider1034.jsonl",
    )
    parser.add_argument(
        "--db_root",
        type=str,
        default="data/spider/database",
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--progress_every", type=int, default=10)
    parser.add_argument("--verbose_load", action="store_true")

    parser.add_argument("--pg_host", type=str, default="localhost")
    parser.add_argument("--pg_port", type=int, default=5432)
    parser.add_argument("--pg_db", type=str, default="a2v")
    parser.add_argument("--pg_user", type=str, default="postgres")
    parser.add_argument("--pg_password", type=str, default="postgres")

    args = parser.parse_args()

    rows = read_jsonl(args.in_file)
    rows = rows[: args.limit]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    sqlite_ok = 0
    postgres_ok = 0
    portable_ok = 0
    same_result = 0

    schema_cache = {}
    start_all = time.time()

    with out_path.open("w", encoding="utf-8") as out:
        for idx, item in enumerate(rows, start=1):
            db_id = item["db_id"]
            sql = item.get("selected_sql")
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
            pg_result = execute_postgres(sql, schema, args)

            item.update(pg_result)

            total += 1

            if item.get("selected_exec_ok"):
                sqlite_ok += 1

            if pg_result["postgres_exec_ok"]:
                postgres_ok += 1

            if item.get("selected_exec_ok") and pg_result["postgres_exec_ok"]:
                portable_ok += 1

                if normalize_result(sqlite_result) == normalize_result(pg_result["postgres_result"]):
                    same_result += 1

            item["postgres_crossdb_portable"] = (
                item.get("selected_exec_ok") and pg_result["postgres_exec_ok"]
            )
            item["postgres_crossdb_same_result"] = (
                item["postgres_crossdb_portable"]
                and normalize_result(sqlite_result) == normalize_result(pg_result["postgres_result"])
            )

            out.write(json.dumps(item, ensure_ascii=False) + "\n")
            out.flush()

            if idx == 1 or idx % args.progress_every == 0 or idx == len(rows):
                elapsed = time.time() - start_all
                speed = idx / elapsed if elapsed > 0 else 0
                remaining = (len(rows) - idx) / speed if speed > 0 else 0

                print(
                    f"[PROGRESS] {idx}/{len(rows)} "
                    f"| db_id={db_id} "
                    f"| postgres_ok={postgres_ok}/{total}={postgres_ok / total:.3f} "
                    f"| same={same_result}/{total}={same_result / total:.3f} "
                    f"| elapsed={elapsed:.1f}s "
                    f"| eta={remaining:.1f}s"
                )

    print("=== PostgreSQL Multi-backend Summary ===")
    print(f"total examples: {total}")
    print(f"SQLite executable: {sqlite_ok}/{total} = {sqlite_ok / total:.3f}")
    print(f"PostgreSQL executable: {postgres_ok}/{total} = {postgres_ok / total:.3f}")
    print(f"Cross-DB executable portability: {portable_ok}/{total} = {portable_ok / total:.3f}")
    print(f"Cross-DB same result: {same_result}/{total} = {same_result / total:.3f}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()