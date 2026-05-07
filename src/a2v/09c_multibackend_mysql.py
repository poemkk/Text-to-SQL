import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

import pymysql


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


def split_top_level_csv(text):
    parts = []
    current = []
    depth = 0
    in_single = False
    in_double = False

    for ch in text:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "(":
                depth += 1
            elif ch == ")" and depth > 0:
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
                continue
        current.append(ch)

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def remove_select_alias(expr):
    s = expr.strip()
    s = re.sub(r"(?is)\s+AS\s+[A-Za-z_][A-Za-z0-9_]*\s*$", "", s)
    s = re.sub(r"(?is)\s+[A-Za-z_][A-Za-z0-9_]*\s*$", "", s)
    return s.strip()


def add_group_by_columns(sql):
    m_select = re.search(r"(?is)^\s*SELECT\s+(.*?)\s+FROM\s+", sql)
    m_group = re.search(
        r"(?is)\bGROUP\s+BY\s+(.*?)(\bHAVING\b|\bORDER\s+BY\b|\bLIMIT\b|$)",
        sql,
    )
    if not m_select or not m_group:
        return sql

    selected = split_top_level_csv(m_select.group(1))
    group_items = split_top_level_csv(m_group.group(1))
    existing = {x.strip().lower() for x in group_items}

    additions = []
    for item in selected:
        base = remove_select_alias(item)
        if not base or base == "*":
            continue
        if re.search(r"(?is)\b(count|sum|avg|min|max)\s*\(", base):
            continue
        if base.lower() not in existing:
            additions.append(base)
            existing.add(base.lower())

    if not additions:
        return sql

    new_group = m_group.group(1).strip() + ", " + ", ".join(additions)
    start, end = m_group.span(1)
    return sql[:start] + new_group + sql[end:]


def cast_avg_sum_columns(sql, cast_type):
    pattern = re.compile(r"(?is)\b(AVG|SUM)\s*\(\s*(?!CAST\s*\()([^)]+?)\s*\)")
    return pattern.sub(lambda m: f"{m.group(1)}(CAST({m.group(2).strip()} AS {cast_type}))", sql)


def fix_numeric_string_comparison(sql, cast_type):
    sql = re.sub(
        r"(?is)\b([A-Za-z_][A-Za-z0-9_\.]*)\s*([=<>!]{1,2})\s*'(-?\d+(?:\.\d+)?)'",
        rf"CAST(\1 AS {cast_type}) \2 \3",
        sql,
    )
    sql = re.sub(
        r"(?is)'(-?\d+(?:\.\d+)?)'\s*([=<>!]{1,2})\s*([A-Za-z_][A-Za-z0-9_\.]*)\b",
        rf"\1 \2 CAST(\3 AS {cast_type})",
        sql,
    )
    return sql


def normalize_sql_for_mysql(sql, error_hint=None):
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

    # MySQL Docker on Linux is case-sensitive for table names by default.
    # Since we import all table/column names as lowercase, normalize common
    # identifiers in SQL to lowercase outside string literals.
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

    # Lowercase identifiers only outside single quotes.
    parts = re.split(r"('(?:[^']|'')*')", s)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\b", lower_identifiers, parts[i])
    s = "".join(parts)

    # SQLite/PostgreSQL-style cast to MySQL-compatible cast.
    s = re.sub(r"CAST\((.*?)\s+AS\s+INTEGER\)", r"CAST(\1 AS SIGNED)", s, flags=re.IGNORECASE)
    s = re.sub(r"CAST\((.*?)\s+AS\s+INT\)", r"CAST(\1 AS SIGNED)", s, flags=re.IGNORECASE)

    if error_hint:
        err = str(error_hint).lower()
        if "only_full_group_by" in err or "group by" in err:
            s = add_group_by_columns(s)
        if "incorrect" in err or "truncated" in err or "type" in err:
            s = fix_numeric_string_comparison(s, "SIGNED")
        if "function avg" in err or "function sum" in err:
            s = cast_avg_sum_columns(s, "DOUBLE")

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


