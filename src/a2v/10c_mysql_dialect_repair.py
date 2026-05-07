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


def prepare_resume_output(path):
    path = Path(path)
    completed = set()
    if not path.exists():
        return completed

    valid_lines = []
    invalid_lines = 0
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                invalid_lines += 1
                print(f"[WARN] dropping invalid resume line {line_no} from {path}")
                continue
            valid_lines.append(json.dumps(item, ensure_ascii=False, default=str) + "\n")
            if item.get("idx") is not None:
                completed.add(item["idx"])

    if invalid_lines:
        backup_path = path.with_name(f"{path.name}.corrupt_backup_{int(time.time())}")
        path.replace(backup_path)
        with path.open("w", encoding="utf-8") as out:
            out.writelines(valid_lines)
        print(f"[RESUME] backed up corrupt output to {backup_path}")

    return completed


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


def execute_mysql(sql, mysql_db, args, apply_normalization=False):
    start = time.time()

    if not sql or not isinstance(sql, str):
        return {
            "exec_ok": False,
            "exec_error": "empty_or_invalid_sql",
            "result": None,
            "latency_ms": 0.0,
            "mysql_sql": sql,
        }

    mysql_sql = normalize_sql_for_mysql(sql) if apply_normalization else sql
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


def build_result_mismatch_hint(target_result, candidate_result):
    target_norm = normalize_result(target_result) or []
    cand_norm = normalize_result(candidate_result) or []
    return (
        f"Target SQLite result rows={len(target_norm)}, sample={target_norm[:3]}. "
        f"Current candidate result rows={len(cand_norm)}, sample={cand_norm[:3]}."
    )


def extract_sql_candidates(content):
    def from_obj(obj):
        if isinstance(obj, dict):
            sqls = []
            if isinstance(obj.get("sql"), str) and obj.get("sql").strip():
                sqls.append(obj["sql"].strip())
            if isinstance(obj.get("sqls"), list):
                for x in obj["sqls"]:
                    if isinstance(x, str) and x.strip():
                        sqls.append(x.strip())
            return sqls
        return []

    sqls = []
    try:
        sqls.extend(from_obj(json.loads(content)))
    except Exception:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if match:
            try:
                sqls.extend(from_obj(json.loads(match.group(0))))
            except Exception:
                pass

    dedup = []
    seen = set()
    for s in sqls:
        if s not in seen:
            seen.add(s)
            dedup.append(s)
    return dedup


