import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path


SOURCE_TIE_RANK = {
    "gemini-3.1-flash-lite-preview": 0,
    "gpt-5.4-mini": 1,
    "grok-4-fast": 2,
    "claude-haiku-4-5-20251001": 3,
    "embedrag": 10,
    "bm25rag": 11,
    "lora_rag": 12,
    "promptonly": 13,
    "loraonly_ep3": 14,
}


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path, rows):
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def source_rank(source):
    return SOURCE_TIE_RANK.get(source, 999)


def compact_ws(text):
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_sql(sql):
    if not sql or not isinstance(sql, str):
        return ""
    sql = re.sub(r"--.*?$", " ", sql, flags=re.MULTILINE)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return compact_ws(sql)


def normalize_cell(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def normalize_result_key(result):
    if result is None:
        return "NULL_RESULT"

    normalized_rows = []
    for row in result:
        if isinstance(row, (list, tuple)):
            normalized_rows.append(tuple(normalize_cell(cell) for cell in row))
        else:
            normalized_rows.append((normalize_cell(row),))

    return json.dumps(sorted(normalized_rows), ensure_ascii=False, sort_keys=True)


def is_non_empty_result(result):
    return result not in (None, [])


def truncate_text(text, max_chars):
    text = text or ""
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " ..."


def flatten_primary_keys(primary_keys):
    flat = set()
    for key in primary_keys or []:
        if isinstance(key, list):
            flat.update(key)
        else:
            flat.add(key)
    return flat


def load_schema_text_by_db(tables_path, max_columns_per_table=80, max_fks=60):
    return {
        db_id: info["text"]
        for db_id, info in load_schema_info_by_db(
            tables_path,
            max_columns_per_table=max_columns_per_table,
            max_fks=max_fks,
        ).items()
    }


def load_schema_info_by_db(tables_path, max_columns_per_table=80, max_fks=60):
    tables_path = Path(tables_path)
    schemas = json.loads(tables_path.read_text(encoding="utf-8"))
    by_db = {}

    for schema in schemas:
        db_id = schema["db_id"]
        table_names = schema.get("table_names_original") or schema.get("table_names") or []
        column_names = schema.get("column_names_original") or schema.get("column_names") or []
        column_types = schema.get("column_types") or []
        primary_keys = flatten_primary_keys(schema.get("primary_keys"))
        foreign_keys = schema.get("foreign_keys") or []

        columns_by_table = defaultdict(list)
        column_refs = []
        for col_idx, pair in enumerate(column_names):
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            table_idx, col_name = pair
            if table_idx == -1:
                continue
            col_type = column_types[col_idx] if col_idx < len(column_types) else "unknown"
            pk = " primary_key" if col_idx in primary_keys else ""
            columns_by_table[table_idx].append(f"{col_name} {col_type}{pk}")
            table_name = table_names[table_idx] if 0 <= table_idx < len(table_names) else ""
            column_refs.append({
                "table": table_name,
                "column": col_name,
                "qualified": f"{table_name}.{col_name}" if table_name else col_name,
                "type": col_type,
                "primary_key": col_idx in primary_keys,
            })

        lines = [f"Database {db_id}."]
        for table_idx, table_name in enumerate(table_names):
            cols = columns_by_table.get(table_idx, [])[:max_columns_per_table]
            if cols:
                lines.append(f"Table {table_name}: " + "; ".join(cols) + ".")
            else:
                lines.append(f"Table {table_name}.")

        fk_lines = []
        for left, right in foreign_keys[:max_fks]:
            left_ref = column_reference(column_names, table_names, left)
            right_ref = column_reference(column_names, table_names, right)
            if left_ref and right_ref:
                fk_lines.append(f"{left_ref} -> {right_ref}")
        if fk_lines:
            lines.append("Foreign keys: " + "; ".join(fk_lines) + ".")

        by_db[db_id] = {
            "text": "\n".join(lines),
            "tables": table_names,
            "columns": column_refs,
            "foreign_keys": fk_lines,
        }

    return by_db


def column_reference(column_names, table_names, col_idx):
    if col_idx is None or col_idx < 0 or col_idx >= len(column_names):
        return None
    table_idx, col_name = column_names[col_idx]
    if table_idx is None or table_idx < 0 or table_idx >= len(table_names):
        return col_name
    return f"{table_names[table_idx]}.{col_name}"


def has_function(sql, name):
    return re.search(rf"\b{re.escape(name)}\s*\(", sql, flags=re.IGNORECASE) is not None


def select_clause(sql):
    match = re.search(r"\bselect\b\s+(.*?)\s+\bfrom\b", sql, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def sql_structure_summary(sql):
    normalized = normalize_sql(sql).lower()
    selected = select_clause(normalized)
    select_items = selected.count(",") + 1 if selected else 0
    flags = {
        "select_items": select_items,
        "joins": len(re.findall(r"\bjoin\b", normalized)),
        "where": bool(re.search(r"\bwhere\b", normalized)),
        "group_by": bool(re.search(r"\bgroup\s+by\b", normalized)),
        "order_by": bool(re.search(r"\border\s+by\b", normalized)),
        "limit": bool(re.search(r"\blimit\b", normalized)),
        "distinct": bool(re.search(r"\bdistinct\b", normalized)),
        "count": has_function(normalized, "count"),
        "avg": has_function(normalized, "avg"),
        "sum": has_function(normalized, "sum"),
        "max": has_function(normalized, "max"),
        "min": has_function(normalized, "min"),
        "not_in_or_exists": bool(re.search(r"\bnot\s+in\s*\(|\bnot\s+exists\b", normalized)),
    }
    return ", ".join(f"{key}={value}" for key, value in flags.items())


def result_shape(result):
    if result is None:
        return {
            "row_count": None,
            "col_count": None,
            "empty": None,
            "scalar": False,
        }
    if not isinstance(result, list):
        return {
            "row_count": None,
            "col_count": None,
            "empty": False,
            "scalar": False,
        }
    if not result:
        return {
            "row_count": 0,
            "col_count": 0,
            "empty": True,
            "scalar": False,
        }
    first = result[0]
    col_count = len(first) if isinstance(first, (list, tuple)) else 1
    return {
        "row_count": len(result),
        "col_count": col_count,
        "empty": False,
        "scalar": len(result) == 1 and col_count == 1,
    }


def result_shape_key(result):
    shape = result_shape(result)
    return (
        shape["row_count"],
        shape["col_count"],
        shape["empty"],
        shape["scalar"],
    )


def value_type_name(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "text"


def result_type_profile(result, max_rows=5):
    if not result or not isinstance(result, list):
        return "types=unknown"

    counts = Counter()
    for row in result[:max_rows]:
        values = row if isinstance(row, (list, tuple)) else [row]
        for value in values:
            counts[value_type_name(value)] += 1

    total = sum(counts.values())
    if not total:
        return "types=empty"
    return "types=" + ",".join(f"{key}:{counts[key]}" for key in sorted(counts))


def summarize_result(result, columns=None, max_rows=3, max_chars=500):
    shape = result_shape(result)
    column_text = "columns=unknown"
    if columns:
        column_text = "columns=" + truncate_text(json.dumps(columns, ensure_ascii=False), 180)

    if result is None:
        return f"result=NULL; {column_text}"
    if result == []:
        return f"result=empty; rows=0; cols=0; {column_text}"

    rows = result[:max_rows] if isinstance(result, list) else result
    sample = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    return (
        f"result=non_empty; rows={shape['row_count']}; cols={shape['col_count']}; "
        f"scalar={shape['scalar']}; {column_text}; {result_type_profile(result)}; "
        f"sample={truncate_text(sample, max_chars)}"
    )


def identifier_tokens(identifier):
    chunks = re.sub(r"([a-z])([A-Z])", r"\1 \2", identifier or "")
    return {
        token.lower()
        for token in re.split(r"[^A-Za-z0-9]+|_", chunks)
        if len(token) >= 2
    }


def text_tokens(text):
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]+", text or "")
        if len(token) >= 2
    }


def schema_link_summary(question, sql, schema_info):
    if not isinstance(schema_info, dict):
        return "schema_link=unavailable"

    sql_l = (sql or "").lower()
    q_tokens = text_tokens(question)

    used_tables = []
    used_columns = []
    used_schema_tokens = set()

    for table in schema_info.get("tables", []):
        table_l = table.lower()
        if re.search(rf"\b{re.escape(table_l)}\b", sql_l):
            used_tables.append(table)
            used_schema_tokens.update(identifier_tokens(table))

    for column in schema_info.get("columns", []):
        col_name = column.get("column", "")
        qualified = column.get("qualified", "")
        col_l = col_name.lower()
        qual_l = qualified.lower()
        if re.search(rf"\b{re.escape(col_l)}\b", sql_l) or qual_l in sql_l:
            used_columns.append(qualified)
            used_schema_tokens.update(identifier_tokens(col_name))

    question_overlap = sorted(q_tokens & used_schema_tokens)
    return (
        f"tables_used={len(used_tables)} {truncate_text(', '.join(used_tables[:12]), 240)}; "
        f"columns_used={len(used_columns)} {truncate_text(', '.join(used_columns[:24]), 360)}; "
        f"question_schema_token_overlap={len(question_overlap)} "
        f"{truncate_text(', '.join(question_overlap[:24]), 240)}"
    )


def first_present(mapping, keys, default=None):
    for key in keys:
        if key in mapping and mapping.get(key) is not None:
            return mapping.get(key)
    return default


def build_pool(candidates):
    pool = []

    for idx, cand in enumerate(candidates or []):
        source = cand.get("source") or cand.get("model") or "unknown"
        original_label_available = "exec_correct" in cand
        original_sql = first_present(cand, ["sql", "pred", "prediction"], "")
        repair_sql = first_present(
            cand,
            [
                "strong_repair_final_sql",
                "repair_sql",
                "repair_final_sql",
                "final_repair_sql",
            ],
            None,
        )
        repair_attempted = bool(
            cand.get("strong_repair_attempted")
            or cand.get("repair_attempted")
            or repair_sql
        )
        original_exec_ok = bool(cand.get("exec_ok"))
        repair_exec_ok = bool(
            cand.get("strong_repair_exec_ok")
            or cand.get("repair_exec_ok")
            or cand.get("repair_ok")
        )

        original_result = cand.get("result")
        pool.append({
            "candidate_index": idx,
            "source": source,
            "variant": "original",
            "sql": original_sql,
            "exec_ok": original_exec_ok,
            "exec_correct": bool(cand.get("exec_correct")),
            "label_available": original_label_available,
            "exec_error": cand.get("exec_error") or cand.get("error"),
            "result": original_result,
            "result_columns": cand.get("result_columns") or cand.get("columns"),
            "result_key": cand.get("result_key") or normalize_result_key(original_result),
            "latency_ms": cand.get("latency_ms"),
            "latency_ms_generation": cand.get("latency_ms_generation"),
            "original_exec_ok": original_exec_ok,
            "repair_attempted": repair_attempted,
            "repair_available": bool(repair_sql),
            "repair_exec_ok": repair_exec_ok,
            "order": len(pool),
        })

        if repair_attempted or repair_sql:
            repair_label_available = (
                "strong_repair_exec_correct" in cand
                or "repair_exec_correct" in cand
            )
            repair_result = first_present(
                cand,
                ["strong_repair_result", "repair_result", "repair_exec_result"],
                None,
            )
            pool.append({
                "candidate_index": idx,
                "source": source,
                "variant": "strong_repair",
                "sql": repair_sql,
                "exec_ok": repair_exec_ok,
                "exec_correct": bool(
                    cand.get("strong_repair_exec_correct")
                    or cand.get("repair_exec_correct")
                ),
                "label_available": repair_label_available,
                "exec_error": (
                    cand.get("strong_repair_exec_error")
                    or cand.get("repair_exec_error")
                    or cand.get("repair_error")
                ),
                "result": repair_result,
                "result_columns": (
                    cand.get("strong_repair_result_columns")
                    or cand.get("repair_result_columns")
                    or cand.get("result_columns")
                    or cand.get("columns")
                ),
                "result_key": (
                    cand.get("strong_repair_result_key")
                    or cand.get("repair_result_key")
                    or normalize_result_key(repair_result)
                ),
                "latency_ms": cand.get("strong_repair_latency_ms") or cand.get("repair_latency_ms"),
                "latency_ms_generation": cand.get("latency_ms_generation"),
                "original_exec_ok": original_exec_ok,
                "repair_attempted": repair_attempted,
                "repair_available": bool(repair_sql),
                "repair_exec_ok": repair_exec_ok,
                "order": len(pool),
            })

    return pool


def enrich_pool(pool):
    executable = [cand for cand in pool if cand.get("exec_ok")]
    counts = Counter(
        cand.get("result_key")
        for cand in executable
        if cand.get("result_key") != "NULL_RESULT"
    )
    executable_count = len(executable)

    enriched = []
    for cand in pool:
        copy = dict(cand)
        support = counts.get(cand.get("result_key"), 0) if cand.get("exec_ok") else 0
        copy["non_empty_result"] = is_non_empty_result(cand.get("result"))
        copy["result_support"] = support
        copy["result_support_frac"] = support / executable_count if executable_count else 0.0
        copy["executable_count"] = executable_count
        copy["result_shape"] = result_shape(cand.get("result"))
        enriched.append(copy)
    return enriched


def repair_trace_text(candidate):
    if candidate.get("variant") == "strong_repair":
        return (
            "repair_variant=true; "
            f"original_exec_ok={candidate.get('original_exec_ok')}; "
            f"repair_exec_ok={candidate.get('repair_exec_ok')}; "
            f"repair_available={candidate.get('repair_available')}"
        )
    return (
        "repair_variant=false; "
        f"repair_available={candidate.get('repair_available')}; "
        f"repair_exec_ok={candidate.get('repair_exec_ok')}"
    )


def candidate_to_text(item, candidate, schema_info, max_schema_chars=4500):
    if isinstance(schema_info, dict):
        schema_text = schema_info.get("text", "")
    else:
        schema_text = schema_info or ""
        schema_info = None
    schema_text = truncate_text(schema_text, max_schema_chars)
    sql = normalize_sql(candidate.get("sql"))
    exec_error = compact_ws(candidate.get("exec_error") or "")
    if exec_error:
        exec_error = truncate_text(exec_error, 400)
    else:
        exec_error = "none"

    parts = [
        f"Question: {compact_ws(item.get('question'))}",
        f"Database id: {item.get('db_id')}",
        "Schema:",
        schema_text,
        (
            "Candidate metadata: "
            f"source={candidate.get('source')}; "
            f"variant={candidate.get('variant')}; "
            f"candidate_index={candidate.get('candidate_index')}"
        ),
        "SQL:",
        sql,
        (
            "Execution evidence: "
            f"exec_ok={candidate.get('exec_ok')}; "
            f"exec_error={exec_error}; "
            f"non_empty_result={candidate.get('non_empty_result')}; "
            f"result_support={candidate.get('result_support')}/"
            f"{candidate.get('executable_count')}"
        ),
        "Result evidence: " + summarize_result(
            candidate.get("result"),
            columns=candidate.get("result_columns"),
        ),
        "SQL structure: " + sql_structure_summary(sql),
        "Schema linking: " + schema_link_summary(item.get("question"), sql, schema_info),
        "Repair trace: " + repair_trace_text(candidate),
    ]
    return "\n".join(parts)


def make_item_candidates(item, schema_by_db, max_schema_chars=4500):
    schema_info = schema_by_db.get(item.get("db_id"), "")
    pool = enrich_pool(build_pool(item.get("candidates", [])))
    for candidate in pool:
        candidate["selector_text"] = candidate_to_text(
            item=item,
            candidate=candidate,
            schema_info=schema_info,
            max_schema_chars=max_schema_chars,
        )
    return pool


def negative_type(candidate, positive_shape_keys=None):
    positive_shape_keys = positive_shape_keys or set()
    if candidate.get("label_available") and candidate.get("exec_ok") and not candidate.get("exec_correct"):
        support = candidate.get("result_support", 0) or 0
        shape_key = result_shape_key(candidate.get("result"))
        if support >= 2:
            return "hard_supported_executable_wrong"
        if shape_key in positive_shape_keys:
            return "hard_same_shape_executable_wrong"
        if is_non_empty_result(candidate.get("result")):
            return "hard_non_empty_executable_wrong"
        return "hard_empty_executable_wrong"
    if candidate.get("label_available") and candidate.get("exec_ok") and candidate.get("exec_correct"):
        return "positive_execution_correct"
    if candidate.get("exec_ok") and not candidate.get("label_available"):
        return "hard_executable_wrong"
    if not candidate.get("exec_ok"):
        return "easy_execution_error"
    return "other_semantic_wrong"


def negative_priority(negative_type_name):
    priority = {
        "hard_supported_executable_wrong": 0,
        "hard_same_shape_executable_wrong": 1,
        "hard_non_empty_executable_wrong": 2,
        "hard_empty_executable_wrong": 3,
        "hard_executable_wrong": 4,
        "other_semantic_wrong": 5,
        "easy_execution_error": 6,
    }
    return priority.get(negative_type_name, 999)


def compact_candidate_for_pair(candidate):
    return {
        "candidate_index": candidate.get("candidate_index"),
        "source": candidate.get("source"),
        "variant": candidate.get("variant"),
        "sql": candidate.get("sql"),
        "exec_ok": candidate.get("exec_ok"),
        "exec_correct": candidate.get("exec_correct"),
        "result_support": candidate.get("result_support"),
        "non_empty_result": candidate.get("non_empty_result"),
        "text": candidate.get("selector_text"),
    }


def build_pairwise_records(item, schema_by_db, max_pairs_per_item=80, rng=None, max_schema_chars=4500):
    rng = rng or random.Random(13)
    pool = make_item_candidates(item, schema_by_db, max_schema_chars=max_schema_chars)
    positives = [cand for cand in pool if cand.get("label_available") and cand.get("exec_correct")]
    negatives = [cand for cand in pool if cand.get("label_available") and not cand.get("exec_correct")]

    if not positives or not negatives:
        return []

    positive_shape_keys = {result_shape_key(cand.get("result")) for cand in positives}
    typed_negatives = [
        (negative_type(cand, positive_shape_keys), cand)
        for cand in negatives
    ]
    typed_negatives.sort(key=lambda item: negative_priority(item[0]))

    pairs = []
    for neg_type, neg in typed_negatives:
        candidate_pairs = [(pos, neg_type, neg) for pos in positives]
        rng.shuffle(candidate_pairs)
        for pair in candidate_pairs:
            if len(pairs) >= max_pairs_per_item:
                break
            pairs.append(pair)
        if len(pairs) >= max_pairs_per_item:
            break

    records = []
    for pair_id, (pos, neg_type, neg) in enumerate(pairs):
        records.append({
            "idx": item.get("idx"),
            "db_id": item.get("db_id"),
            "question": item.get("question"),
            "gold": item.get("gold"),
            "pair_id": pair_id,
            "negative_type": neg_type,
            "positive": compact_candidate_for_pair(pos),
            "negative": compact_candidate_for_pair(neg),
        })
    return records


def assign_db_folds(rows, folds):
    by_db = defaultdict(int)
    for row in rows:
        by_db[row.get("db_id", "unknown")] += 1

    fold_sizes = [0] * folds
    db_to_fold = {}

    for db_id, count in sorted(by_db.items(), key=lambda item: (-item[1], item[0])):
        fold_idx = min(range(folds), key=lambda idx: fold_sizes[idx])
        db_to_fold[db_id] = fold_idx
        fold_sizes[fold_idx] += count

    row_folds = [db_to_fold.get(row.get("db_id", "unknown"), 0) for row in rows]
    return row_folds, db_to_fold, fold_sizes


def select_rule_priority(pool):
    if not pool:
        return None
    executable = [cand for cand in pool if cand.get("exec_ok")]
    candidates = executable if executable else pool
    return sorted(
        candidates,
        key=lambda cand: (
            source_rank(cand.get("source")),
            0 if cand.get("variant") == "original" else 1,
            cand.get("order", 999999),
        ),
    )[0]


def select_consensus_practical(pool):
    if not pool:
        return None
    executable = [cand for cand in pool if cand.get("exec_ok")]
    if not executable:
        return select_rule_priority(pool)

    counts = Counter(cand.get("result_key") for cand in executable)
    return sorted(
        executable,
        key=lambda cand: (
            -counts.get(cand.get("result_key"), 0),
            0 if cand.get("non_empty_result") else 1,
            source_rank(cand.get("source")),
            0 if cand.get("variant") == "original" else 1,
            cand.get("order", 999999),
        ),
    )[0]


def select_oracle(pool):
    correct = [cand for cand in pool if cand.get("label_available") and cand.get("exec_correct")]
    if correct:
        return sorted(
            correct,
            key=lambda cand: (
                source_rank(cand.get("source")),
                0 if cand.get("variant") == "original" else 1,
                cand.get("order", 999999),
            ),
        )[0]
    return select_consensus_practical(pool)


def has_hard_semantic_choice(pool):
    has_correct = any(cand.get("label_available") and cand.get("exec_correct") for cand in pool)
    has_exec_wrong = any(
        cand.get("label_available")
        and cand.get("exec_ok")
        and not cand.get("exec_correct")
        for cand in pool
    )
    return has_correct and has_exec_wrong


def compact_selected(candidate):
    if candidate is None:
        return None
    return {
        "candidate_index": candidate.get("candidate_index"),
        "source": candidate.get("source"),
        "variant": candidate.get("variant"),
        "sql": candidate.get("sql"),
        "score": candidate.get("semantic_selector_score"),
        "exec_ok": candidate.get("exec_ok"),
        "exec_correct": candidate.get("exec_correct"),
        "label_available": candidate.get("label_available"),
        "result": candidate.get("result"),
        "result_support": candidate.get("result_support"),
        "non_empty_result": candidate.get("non_empty_result"),
    }