def execute_mysql(sql, mysql_db, args, apply_normalization=False, error_hint=None):
    start = time.time()

    if not sql or not isinstance(sql, str):
        return {
            "mysql_exec_ok": False,
            "mysql_exec_error": "empty_or_invalid_sql",
            "mysql_result": None,
            "mysql_latency_ms": 0.0,
            "mysql_sql": sql,
        }

    mysql_sql = normalize_sql_for_mysql(sql, error_hint=error_hint) if apply_normalization else sql
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
            "mysql_exec_ok": True,
            "mysql_exec_error": None,
            "mysql_result": rows,
            "mysql_latency_ms": latency_ms,
            "mysql_sql": mysql_sql,
        }

    except Exception as e:
        if conn is not None:
            conn.close()

        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "mysql_exec_ok": False,
            "mysql_exec_error": str(e),
            "mysql_result": None,
            "mysql_latency_ms": latency_ms,
            "mysql_sql": mysql_sql,
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
        default="runs/outputs/a2v/multibackend_mysql_spider1034.jsonl",
    )
    parser.add_argument(
        "--db_root",
        type=str,
        default="data/spider/database",
    )
    parser.add_argument("--limit", type=int, default=1034)
    parser.add_argument("--progress_every", type=int, default=10)
    parser.add_argument("--verbose_load", action="store_true")

    parser.add_argument("--mysql_host", type=str, default="localhost")
    parser.add_argument("--mysql_port", type=int, default=3307)
    parser.add_argument("--mysql_user", type=str, default="root")
    parser.add_argument("--mysql_password", type=str, default="mysql")

    args = parser.parse_args()

    rows = read_jsonl(args.in_file)
    rows = rows[: args.limit]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    sqlite_ok = 0
    mysql_ok = 0
    portable_ok = 0
    same_result = 0
    mysql_after_norm_ok = 0
    portable_after_norm_ok = 0
    same_after_norm = 0

    db_cache = {}
    start_all = time.time()

    with out_path.open("w", encoding="utf-8") as out:
        for idx, item in enumerate(rows, start=1):
            db_id = item["db_id"]
            sql = item.get("selected_sql")
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
            mysql_raw = execute_mysql(sql, mysql_db, args, apply_normalization=False)

            item["mysql_exec_ok"] = mysql_raw["mysql_exec_ok"]
            item["mysql_exec_error"] = mysql_raw["mysql_exec_error"]
            item["mysql_result"] = mysql_raw["mysql_result"]
            item["mysql_latency_ms"] = mysql_raw["mysql_latency_ms"]
            item["mysql_sql"] = mysql_raw["mysql_sql"]

            item["mysql_normalized_attempted"] = False
            item["mysql_normalized_exec_ok"] = False
            item["mysql_normalized_exec_error"] = None
            item["mysql_normalized_result"] = None
            item["mysql_normalized_latency_ms"] = None
            item["mysql_normalized_sql"] = None
            item["mysql_normalized_strategy"] = None

            final_result = mysql_raw

            if not mysql_raw["mysql_exec_ok"]:
                item["mysql_normalized_attempted"] = True
                attempts = [
                    ("base", execute_mysql(sql, mysql_db, args, apply_normalization=True)),
                    (
                        "error_aware",
                        execute_mysql(
                            sql,
                            mysql_db,
                            args,
                            apply_normalization=True,
                            error_hint=mysql_raw["mysql_exec_error"],
                        ),
                    ),
                ]

                best = attempts[-1][1]
                best_name = attempts[-1][0]

                for name, result in attempts:
                    best = result
                    best_name = name
                    if result["mysql_exec_ok"]:
                        final_result = result
                        break

                item["mysql_normalized_exec_ok"] = best["mysql_exec_ok"]
                item["mysql_normalized_exec_error"] = best["mysql_exec_error"]
                item["mysql_normalized_result"] = best["mysql_result"]
                item["mysql_normalized_latency_ms"] = best["mysql_latency_ms"]
                item["mysql_normalized_sql"] = best["mysql_sql"]
                item["mysql_normalized_strategy"] = best_name

            total += 1

            if item.get("selected_exec_ok"):
                sqlite_ok += 1

            if mysql_raw["mysql_exec_ok"]:
                mysql_ok += 1

            if item.get("selected_exec_ok") and mysql_raw["mysql_exec_ok"]:
                portable_ok += 1

                if normalize_result(sqlite_result) == normalize_result(mysql_raw["mysql_result"]):
                    same_result += 1

            item["mysql_crossdb_portable"] = (
                item.get("selected_exec_ok") and mysql_raw["mysql_exec_ok"]
            )
            item["mysql_crossdb_same_result"] = (
                item["mysql_crossdb_portable"]
                and normalize_result(sqlite_result) == normalize_result(mysql_raw["mysql_result"])
            )

            item["mysql_after_normalize_exec_ok"] = final_result["mysql_exec_ok"]
            item["mysql_after_normalize_result"] = final_result["mysql_result"]
            item["mysql_after_normalize_sql"] = final_result["mysql_sql"]
            item["mysql_after_normalize_error"] = final_result["mysql_exec_error"]
            item["mysql_after_normalize_used_normalization"] = (
                (not mysql_raw["mysql_exec_ok"]) and item["mysql_normalized_exec_ok"]
            )

            item["mysql_crossdb_portable_after_normalize"] = (
                item.get("selected_exec_ok") and final_result["mysql_exec_ok"]
            )
            item["mysql_crossdb_same_result_after_normalize"] = (
                item["mysql_crossdb_portable_after_normalize"]
                and normalize_result(sqlite_result) == normalize_result(final_result["mysql_result"])
            )

            if item["mysql_after_normalize_exec_ok"]:
                mysql_after_norm_ok += 1

            if item["mysql_crossdb_portable_after_normalize"]:
                portable_after_norm_ok += 1

            if item["mysql_crossdb_same_result_after_normalize"]:
                same_after_norm += 1

            out.write(json.dumps(item, ensure_ascii=False) + "\n")
            out.flush()

            if idx == 1 or idx % args.progress_every == 0 or idx == len(rows):
                elapsed = time.time() - start_all
                speed = idx / elapsed if elapsed > 0 else 0
                remaining = (len(rows) - idx) / speed if speed > 0 else 0

                print(
                    f"[PROGRESS] {idx}/{len(rows)} "
                    f"| db_id={db_id} "
                    f"| mysql_raw_ok={mysql_ok}/{total}={mysql_ok / total:.3f} "
                    f"| mysql_after_norm_ok={mysql_after_norm_ok}/{total}={mysql_after_norm_ok / total:.3f} "
                    f"| same_raw={same_result}/{total}={same_result / total:.3f} "
                    f"| same_after_norm={same_after_norm}/{total}={same_after_norm / total:.3f} "
                    f"| elapsed={elapsed:.1f}s "
                    f"| eta={remaining:.1f}s"
                )

    print("=== MySQL Multi-backend Summary ===")
    print(f"total examples: {total}")
    print(f"SQLite executable: {sqlite_ok}/{total} = {sqlite_ok / total:.3f}")
    print(f"MySQL executable (raw SQL): {mysql_ok}/{total} = {mysql_ok / total:.3f}")
    print(
        f"MySQL executable (after normalize fallback): "
        f"{mysql_after_norm_ok}/{total} = {mysql_after_norm_ok / total:.3f}"
    )
    print(f"Cross-DB portability (raw SQL): {portable_ok}/{total} = {portable_ok / total:.3f}")
    print(
        f"Cross-DB portability (after normalize fallback): "
        f"{portable_after_norm_ok}/{total} = {portable_after_norm_ok / total:.3f}"
    )
    print(f"Cross-DB same result (raw SQL): {same_result}/{total} = {same_result / total:.3f}")
    print(
        f"Cross-DB same result (after normalize fallback): "
        f"{same_after_norm}/{total} = {same_after_norm / total:.3f}"
    )
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
