import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPIDER_DIR = ROOT / "data" / "spider"
DATABASE_DIR = SPIDER_DIR / "database"
TABLES_PATH = SPIDER_DIR / "tables.json"
DEV_PATH = SPIDER_DIR / "dev.json"
RUNS_DIR = ROOT / "runs"

PRIORITY_DATABASES = [
    "concert_singer",
    "pets_1",
    "department_management",
    "car_1",
    "flight_2",
    "world_1",
    "employee_hire_evaluation",
]

VALID_METHODS = {
    "prompt_only",
    "bm25_rag",
    "embedding_rag",
    "lora_only",
    "lora_rag",
    "rule_selector_priority",
    "a2v_strong_repair",
}

METHOD_SOURCES = {
    "prompt_only": ["promptonly", "prompt_only"],
    "bm25_rag": ["bm25rag", "bm25_rag"],
    "embedding_rag": ["embedrag", "embedding_rag"],
    "lora_only": ["loraonly_ep3", "loraonly", "lora_only"],
    "lora_rag": ["lora_rag", "lora-rag"],
}

DEMO_EXAMPLES = {
    "concert_singer": [
        "How many singers do we have?",
        "What is the total number of singers?",
        "Show name, country, age for all singers ordered by age from old to young.",
        "What are the average, minimum and maximum age of singers from France?",
        "Count the number of singers from each country.",
    ],
    "pets_1": [
        "How many pets are heavier than 10?",
        "What is the weight of the youngest dog?",
    ],
}

DEMO_SQL = {
    ("concert_singer", "how many singers do we have"): "SELECT COUNT(*) FROM singer;",
    ("concert_singer", "what is the total number of singers"): "SELECT COUNT(*) FROM singer;",
    (
        "concert_singer",
        "show name country age for all singers ordered by age from old to young",
    ): "SELECT Name, Country, Age FROM singer ORDER BY Age DESC;",
    (
        "concert_singer",
        "show name country age for all singers ordered by age from oldest to youngest",
    ): "SELECT Name, Country, Age FROM singer ORDER BY Age DESC;",
    (
        "concert_singer",
        "what are the average minimum and maximum age of singers from france",
    ): "SELECT AVG(Age), MIN(Age), MAX(Age) FROM singer WHERE Country = 'France';",
    (
        "concert_singer",
        "what is the average minimum and maximum age of all singers from france",
    ): "SELECT AVG(Age), MIN(Age), MAX(Age) FROM singer WHERE Country = 'France';",
    (
        "concert_singer",
        "count the number of singers from each country",
    ): "SELECT Country, COUNT(*) FROM singer GROUP BY Country;",
    (
        "concert_singer",
        "show all countries and the number of singers in each country",
    ): "SELECT Country, COUNT(*) FROM singer GROUP BY Country;",
    ("pets_1", "how many pets are heavier than 10"): "SELECT COUNT(*) FROM Pets WHERE Weight > 10;",
    (
        "pets_1",
        "what is the weight of the youngest dog",
    ): "SELECT Weight FROM Pets WHERE PetType = 'dog' ORDER BY pet_age ASC LIMIT 1;",
}


