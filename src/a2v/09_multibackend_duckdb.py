import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

import duckdb


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


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
    # col = '123' -> CAST(col AS DOUBLE) = 123
    sql = re.sub(
        r"(?is)\b([A-Za-z_][A-Za-z0-9_\.]*)\s*([=<>!]{1,2})\s*'(-?\d+(?:\.\d+)?)'",
        rf"CAST(\1 AS {cast_type}) \2 \3",
        sql,
    )
    # '123' = col -> 123 = CAST(col AS DOUBLE)
    sql = re.sub(
        r"(?is)'(-?\d+(?:\.\d+)?)'\s*([=<>!]{1,2})\s*([A-Za-z_][A-Za-z0-9_\.]*)\b",
        rf"\1 \2 CAST(\3 AS {cast_type})",
        sql,
    )
    return sql


def normalize_sql_for_duckdb(sql, error_hint=None):
    if not sql:
        return sql

    s = sql
    s = s.replace("[", "").replace("]", "")
    s = re.sub(r'"([A-Za-z_][A-Za-z0-9_]*)"', r"\1", s)
    s = re.sub(r'`([A-Za-z_][A-Za-z0-9_]*)`', r"\1", s)

    if error_hint:
        err = str(error_hint).lower()
        if "group by" in err:
            s = add_group_by_columns(s)
        if "avg" in err or "sum" in err or "cannot be cast" in err or "no function matches" in err:
            s = cast_avg_sum_columns(s, "DOUBLE")
        if "compare" in err or "type" in err or "varchar" in err:
            s = fix_numeric_string_comparison(s, "DOUBLE")
    return s


