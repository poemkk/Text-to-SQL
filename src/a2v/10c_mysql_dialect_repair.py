import argparse
import json
import os
import re
import sqlite3
import time
from pathlib import Path

import pymysql
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


def sqlite_type_to_mysql(sqlite_type):
    t = str(sqlite_type).lower()

    if "int" in t or "number" in t or "numeric" in t:
        return "DOUBLE"

    if "real" in t or "float" in t or "double" in t or "decimal" in t:
        return "DOUBLE"

    if "char" in t or "text" in t or "varchar" in t:
        return "TEXT"

    return "TEXT"


def clean_value_for_mysql(value, mysql_type):
    if value is None:
        return None

    if mysql_type == "DOUBLE":
        if value == "":
            return None
        try:
            return float(value)
        except Exception:
            return None

    return str(value)


def clean_rows_for_mysql(rows, col_types):
    cleaned = []
    for row in rows:
        cleaned.append([
            clean_value_for_mysql(value, dtype)
            for value, dtype in zip(row, col_types)
        ])
    return cleaned


def quote_ident(name):
    escaped = str(name).replace("`", "``")
    return f"`{escaped}`"


def make_mysql_db_name(db_id):
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", db_id.lower())
    return f"a2v_{safe}"


def mysql_connect(args, database=None):
    return pymysql.connect(
        host=args.mysql_host,
        port=args.mysql_port,
        user=args.mysql_user,
        password=args.mysql_password,
        database=database,
        charset="utf8mb4",
        autocommit=True,
    )


def normalize_sql_for_mysql(sql):
    """
    Light normalization before MySQL execution.
    This does not rewrite query semantics.
    It mainly adapts SQLite-style identifiers and casts to MySQL.
    """
    if not sql:
        return sql

    s = sql

    # Remove SQLite-style quoting.
    s = s.replace("[", "").replace("]", "")
    s = re.sub(r'"([A-Za-z_][A-Za-z0-9_]*)"', r"\1", s)
    s = re.sub(r'`([A-Za-z_][A-Za-z0-9_]*)`', r"\1", s)

    # Lowercase identifiers outside string literals.
    def lower_identifiers(match):
        token = match.group(0)

        keywords = {
            "SELECT", "FROM", "WHERE", "JOIN", "ON", "AS", "AND", "OR",
            "GROUP", "BY", "ORDER", "LIMIT", "DESC", "ASC", "COUNT",
            "AVG", "MIN", "MAX", "SUM", "DISTINCT", "HAVING", "IN",
            "BETWEEN", "LIKE", "NOT", "IS", "NULL", "CAST", "INTEGER",
            "SIGNED", "UNSIGNED", "CASE", "WHEN", "THEN", "ELSE", "END",
            "INNER", "LEFT", "RIGHT", "OUTER"
        }

        if token.upper() in keywords:
            return token

        return token.lower()

    parts = re.split(r"('(?:[^']|'')*')", s)

    for i in range(0, len(parts), 2):
        parts[i] = re.sub(
            r"\b[A-Za-z_][A-Za-z0-9_]*\b",
            lower_identifiers,
            parts[i],
        )

    s = "".join(parts)

    # SQLite/PostgreSQL-style cast to MySQL-compatible cast.
    s = re.sub(
        r"CAST\((.*?)\s+AS\s+INTEGER\)",
        r"CAST(\1 AS SIGNED)",
        s,
        flags=re.IGNORECASE,
    )

    s = re.sub(
        r"CAST\((.*?)\s+AS\s+INT\)",
        r"CAST(\1 AS SIGNED)",
        s,
        flags=re.IGNORECASE,
    )

    return s


