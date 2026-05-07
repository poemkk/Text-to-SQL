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


def execute_postgres(sql, schema, args, apply_normalization=False):
    start = time.time()

    if not sql or not isinstance(sql, str):
        return {
            "exec_ok": False,
            "exec_error": "empty_or_invalid_sql",
            "result": None,
            "latency_ms": 0.0,
            "postgres_sql": sql,
        }

    pg_sql = normalize_sql_for_postgres(sql) if apply_normalization else sql
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


def call_postgres_dialect_repair(
    client,
    model,
    db_id,
    schema_context,
    sqlite_sql,
    postgres_sql,
    postgres_error,
    n_candidates=3,
    mismatch_hint=None,
):
    mismatch_block = f"\nCurrent mismatch hint:\n{mismatch_hint}\n" if mismatch_hint else ""
    prompt = f"""
You are a PostgreSQL dialect repair expert.

The following SQL query was originally generated for SQLite-style execution,
but it failed in PostgreSQL.

Your task is to produce multiple PostgreSQL-compatible SQL candidates while preserving the same meaning.

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
{mismatch_block}

Repair rules:
- Return {n_candidates} diverse PostgreSQL-compatible SQL candidates when possible.
- Preserve the original query meaning as much as possible.
- Use ONLY tables and columns from the schema context.
- Table and column names in PostgreSQL are imported in lowercase.
- If PostgreSQL complains about type comparison such as double precision = text or text = double precision, add explicit CAST only where necessary.
- If PostgreSQL complains about GROUP BY, add required non-aggregated selected columns to GROUP BY or use an equivalent PostgreSQL-compatible form.
- If PostgreSQL complains about AVG/SUM over text, cast the column to DOUBLE PRECISION only where necessary.
- Do not change the task meaning.
- Do not explain.

Output format:
Return ONLY a valid JSON object with exactly one key: "sqls".

Example:
{{"sqls": ["SELECT COUNT(*) FROM singer;", "SELECT CAST(COUNT(*) AS BIGINT) FROM singer;"]}}
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
        default="runs/outputs/a2v/multibackend_postgres_spider1034.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/multibackend_postgres_spider1034_dialect_repaired.jsonl",
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
    completed_indices = prepare_resume_output(out_path) if args.resume else set()
    if args.resume:
        print(f"[RESUME] found {len(completed_indices)} completed rows in {out_path}")

    schema_cache = {}

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
            item["postgres_dialect_repair_stage"] = "none"
            item["postgres_llm_repair_attempted"] = False

            raw_exec_ok = bool(item.get("postgres_exec_ok"))
            raw_same = bool(item.get("postgres_crossdb_same_result"))

            if raw_exec_ok and raw_same:
                out.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
                out.flush()
                continue

            db_id = item["db_id"]
            sqlite_sql = item.get("selected_sql")
            sqlite_result = item.get("selected", {}).get("result")

            repair_triggered += 1
            if not raw_exec_ok:
                fallback_attempted += 1
            else:
                mismatch_triggered += 1

            # Stage 1: use normalize fallback result if available in 09b output.
            norm_exec_ok = item.get("postgres_normalized_exec_ok")
            norm_result = item.get("postgres_normalized_result")
            norm_error = item.get("postgres_normalized_exec_error")
            norm_sql = item.get("postgres_normalized_sql")

            if norm_exec_ok is None:
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
                norm_validation = execute_postgres(
                    sqlite_sql,
                    schema,
                    args,
                    apply_normalization=True,
                )
                norm_exec_ok = norm_validation["postgres_exec_ok"]
                norm_result = norm_validation["postgres_result"]
                norm_error = norm_validation["postgres_exec_error"]
                norm_sql = norm_validation["postgres_sql"]
                item["postgres_normalized_attempted"] = True
                item["postgres_normalized_exec_ok"] = norm_exec_ok
                item["postgres_normalized_exec_error"] = norm_error
                item["postgres_normalized_result"] = norm_result
                item["postgres_normalized_latency_ms"] = norm_validation["postgres_latency_ms"]
                item["postgres_normalized_sql"] = norm_sql

            norm_same = (
                bool(norm_exec_ok)
                and normalize_result(sqlite_result) == normalize_result(norm_result)
            )

            if norm_same:
                same_result = (
                    normalize_result(sqlite_result) == normalize_result(norm_result)
                )
                item["postgres_dialect_repair_attempted"] = True
                item["postgres_dialect_repair_stage"] = "normalize"
                item["postgres_dialect_repair_sql"] = norm_sql
                item["postgres_dialect_repair_exec_ok"] = True
                item["postgres_dialect_repair_error"] = None
                item["postgres_dialect_repair_result"] = norm_result
                item["postgres_dialect_repair_same_result"] = same_result
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

            postgres_sql = norm_sql or normalize_sql_for_postgres(sqlite_sql)
            if raw_exec_ok and not raw_same:
                mismatch_hint = build_result_mismatch_hint(sqlite_result, item.get("postgres_result"))
                postgres_error = "result_mismatch_after_execution"
            else:
                mismatch_hint = None
                postgres_error = norm_error or item.get("postgres_exec_error")
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
                candidates, raw_response = call_postgres_dialect_repair(
                    client=client,
                    model=args.model,
                    db_id=db_id,
                    schema_context=schema_context,
                    sqlite_sql=sqlite_sql,
                    postgres_sql=postgres_sql,
                    postgres_error=postgres_error,
                    n_candidates=args.repair_candidates,
                    mismatch_hint=mismatch_hint,
                )
                all_raw_responses.append(raw_response)

                if not candidates:
                    continue

                for cand_rank, cand_sql in enumerate(candidates[: args.repair_candidates], start=1):
                    validation = execute_postgres(
                        cand_sql,
                        schema,
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
                    postgres_error = best_validation["exec_error"]

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

            item["postgres_dialect_repair_attempted"] = True
            item["postgres_dialect_repair_stage"] = "llm"
            item["postgres_llm_repair_attempted"] = True
            item["postgres_dialect_repair_rounds_used"] = rounds_used
            item["postgres_dialect_repair_candidates"] = candidate_records
            item["postgres_dialect_repair_candidate_count"] = len(candidate_records)
            item["postgres_dialect_repair_first_candidate_sql"] = first_candidate_record["sql"]
            item["postgres_dialect_repair_first_candidate_exec_ok"] = first_candidate_record["exec_ok"]
            item["postgres_dialect_repair_first_candidate_error"] = first_candidate_record["exec_error"]
            item["postgres_dialect_repair_first_candidate_same_result"] = first_candidate_record["same_result"]
            item["postgres_dialect_repair_select_attempted"] = True
            item["postgres_dialect_repair_select_policy"] = "same_result_then_exec_then_row_count_delta"
            item["postgres_dialect_repair_selected_sql"] = best_sql
            item["postgres_dialect_repair_selected_score"] = list(best_score)
            item["postgres_dialect_repair_selected_exec_ok"] = best_validation["exec_ok"]
            item["postgres_dialect_repair_selected_error"] = best_validation["exec_error"]
            item["postgres_dialect_repair_selected_same_result"] = best_same_result
            item["postgres_dialect_repair_sql"] = best_sql
            item["postgres_dialect_repair_raw_response"] = "\n\n".join(all_raw_responses)
            item["postgres_dialect_repair_exec_ok"] = best_validation["exec_ok"]
            item["postgres_dialect_repair_error"] = best_validation["exec_error"]
            item["postgres_dialect_repair_result"] = best_validation["result"]
            item["postgres_dialect_repair_latency_ms"] = best_validation["latency_ms"]
            item["postgres_dialect_repair_same_result"] = best_same_result

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
                    f"[PROGRESS] postgres triggered={repair_triggered} "
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

    print("=== PostgreSQL Dialect Repair Summary ===")
    print(f"total examples: {total}")
    print(f"before PostgreSQL executable (raw SQL): {before_ok}/{total} = {before_ok / total:.3f}")
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
    print(f"after PostgreSQL executable: {after_ok}/{total} = {after_ok / total:.3f}")
    print(f"after same result: {after_same}/{total} = {after_same / total:.3f}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
