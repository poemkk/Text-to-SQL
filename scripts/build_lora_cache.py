#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, json, argparse
from src.spider.load_spider import iter_spider_samples
from src.rag.retrieve import retrieve_schema_context

PROMPT = """You are a Text-to-SQL system.
Write ONE valid SQLite SQL query.

Rules:
- Output SQL ONLY. One statement.
- Use ONLY table/column names from the ALLOWED LIST.
- If a table/column is not in the allowed list, you MUST NOT use it.
- The SQL must start with SELECT or WITH and end with a semicolon.

Schema context:
{schema}

ALLOWED TABLES:
{allowed_tables}

ALLOWED COLUMNS:
{allowed_cols}

Question:
{question}

SQL:
"""

def parse_allowed(schema_text: str):
    tables, cols = [], []
    for line in schema_text.splitlines():
        s = line.strip()
        if s.startswith("Table: "):
            tables.append(s.replace("Table: ", "").strip())
        if s.startswith("Column: "):
            cols.append(s.replace("Column: ", "").strip())
    return sorted(set(tables)), sorted(set(cols))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in_json", required=True)
    ap.add_argument("--out_jsonl", required=True)
    ap.add_argument("--bm25_index", default="runs/cache/bm25_schema")
    ap.add_argument("--limit", type=int, default=10000)
    ap.add_argument("--schema_char_limit", type=int, default=1800)
    ap.add_argument("--topk_table", type=int, default=5)
    ap.add_argument("--topk_col", type=int, default=8)
    ap.add_argument("--topk_fk", type=int, default=8)
    ap.add_argument("--max_tables", type=int, default=50)
    ap.add_argument("--max_cols", type=int, default=200)
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out_jsonl), exist_ok=True)

    n = 0
    with open(args.out_jsonl, "w", encoding="utf-8") as f:
        for ex in iter_spider_samples(args.in_json):
            if n >= args.limit:
                break
            schema = retrieve_schema_context(
                index_dir=args.bm25_index,
                question=ex["question"],
                db_id=ex["db_id"],
                topk_table=args.topk_table,
                topk_col=args.topk_col,
                topk_fk=args.topk_fk,
            )
            if args.schema_char_limit and len(schema) > args.schema_char_limit:
                schema = schema[:args.schema_char_limit]

            tables, cols = parse_allowed(schema)
            allowed_tables = "\n".join(tables[:args.max_tables]) if tables else "(none)"
            allowed_cols = "\n".join(cols[:args.max_cols]) if cols else "(none)"

            inp = PROMPT.format(
                schema=schema,
                allowed_tables=allowed_tables,
                allowed_cols=allowed_cols,
                question=ex["question"],
            )
            tgt = (ex.get("query") or "").strip()
            if tgt and not tgt.endswith(";"):
                tgt += ";"

            rec = {"input_text": inp, "target_text": tgt, "db_id": ex["db_id"]}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            if n % 200 == 0:
                print(f"[{n}] cached")

    print("[OK] wrote", n, "to", args.out_jsonl)

if __name__ == "__main__":
    main()