def _normalize_question(value: str) -> str:
    value = (value or "").lower().replace("’", "'")
    value = re.sub(r"[^a-z0-9_']+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _safe_json_load(path: Path, fallback):
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _tables_by_db():
    data = _safe_json_load(TABLES_PATH, [])
    return {item["db_id"]: item for item in data}


@lru_cache(maxsize=1)
def _dev_examples_by_db():
    examples = {}
    for item in _safe_json_load(DEV_PATH, []):
        db_id = item.get("db_id")
        question = item.get("question")
        if db_id and question:
            examples.setdefault(db_id, []).append(question)
    return examples


def _sqlite_path(db_id: str) -> Path:
    return DATABASE_DIR / db_id / f"{db_id}.sqlite"


def _sqlite_tables(db_id: str):
    db_path = _sqlite_path(db_id)
    if not db_path.exists():
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def get_databases():
    table_index = _tables_by_db()
    database_ids = [p.name for p in DATABASE_DIR.iterdir() if p.is_dir()] if DATABASE_DIR.exists() else []
    ordered = [db for db in PRIORITY_DATABASES if db in database_ids or db in table_index]
    if not ordered:
        ordered = sorted(database_ids)[:20]
    result = []
    for db_id in ordered:
        schema = table_index.get(db_id)
        if schema:
            tables = schema.get("table_names_original") or schema.get("table_names") or []
        else:
            tables = _sqlite_tables(db_id)
        if tables:
            result.append({"db_id": db_id, "tables": tables})
    return result


def get_examples(db_id: str):
    examples = list(DEMO_EXAMPLES.get(db_id, []))
    seen = {_normalize_question(q) for q in examples}
    for question in _dev_examples_by_db().get(db_id, []):
        key = _normalize_question(question)
        if key not in seen:
            examples.append(question)
            seen.add(key)
        if len(examples) >= 12:
            break
    return examples


def get_schema(db_id: str):
    schema = _tables_by_db().get(db_id)
    if not schema:
        return _schema_from_sqlite(db_id)

    table_names = schema.get("table_names_original") or schema.get("table_names") or []
    column_names = schema.get("column_names_original") or schema.get("column_names") or []
    column_types = schema.get("column_types") or []
    tables = [{"name": name, "columns": []} for name in table_names]

    for idx, (table_idx, column_name) in enumerate(column_names):
        if table_idx < 0 or table_idx >= len(tables) or column_name == "*":
            continue
        column_type = column_types[idx] if idx < len(column_types) else "text"
        tables[table_idx]["columns"].append({"name": column_name, "type": column_type})

    foreign_keys = []
    for from_idx, to_idx in schema.get("foreign_keys", []):
        from_col = _column_ref(table_names, column_names, from_idx)
        to_col = _column_ref(table_names, column_names, to_idx)
        if from_col and to_col:
            foreign_keys.append({"from": from_col, "to": to_col})

    return {"db_id": db_id, "tables": tables, "foreign_keys": foreign_keys}


def _column_ref(table_names, column_names, column_idx):
    if column_idx >= len(column_names):
        return None
    table_idx, column_name = column_names[column_idx]
    if table_idx < 0 or table_idx >= len(table_names):
        return None
    return f"{table_names[table_idx]}.{column_name}"


def _schema_from_sqlite(db_id: str):
    db_path = _sqlite_path(db_id)
    if not db_path.exists():
        return {"db_id": db_id, "tables": [], "foreign_keys": []}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = []
        for table_name in _sqlite_tables(db_id):
            info = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            columns = [{"name": row[1], "type": row[2] or "text"} for row in info]
            tables.append({"name": table_name, "columns": columns})
        return {"db_id": db_id, "tables": tables, "foreign_keys": []}
    finally:
        conn.close()


def schema_as_text(db_id: str):
    schema = get_schema(db_id)
    lines = []
    for table in schema["tables"]:
        cols = ", ".join(f"{col['name']}:{col['type']}" for col in table["columns"])
        lines.append(f"{table['name']}({cols})")
    if schema["foreign_keys"]:
        lines.append("Foreign keys:")
        lines.extend(f"{fk['from']} -> {fk['to']}" for fk in schema["foreign_keys"])
    return "\n".join(lines)


@lru_cache(maxsize=1)
def _cached_sql_results():
    paths = [
        RUNS_DIR / "outputs" / "a2v" / "selected_after_strong_repair_practical_v2_spider1034_full.jsonl",
        RUNS_DIR / "outputs" / "a2v" / "selected_spider1034.jsonl",
    ]
    paths.extend(sorted((RUNS_DIR / "outputs").glob("pred_dev*.jsonl")))

    records = []
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("db_id") and row.get("question"):
                    row["_source_file"] = str(path.relative_to(ROOT))
                    records.append(row)
    return records


def _find_cached_record(db_id: str, question: str):
    wanted = _normalize_question(question)
    for row in _cached_sql_results():
        if row.get("db_id") == db_id and _normalize_question(row.get("question")) == wanted:
            return row
    return None


def _select_candidate(record, method: str):
    if not record:
        return None

    if method == "a2v_strong_repair":
        sql = record.get("selected_sql")
        if sql:
            return {
                "source": record.get("selected_source") or "a2v_strong_repair",
                "sql": sql,
                "variant": record.get("selected_variant"),
            }

    if method == "rule_selector_priority":
        sql = record.get("selected_sql")
        if sql:
            return {
                "source": record.get("selected_source") or "rule_selector_priority",
                "sql": sql,
            }

    aliases = set(METHOD_SOURCES.get(method, []))
    for candidate in record.get("candidates", []):
        if candidate.get("source") in aliases:
            return {"source": candidate.get("source"), "sql": candidate.get("sql")}

    if record.get("pred"):
        source_file = record.get("_source_file", "")
        if any(alias in source_file for alias in aliases):
            return {"source": method, "sql": record["pred"]}

    if record.get("selected_sql"):
        return {"source": record.get("selected_source") or method, "sql": record["selected_sql"]}
    return None


def _demo_sql(db_id: str, question: str):
    key = (db_id, _normalize_question(question))
    return DEMO_SQL.get(key)


def generate_sql(db_id: str, question: str, method: str):
    if method not in VALID_METHODS:
        raise ValueError(f"Unsupported SQL generation method: {method}")

    record = _find_cached_record(db_id, question)
    candidate = _select_candidate(record, method)
    source = "cached_prediction"

    if not candidate:
        sql = _demo_sql(db_id, question)
        if not sql:
            sql = f"-- No cached prediction found for {db_id}.\nSELECT 1;"
        candidate = {"source": method, "sql": sql}
        source = "demo_rule"

    candidates = []
    if record and record.get("candidates"):
        candidates = [
            {"source": c.get("source"), "sql": c.get("sql"), "exec_ok": c.get("exec_ok")}
            for c in record["candidates"]
            if c.get("sql")
        ]
    if not candidates:
        candidates = [candidate]

    return {
        "task_type": "sql",
        "db_id": db_id,
        "question": question,
        "method": method,
        "context": {"type": "schema", "content": schema_as_text(db_id)},
        "candidates": candidates,
        "selected_sql": candidate["sql"],
        "source": source,
    }


def execute_sql(db_id: str, sql: str):
    db_path = _sqlite_path(db_id)
    if not db_path.exists():
        return {
            "exec_ok": False,
            "error": f"database not found: {db_id}",
            "columns": [],
            "rows": [],
            "row_count": 0,
        }

    if not sql or not sql.strip():
        return {"exec_ok": False, "error": "empty SQL", "columns": [], "rows": [], "row_count": 0}

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cursor = conn.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = [_json_safe_row(row) for row in cursor.fetchall()]
        return {
            "exec_ok": True,
            "error": None,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }
    except Exception as exc:
        return {"exec_ok": False, "error": str(exc), "columns": [], "rows": [], "row_count": 0}
    finally:
        conn.close()


def _json_safe_row(row):
    safe = []
    for value in row:
        if isinstance(value, bytes):
            safe.append(value.decode("utf-8", errors="replace"))
        else:
            safe.append(value)
    return safe


def repair_demo(db_id: str, question: str, bad_sql: str, error: str):
    repaired_sql = bad_sql or ""
    repair_reason = "No deterministic repair rule matched; the original SQL was re-tested."

    tables = {table["name"].lower(): table["name"] for table in get_schema(db_id)["tables"]}

    missing_table = re.search(r"no such table:\s*([A-Za-z_][A-Za-z0-9_]*)", error or "", re.I)
    if missing_table:
        bad_table = missing_table.group(1)
        singular = bad_table[:-1] if bad_table.lower().endswith("s") else bad_table
        if db_id == "concert_singer" and bad_table.lower() == "singers":
            repaired_sql = re.sub(r"\bsingers\b", "singer", repaired_sql, flags=re.I)
            repair_reason = "The table singers does not exist; schema contains singer."
        elif singular.lower() in tables:
            repaired_sql = re.sub(rf"\b{re.escape(bad_table)}\b", tables[singular.lower()], repaired_sql, flags=re.I)
            repair_reason = f"The table {bad_table} does not exist; schema contains {tables[singular.lower()]}."

    missing_column = re.search(r"no such column:\s*(?:[A-Za-z_][A-Za-z0-9_]*\.)?([A-Za-z_][A-Za-z0-9_]*)", error or "", re.I)
    if missing_column:
        bad_col = missing_column.group(1)
        columns = _column_lookup(db_id)
        if bad_col.lower() in columns:
            repaired_sql = re.sub(rf"\b{re.escape(bad_col)}\b", columns[bad_col.lower()], repaired_sql)
            repair_reason = f"The column {bad_col} was rewritten to match schema casing."

    if db_id == "concert_singer" and "singers" in repaired_sql.lower():
        repaired_sql = re.sub(r"\bsingers\b", "singer", repaired_sql, flags=re.I)
        repair_reason = "The table singers does not exist; schema contains singer."

    if not repaired_sql.strip() and _demo_sql(db_id, question):
        repaired_sql = _demo_sql(db_id, question)
        repair_reason = "Fallback demo rule selected a known executable SQL query for this question."

    execution = execute_sql(db_id, repaired_sql)
    return {
        "repair_attempted": True,
        "original_sql": bad_sql,
        "error": error,
        "repaired_sql": repaired_sql,
        "repair_reason": repair_reason,
        "exec_ok": execution["exec_ok"],
        "columns": execution["columns"],
        "rows": execution["rows"],
        "row_count": execution["row_count"],
        "exec_error": execution["error"],
    }


def _column_lookup(db_id: str):
    columns = {}
    for table in get_schema(db_id)["tables"]:
        for col in table["columns"]:
            columns[col["name"].lower()] = col["name"]
    return columns