def load_sqlite_to_mysql(sqlite_path, db_id, args, verbose=False):
    mysql_db = make_mysql_db_name(db_id)

    conn = mysql_connect(args)
    cur = conn.cursor()

    cur.execute(f"DROP DATABASE IF EXISTS {quote_ident(mysql_db)};")
    cur.execute(
        f"CREATE DATABASE {quote_ident(mysql_db)} "
        "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    )

    cur.close()
    conn.close()

    conn = mysql_connect(args, database=mysql_db)
    cur = conn.cursor()

    tables = sqlite_tables(sqlite_path)

    if verbose:
        print(f"[LOAD] {sqlite_path.name}: {len(tables)} tables -> database {mysql_db}")

    for table in tables:
        sqlite_conn = safe_sqlite_connect(sqlite_path)

        try:
            rows = sqlite_conn.execute(f'SELECT * FROM "{table}"').fetchall()
            cols_info = sqlite_conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        finally:
            sqlite_conn.close()

        original_col_names = [c[1] for c in cols_info]
        col_names = [normalize_ident(c) for c in original_col_names]
        col_types = [sqlite_type_to_mysql(c[2]) for c in cols_info]

        if not col_names:
            continue

        mysql_table = normalize_ident(table)

        col_defs = ", ".join(
            f"{quote_ident(name)} {dtype}"
            for name, dtype in zip(col_names, col_types)
        )

        try:
            cur.execute(
                f"CREATE TABLE {quote_ident(mysql_table)} ({col_defs});"
            )
        except Exception as e:
            print(f"[WARN] failed to create MySQL table: {db_id}::{table} | {e}")
            continue

        if rows:
            cleaned_rows = clean_rows_for_mysql(rows, col_types)
            cols = ", ".join(quote_ident(c) for c in col_names)
            placeholders = ", ".join(["%s"] * len(col_names))

            try:
                cur.executemany(
                    f"INSERT INTO {quote_ident(mysql_table)} ({cols}) VALUES ({placeholders})",
                    cleaned_rows,
                )
            except Exception as e:
                print(f"[WARN] failed to insert MySQL table: {db_id}::{table} | {e}")

    cur.close()
    conn.close()

    return mysql_db


def execute_mysql(sql, mysql_db, args):
    start = time.time()

    if not sql or not isinstance(sql, str):
        return {
            "exec_ok": False,
            "exec_error": "empty_or_invalid_sql",
            "result": None,
            "latency_ms": 0.0,
            "mysql_sql": sql,
        }

    mysql_sql = normalize_sql_for_mysql(sql)
    conn = None

    try:
        conn = mysql_connect(args, database=mysql_db)
        cur = conn.cursor()
        cur.execute(mysql_sql)
        rows = cur.fetchall()

        cur.close()
        conn.close()

        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "exec_ok": True,
            "exec_error": None,
            "result": rows,
            "latency_ms": latency_ms,
            "mysql_sql": mysql_sql,
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
            "mysql_sql": mysql_sql,
        }


def normalize_result(result):
    if result is None:
        return None

    normalized = []
    for row in result:
        normalized.append(tuple(str(x) for x in row))

    return sorted(normalized)