def call_mysql_dialect_repair(
    client,
    model,
    db_id,
    schema_context,
    original_sql,
    mysql_sql,
    mysql_error,
    n_candidates=3,
    mismatch_hint=None,
):
    mismatch_block = f"\nCurrent mismatch hint:\n{mismatch_hint}\n" if mismatch_hint else ""
    prompt = f"""
You are a MySQL dialect repair expert.

The following SQL query was originally generated for SQLite-style execution,
but it failed in MySQL 8.0.

Your task is to produce multiple MySQL-compatible SQL candidates while preserving the same meaning.

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
{mismatch_block}

Repair rules:
- Return {n_candidates} diverse MySQL-compatible SQL candidates when possible.
- Preserve the original query meaning as much as possible.
- Use ONLY tables and columns from the schema context.
- Table and column names in MySQL are imported in lowercase.
- If MySQL complains about ONLY_FULL_GROUP_BY, add required non-aggregated selected columns to GROUP BY or use an equivalent MySQL-compatible form.
- If the query uses CAST(... AS INTEGER), replace it with CAST(... AS SIGNED).
- If MySQL complains about type comparison, add explicit CAST only where necessary.
- Do not change the task meaning.
- Do not explain.

Output format:
Return ONLY a valid JSON object with exactly one key: "sqls".

Example:
{{"sqls": ["SELECT COUNT(*) FROM singer;", "SELECT CAST(COUNT(*) AS SIGNED) FROM singer;"]}}
""".strip()

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    content = response.choices[0].message.content.strip()

    return extract_sql_candidates(content), content


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--in_file",
        type=str,
        default="runs/outputs/a2v/multibackend_mysql_spider1034.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/multibackend_mysql_spider1034_dialect_repaired.jsonl",
    )
    parser.add_argument(
        "--db_root",
        type=str,
        default="data/spider/database",
    )
    parser.add_argument("--model", type=str, default="deepseek-chat")
    parser.add_argument("--max_repairs", type=int, default=200)
    parser.add_argument("--progress_every", type=int, default=5)
    parser.add_argument("--verbose_load", action="store_true")
    parser.add_argument("--repair_candidates", type=int, default=3)
    parser.add_argument("--max_repair_rounds", type=int, default=2)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Append to existing output and skip rows whose idx is already present.",
    )

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
    completed_indices = prepare_resume_output(out_path) if args.resume else set()
    if args.resume:
        print(f"[RESUME] found {len(completed_indices)} completed rows in {out_path}")

    db_cache = {}

    total = 0
    before_ok = 0
    before_same = 0

    repair_triggered = 0
    fallback_attempted = 0
    mismatch_triggered = 0
    normalize_fixed = 0
    normalize_same = 0
    llm_attempted = 0
    llm_api_calls = 0
    llm_fixed = 0
    llm_same = 0
    llm_first_fixed = 0
    llm_first_same = 0

    start_all = time.time()

    write_mode = "a" if args.resume else "w"
    with out_path.open(write_mode, encoding="utf-8") as out:
        for row_idx, item in enumerate(rows, start=1):
            if args.resume and item.get("idx") in completed_indices:
                continue

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
            item["mysql_dialect_repair_stage"] = "none"
            item["mysql_llm_repair_attempted"] = False

            raw_exec_ok = bool(item.get("mysql_exec_ok"))
            raw_same = bool(item.get("mysql_crossdb_same_result"))

            if raw_exec_ok and raw_same:
                out.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
                out.flush()
                continue

            db_id = item["db_id"]
            original_sql = item.get("selected_sql")
            sqlite_result = item.get("selected", {}).get("result")

            repair_triggered += 1
            if not raw_exec_ok:
                fallback_attempted += 1
            else:
                mismatch_triggered += 1

            # Stage 1: use normalize fallback result if available in 09c output.
            norm_exec_ok = item.get("mysql_normalized_exec_ok")
            norm_result = item.get("mysql_normalized_result")
            norm_error = item.get("mysql_normalized_exec_error")
            norm_sql = item.get("mysql_normalized_sql")

            if norm_exec_ok is None:
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
                norm_validation = execute_mysql(
                    original_sql,
                    mysql_db,
                    args,
                    apply_normalization=True,
                )
                norm_exec_ok = norm_validation["exec_ok"]
                norm_result = norm_validation["result"]
                norm_error = norm_validation["exec_error"]
                norm_sql = norm_validation["mysql_sql"]
                item["mysql_normalized_attempted"] = True
                item["mysql_normalized_exec_ok"] = norm_exec_ok
                item["mysql_normalized_exec_error"] = norm_error
                item["mysql_normalized_result"] = norm_result
                item["mysql_normalized_latency_ms"] = norm_validation["latency_ms"]
                item["mysql_normalized_sql"] = norm_sql

            norm_same = (
                bool(norm_exec_ok)
                and normalize_result(sqlite_result) == normalize_result(norm_result)
            )

            if norm_same:
                same_result = (
                    normalize_result(sqlite_result) == normalize_result(norm_result)
                )
                item["mysql_dialect_repair_attempted"] = True
                item["mysql_dialect_repair_stage"] = "normalize"
                item["mysql_dialect_repair_sql"] = norm_sql
                item["mysql_dialect_repair_exec_ok"] = True
                item["mysql_dialect_repair_error"] = None
                item["mysql_dialect_repair_result"] = norm_result
                item["mysql_dialect_repair_same_result"] = same_result
                normalize_fixed += 1
                if same_result:
                    normalize_same += 1
                out.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
                out.flush()
                continue

            if llm_attempted >= args.max_repairs:
                out.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
                out.flush()
                continue

            mysql_sql = norm_sql or normalize_sql_for_mysql(original_sql)
            if raw_exec_ok and not raw_same:
                mismatch_hint = build_result_mismatch_hint(sqlite_result, item.get("mysql_result"))
                mysql_error = "result_mismatch_after_execution"
            else:
                mismatch_hint = None
                mysql_error = norm_error or item.get("mysql_exec_error")
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

            llm_attempted += 1
            target_norm = normalize_result(sqlite_result)
            rounds_used = 0
            all_raw_responses = []
            candidate_records = []
            first_candidate_record = None
            best_sql = None
            best_validation = None
            best_same_result = False
            best_score = (-1, -1, -10**9)

            for round_idx in range(1, args.max_repair_rounds + 1):
                rounds_used = round_idx
                llm_api_calls += 1
                candidates, raw_response = call_mysql_dialect_repair(
                    client=client,
                    model=args.model,
                    db_id=db_id,
                    schema_context=schema_context,
                    original_sql=original_sql,
                    mysql_sql=mysql_sql,
                    mysql_error=mysql_error,
                    n_candidates=args.repair_candidates,
                    mismatch_hint=mismatch_hint,
                )
                all_raw_responses.append(raw_response)

                if not candidates:
                    continue

                for cand_rank, cand_sql in enumerate(candidates[: args.repair_candidates], start=1):
                    validation = execute_mysql(
                        cand_sql,
                        mysql_db,
                        args,
                        apply_normalization=False,
                    )
                    same_result = (
                        validation["exec_ok"]
                        and normalize_result(validation["result"]) == target_norm
                    )
                    row_delta = -10**8
                    if validation["exec_ok"]:
                        row_delta = -abs(len(validation["result"] or []) - len(sqlite_result or []))
                    score = (
                        1 if same_result else 0,
                        1 if validation["exec_ok"] else 0,
                        row_delta,
                    )
                    candidate_record = {
                        "round": round_idx,
                        "rank": cand_rank,
                        "sql": cand_sql,
                        "exec_ok": validation["exec_ok"],
                        "exec_error": validation["exec_error"],
                        "same_result": same_result,
                        "latency_ms": validation["latency_ms"],
                        "result_rows": len(validation["result"] or []) if validation["exec_ok"] else None,
                        "score": list(score),
                    }
                    candidate_records.append(candidate_record)
                    if first_candidate_record is None:
                        first_candidate_record = candidate_record

                    if score > best_score:
                        best_score = score
                        best_sql = cand_sql
                        best_validation = validation
                        best_same_result = same_result

                    if same_result:
                        break

                if best_same_result:
                    break

                if best_validation and best_validation["exec_ok"]:
                    mismatch_hint = build_result_mismatch_hint(sqlite_result, best_validation["result"])
                elif best_validation and best_validation.get("exec_error"):
                    mysql_error = best_validation["exec_error"]

            if best_validation is None:
                best_sql = None
                best_validation = {
                    "exec_ok": False,
                    "exec_error": "llm_no_candidate",
                    "result": None,
                    "latency_ms": 0.0,
                }
                best_same_result = False

            if first_candidate_record is None:
                first_candidate_record = {
                    "round": None,
                    "rank": None,
                    "sql": None,
                    "exec_ok": False,
                    "exec_error": "llm_no_candidate",
                    "same_result": False,
                    "latency_ms": 0.0,
                    "result_rows": None,
                    "score": [0, 0, -10**8],
                }

            item["mysql_dialect_repair_attempted"] = True
            item["mysql_dialect_repair_stage"] = "llm"
            item["mysql_llm_repair_attempted"] = True
            item["mysql_dialect_repair_rounds_used"] = rounds_used
            item["mysql_dialect_repair_candidates"] = candidate_records
            item["mysql_dialect_repair_candidate_count"] = len(candidate_records)
            item["mysql_dialect_repair_first_candidate_sql"] = first_candidate_record["sql"]
            item["mysql_dialect_repair_first_candidate_exec_ok"] = first_candidate_record["exec_ok"]
            item["mysql_dialect_repair_first_candidate_error"] = first_candidate_record["exec_error"]
            item["mysql_dialect_repair_first_candidate_same_result"] = first_candidate_record["same_result"]
            item["mysql_dialect_repair_select_attempted"] = True
            item["mysql_dialect_repair_select_policy"] = "same_result_then_exec_then_row_count_delta"
            item["mysql_dialect_repair_selected_sql"] = best_sql
            item["mysql_dialect_repair_selected_score"] = list(best_score)
            item["mysql_dialect_repair_selected_exec_ok"] = best_validation["exec_ok"]
            item["mysql_dialect_repair_selected_error"] = best_validation["exec_error"]
            item["mysql_dialect_repair_selected_same_result"] = best_same_result
            item["mysql_dialect_repair_sql"] = best_sql
            item["mysql_dialect_repair_raw_response"] = "\n\n".join(all_raw_responses)
            item["mysql_dialect_repair_exec_ok"] = best_validation["exec_ok"]
            item["mysql_dialect_repair_error"] = best_validation["exec_error"]
            item["mysql_dialect_repair_result"] = best_validation["result"]
            item["mysql_dialect_repair_latency_ms"] = best_validation["latency_ms"]
            item["mysql_dialect_repair_same_result"] = best_same_result

            if first_candidate_record["exec_ok"]:
                llm_first_fixed += 1

            if first_candidate_record["same_result"]:
                llm_first_same += 1

            if best_validation["exec_ok"]:
                llm_fixed += 1

            if best_same_result:
                llm_same += 1

            out.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
            out.flush()

            if (
                repair_triggered == 1
                or repair_triggered % args.progress_every == 0
                or llm_attempted == args.max_repairs
            ):
                elapsed = time.time() - start_all
                print(
                    f"[PROGRESS] mysql triggered={repair_triggered} "
                    f"| row={row_idx}/{len(rows)} "
                    f"| idx={item.get('idx')} "
                    f"| db_id={db_id} "
                    f"| normalize_fixed={normalize_fixed}/{max(repair_triggered, 1)} "
                    f"| llm_attempted={llm_attempted}/{args.max_repairs} "
                    f"| llm_fixed={llm_fixed}/{max(llm_attempted, 1)} "
                    f"| elapsed={elapsed:.1f}s"
                )

    repair_ok = normalize_fixed + llm_fixed
    repair_same = normalize_same + llm_same
    after_ok = before_ok + repair_ok
    after_same = before_same + repair_same

    print("=== MySQL Dialect Repair Summary ===")
    print(f"total examples: {total}")
    print(f"before MySQL executable (raw SQL): {before_ok}/{total} = {before_ok / total:.3f}")
    print(f"before same result: {before_same}/{total} = {before_same / total:.3f}")
    print(f"repair triggered total: {repair_triggered}")
    print(f"fallback attempted (raw failed): {fallback_attempted}")
    print(f"mismatch triggered (exec ok but same=false): {mismatch_triggered}")
    if repair_triggered > 0:
        print(
            f"normalize fixed executable: "
            f"{normalize_fixed}/{repair_triggered} = {normalize_fixed / repair_triggered:.3f}"
        )
        print(
            f"normalize fixed same result: "
            f"{normalize_same}/{repair_triggered} = {normalize_same / repair_triggered:.3f}"
        )
    print(f"llm attempted: {llm_attempted}")
    print(f"llm api calls: {llm_api_calls}")
    if llm_attempted > 0:
        print(
            f"llm repair executable: "
            f"{llm_fixed}/{llm_attempted} = {llm_fixed / llm_attempted:.3f}"
        )
        print(
            f"llm repair same result: "
            f"{llm_same}/{llm_attempted} = {llm_same / llm_attempted:.3f}"
        )
        print(
            f"llm first-candidate executable (repair before select): "
            f"{llm_first_fixed}/{llm_attempted} = {llm_first_fixed / llm_attempted:.3f}"
        )
        print(
            f"llm first-candidate same result (repair before select): "
            f"{llm_first_same}/{llm_attempted} = {llm_first_same / llm_attempted:.3f}"
        )
        print(
            f"llm selected-candidate executable (repair + select): "
            f"{llm_fixed}/{llm_attempted} = {llm_fixed / llm_attempted:.3f}"
        )
        print(
            f"llm selected-candidate same result (repair + select): "
            f"{llm_same}/{llm_attempted} = {llm_same / llm_attempted:.3f}"
        )
    if repair_triggered > 0:
        print(
            f"total fallback executable (normalize+llm): "
            f"{repair_ok}/{repair_triggered} = {repair_ok / repair_triggered:.3f}"
        )
        print(
            f"total fallback same result (normalize+llm): "
            f"{repair_same}/{repair_triggered} = {repair_same / repair_triggered:.3f}"
        )
    print(f"after MySQL executable: {after_ok}/{total} = {after_ok / total:.3f}")
    print(f"after same result: {after_same}/{total} = {after_same / total:.3f}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
