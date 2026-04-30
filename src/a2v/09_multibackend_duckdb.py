import argparse
import json
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


def execute_duckdb(con, sql):
    start = time.time()

    if not sql or not isinstance(sql, str):
        return {
            "duckdb_exec_ok": False,
            "duckdb_exec_error": "empty_or_invalid_sql",
            "duckdb_result": None,
            "duckdb_latency_ms": 0.0,
        }

    try:
        rows = con.execute(sql).fetchall()
        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "duckdb_exec_ok": True,
            "duckdb_exec_error": None,
            "duckdb_result": rows,
            "duckdb_latency_ms": latency_ms,
        }

    except Exception as e:
        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "duckdb_exec_ok": False,
            "duckdb_exec_error": str(e),
            "duckdb_result": None,
            "duckdb_latency_ms": latency_ms,
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
        default=100,
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
            duck_result = execute_duckdb(con, sql)

            item.update(duck_result)

            total += 1

            if item.get("selected_exec_ok"):
                sqlite_ok += 1

            if duck_result["duckdb_exec_ok"]:
                duckdb_ok += 1

            if item.get("selected_exec_ok") and duck_result["duckdb_exec_ok"]:
                portable_ok += 1

                if normalize_result(sqlite_result) == normalize_result(duck_result["duckdb_result"]):
                    same_result += 1

            item["crossdb_portable"] = item.get("selected_exec_ok") and duck_result["duckdb_exec_ok"]
            item["crossdb_same_result"] = (
                item["crossdb_portable"]
                and normalize_result(sqlite_result) == normalize_result(duck_result["duckdb_result"])
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
                    f"| duckdb_ok={duckdb_ok}/{total}={duckdb_ok / total:.3f} "
                    f"| same={same_result}/{total}={same_result / total:.3f} "
                    f"| elapsed={elapsed:.1f}s "
                    f"| eta={remaining:.1f}s"
                )

    print("=== DuckDB Multi-backend Summary ===")
    print(f"total examples: {total}")
    print(f"SQLite executable: {sqlite_ok}/{total} = {sqlite_ok / total:.3f}")
    print(f"DuckDB executable: {duckdb_ok}/{total} = {duckdb_ok / total:.3f}")
    print(f"Cross-DB executable portability: {portable_ok}/{total} = {portable_ok / total:.3f}")
    print(f"Cross-DB same result: {same_result}/{total} = {same_result / total:.3f}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()