def call_mysql_dialect_repair(
    client,
    model,
    db_id,
    schema_context,
    original_sql,
    mysql_sql,
    mysql_error,
):
    prompt = f"""
You are a MySQL dialect repair expert.

The following SQL query was originally generated for SQLite-style execution,
but it failed in MySQL 8.0.

Your task is to rewrite it into MySQL-compatible SQL while preserving the same meaning.

Database id:
{db_id}

Schema context:
{schema_context}

Original SQL:
{original_sql}

SQL executed in MySQL after light normalization:
{mysql_sql}

MySQL execution error:
{mysql_error}

Repair rules:
- Return ONE MySQL-compatible SQL query.
- Preserve the original query meaning as much as possible.
- Use ONLY tables and columns from the schema context.
- Table and column names in MySQL are imported in lowercase.
- If MySQL complains about ONLY_FULL_GROUP_BY, add required non-aggregated selected columns to GROUP BY or use an equivalent MySQL-compatible form.
- If the query uses CAST(... AS INTEGER), replace it with CAST(... AS SIGNED).
- If MySQL complains about type comparison, add explicit CAST only where necessary.
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
        default="runs/outputs/a2v/multibackend_mysql_spider100_v2.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/multibackend_mysql_spider100_dialect_repaired.jsonl",
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

    parser.add_argument("--mysql_host", type=str, default="localhost")
    parser.add_argument("--mysql_port", type=int, default=3307)
    parser.add_argument("--mysql_user", type=str, default="root")
    parser.add_argument("--mysql_password", type=str, default="mysql")

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

    db_cache = {}

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

            if item.get("mysql_exec_ok"):
                before_ok += 1

            if item.get("mysql_crossdb_same_result"):
                before_same += 1

            item["mysql_dialect_repair_attempted"] = False
            item["mysql_dialect_repair_sql"] = None
            item["mysql_dialect_repair_raw_response"] = None
            item["mysql_dialect_repair_exec_ok"] = False
            item["mysql_dialect_repair_error"] = None
            item["mysql_dialect_repair_result"] = None
            item["mysql_dialect_repair_same_result"] = False

            if item.get("mysql_exec_ok"):
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
                out.flush()
                continue

            if repair_attempted >= args.max_repairs:
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
                out.flush()
                continue

            db_id = item["db_id"]
            original_sql = item.get("selected_sql")
            mysql_sql = item.get("mysql_sql") or normalize_sql_for_mysql(original_sql)
            mysql_error = item.get("mysql_exec_error")
            sqlite_result = item.get("selected", {}).get("result")
            sqlite_path = Path(args.db_root) / db_id / f"{db_id}.sqlite"

            if db_id not in db_cache:
                print(f"[LOAD] loading db {db_id} into MySQL")
                db_cache[db_id] = load_sqlite_to_mysql(
                    sqlite_path=sqlite_path,
                    db_id=db_id,
                    args=args,
                    verbose=args.verbose_load,
                )

            mysql_db = db_cache[db_id]
            schema_context = build_schema_context(schema_docs_by_db, db_id)

            repaired_sql, raw_response = call_mysql_dialect_repair(
                client=client,
                model=args.model,
                db_id=db_id,
                schema_context=schema_context,
                original_sql=original_sql,
                mysql_sql=mysql_sql,
                mysql_error=mysql_error,
            )

            repair_attempted += 1

            validation = execute_mysql(repaired_sql, mysql_db, args)

            same_result = (
                validation["exec_ok"]
                and normalize_result(sqlite_result) == normalize_result(validation["result"])
            )

            item["mysql_dialect_repair_attempted"] = True
            item["mysql_dialect_repair_sql"] = repaired_sql
            item["mysql_dialect_repair_raw_response"] = raw_response
            item["mysql_dialect_repair_exec_ok"] = validation["exec_ok"]
            item["mysql_dialect_repair_error"] = validation["exec_error"]
            item["mysql_dialect_repair_result"] = validation["result"]
            item["mysql_dialect_repair_latency_ms"] = validation["latency_ms"]
            item["mysql_dialect_repair_same_result"] = same_result

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
                    f"[PROGRESS] mysql dialect repairs={repair_attempted}/{args.max_repairs} "
                    f"| row={row_idx}/{len(rows)} "
                    f"| idx={item.get('idx')} "
                    f"| db_id={db_id} "
                    f"| repair_ok={repair_ok}/{repair_attempted} "
                    f"| repair_same={repair_same}/{repair_attempted} "
                    f"| elapsed={elapsed:.1f}s"
                )

    after_ok = before_ok + repair_ok
    after_same = before_same + repair_same

    print("=== MySQL Dialect Repair Summary ===")
    print(f"total examples: {total}")
    print(f"before MySQL executable: {before_ok}/{total} = {before_ok / total:.3f}")
    print(f"before same result: {before_same}/{total} = {before_same / total:.3f}")
    print(f"repair attempted: {repair_attempted}")
    if repair_attempted > 0:
        print(f"mysql dialect repair executable: {repair_ok}/{repair_attempted} = {repair_ok / repair_attempted:.3f}")
        print(f"mysql dialect repair same result: {repair_same}/{repair_attempted} = {repair_same / repair_attempted:.3f}")
    print(f"after MySQL executable: {after_ok}/{total} = {after_ok / total:.3f}")
    print(f"after same result: {after_same}/{total} = {after_same / total:.3f}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