def execute_duckdb(con, sql, apply_normalization=False, error_hint=None):
    start = time.time()

    if not sql or not isinstance(sql, str):
        return {
            "duckdb_exec_ok": False,
            "duckdb_exec_error": "empty_or_invalid_sql",
            "duckdb_result": None,
            "duckdb_latency_ms": 0.0,
            "duckdb_sql": sql,
        }

    duckdb_sql = normalize_sql_for_duckdb(sql, error_hint=error_hint) if apply_normalization else sql

    try:
        rows = con.execute(duckdb_sql).fetchall()
        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "duckdb_exec_ok": True,
            "duckdb_exec_error": None,
            "duckdb_result": rows,
            "duckdb_latency_ms": latency_ms,
            "duckdb_sql": duckdb_sql,
        }

    except Exception as e:
        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "duckdb_exec_ok": False,
            "duckdb_exec_error": str(e),
            "duckdb_result": None,
            "duckdb_latency_ms": latency_ms,
            "duckdb_sql": duckdb_sql,
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
        default="runs/outputs/a2v/multibackend_duckdb_spider1034.jsonl",
    )
    parser.add_argument(
        "--db_root",
        type=str,
        default="data/spider/database",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1034,
    )
    parser.add_argument(
        "--progress_every",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--verbose_load",
        action="store_true",
        help="Print database loading details.",
    )
    args = parser.parse_args()

    rows = read_jsonl(args.in_file)
    rows = rows[: args.limit]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    sqlite_ok = 0
    duckdb_ok = 0
    portable_ok = 0
    same_result = 0
    duckdb_after_norm_ok = 0
    portable_after_norm_ok = 0
    same_after_norm = 0

    duckdb_cache = {}
    start_all = time.time()

    with out_path.open("w", encoding="utf-8") as out:
        for idx, item in enumerate(rows, start=1):
            db_id = item["db_id"]
            sql = item.get("selected_sql")
            sqlite_result = item.get("selected", {}).get("result")

            sqlite_path = Path(args.db_root) / db_id / f"{db_id}.sqlite"

            if db_id not in duckdb_cache:
                print(f"[LOAD] loading db {db_id} ({sqlite_path})")
                duckdb_cache[db_id] = load_sqlite_to_duckdb(
                    sqlite_path,
                    verbose=args.verbose_load,
                )

            con = duckdb_cache[db_id]
            duck_raw = execute_duckdb(con, sql, apply_normalization=False)

            item["duckdb_exec_ok"] = duck_raw["duckdb_exec_ok"]
            item["duckdb_exec_error"] = duck_raw["duckdb_exec_error"]
            item["duckdb_result"] = duck_raw["duckdb_result"]
            item["duckdb_latency_ms"] = duck_raw["duckdb_latency_ms"]
            item["duckdb_sql"] = duck_raw["duckdb_sql"]

            item["duckdb_normalized_attempted"] = False
            item["duckdb_normalized_exec_ok"] = False
            item["duckdb_normalized_exec_error"] = None
            item["duckdb_normalized_result"] = None
            item["duckdb_normalized_latency_ms"] = None
            item["duckdb_normalized_sql"] = None
            item["duckdb_normalized_strategy"] = None

            final_result = duck_raw

            if not duck_raw["duckdb_exec_ok"]:
                item["duckdb_normalized_attempted"] = True
                attempts = [
                    ("base", execute_duckdb(con, sql, apply_normalization=True)),
                    (
                        "error_aware",
                        execute_duckdb(
                            con,
                            sql,
                            apply_normalization=True,
                            error_hint=duck_raw["duckdb_exec_error"],
                        ),
                    ),
                ]

                best = attempts[-1][1]
                best_name = attempts[-1][0]

                for name, result in attempts:
                    best = result
                    best_name = name
                    if result["duckdb_exec_ok"]:
                        final_result = result
                        break

                item["duckdb_normalized_exec_ok"] = best["duckdb_exec_ok"]
                item["duckdb_normalized_exec_error"] = best["duckdb_exec_error"]
                item["duckdb_normalized_result"] = best["duckdb_result"]
                item["duckdb_normalized_latency_ms"] = best["duckdb_latency_ms"]
                item["duckdb_normalized_sql"] = best["duckdb_sql"]
                item["duckdb_normalized_strategy"] = best_name

            total += 1

            if item.get("selected_exec_ok"):
                sqlite_ok += 1

            if duck_raw["duckdb_exec_ok"]:
                duckdb_ok += 1

            if item.get("selected_exec_ok") and duck_raw["duckdb_exec_ok"]:
                portable_ok += 1

                if normalize_result(sqlite_result) == normalize_result(duck_raw["duckdb_result"]):
                    same_result += 1

            item["crossdb_portable"] = item.get("selected_exec_ok") and duck_raw["duckdb_exec_ok"]
            item["crossdb_same_result"] = (
                item["crossdb_portable"]
                and normalize_result(sqlite_result) == normalize_result(duck_raw["duckdb_result"])
            )

            item["duckdb_after_normalize_exec_ok"] = final_result["duckdb_exec_ok"]
            item["duckdb_after_normalize_result"] = final_result["duckdb_result"]
            item["duckdb_after_normalize_sql"] = final_result["duckdb_sql"]
            item["duckdb_after_normalize_error"] = final_result["duckdb_exec_error"]
            item["duckdb_after_normalize_used_normalization"] = (
                (not duck_raw["duckdb_exec_ok"]) and item["duckdb_normalized_exec_ok"]
            )

            item["crossdb_portable_after_normalize"] = (
                item.get("selected_exec_ok") and final_result["duckdb_exec_ok"]
            )
            item["crossdb_same_result_after_normalize"] = (
                item["crossdb_portable_after_normalize"]
                and normalize_result(sqlite_result) == normalize_result(final_result["duckdb_result"])
            )

            if item["duckdb_after_normalize_exec_ok"]:
                duckdb_after_norm_ok += 1

            if item["crossdb_portable_after_normalize"]:
                portable_after_norm_ok += 1

            if item["crossdb_same_result_after_normalize"]:
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
                        f"| duckdb_raw_ok={duckdb_ok}/{total}={duckdb_ok / total:.3f} "
                        f"| duckdb_after_norm_ok={duckdb_after_norm_ok}/{total}={duckdb_after_norm_ok / total:.3f} "
                        f"| same_raw={same_result}/{total}={same_result / total:.3f} "
                        f"| same_after_norm={same_after_norm}/{total}={same_after_norm / total:.3f} "
                        f"| elapsed={elapsed:.1f}s "
                        f"| eta={remaining:.1f}s"
                )

    print("=== DuckDB Multi-backend Summary ===")
    print(f"total examples: {total}")
    print(f"SQLite executable: {sqlite_ok}/{total} = {sqlite_ok / total:.3f}")
    print(f"DuckDB executable (raw SQL): {duckdb_ok}/{total} = {duckdb_ok / total:.3f}")
    print(
        f"DuckDB executable (after normalize fallback): "
        f"{duckdb_after_norm_ok}/{total} = {duckdb_after_norm_ok / total:.3f}"
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
