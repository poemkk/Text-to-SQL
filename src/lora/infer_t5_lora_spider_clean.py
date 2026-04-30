#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import re
from typing import List, Tuple

import torch
from peft import PeftModel
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from src.rag.retrieve import retrieve_schema_context
from src.spider.load_spider import iter_spider_samples


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

_CODE_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", flags=re.IGNORECASE | re.DOTALL)


def pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def extract_sql(text: str) -> str:
    t = (text or "").strip()

    m = _CODE_FENCE.search(t)
    if m:
        t = m.group(1).strip()

    m = re.search(r"\b(SELECT|WITH)\b", t, flags=re.IGNORECASE)
    if m:
        t = t[m.start():].strip()

    if ";" in t:
        t = t.split(";", 1)[0].strip() + ";"
    elif t:
        t = t.rstrip() + ";"

    return t


def parse_allowed_from_schema(
    schema_text: str,
    max_tables: int = 80,
    max_cols: int = 400,
) -> Tuple[str, str]:
    tables: List[str] = []
    cols: List[str] = []

    for line in (schema_text or "").splitlines():
        s = line.strip()
        if s.startswith("Table: "):
            tables.append(s.replace("Table: ", "").strip())
        elif s.startswith("Column: "):
            cols.append(s.replace("Column: ", "").strip())

    tables = sorted(set(tables))[:max_tables]
    cols = sorted(set(cols))[:max_cols]
    return (
        "\n".join(tables) if tables else "(none)",
        "\n".join(cols) if cols else "(none)",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev_json", default="data/spider/dev.json")
    ap.add_argument("--bm25_index", default="runs/cache/bm25_schema")
    ap.add_argument("--adapter_dir", required=True)
    ap.add_argument("--base_model", default="google/flan-t5-base")
    ap.add_argument("--out", default="runs/outputs/pred_dev1034_lora_rag_clean_ep3.jsonl")
    ap.add_argument("--limit", type=int, default=1034)
    ap.add_argument("--topk_table", type=int, default=5)
    ap.add_argument("--topk_col", type=int, default=8)
    ap.add_argument("--topk_fk", type=int, default=8)
    ap.add_argument("--schema_char_limit", type=int, default=1800)
    ap.add_argument("--max_input_len", type=int, default=512)
    ap.add_argument("--max_new_tokens", type=int, default=256)
    ap.add_argument("--num_beams", type=int, default=4)
    args = ap.parse_args()

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    device = pick_device()
    print("[INFO] device:", device)
    print("[INFO] clean LoRA+RAG inference: one prediction per example")
    print(
        "[INFO] rag:",
        f"topk_table={args.topk_table}",
        f"topk_col={args.topk_col}",
        f"topk_fk={args.topk_fk}",
        f"schema_char_limit={args.schema_char_limit}",
    )

    tok = AutoTokenizer.from_pretrained(args.adapter_dir)
    base = AutoModelForSeq2SeqLM.from_pretrained(args.base_model)
    model = PeftModel.from_pretrained(base, args.adapter_dir)
    model.to(device)
    model.eval()

    n = 0
    with open(args.out, "w", encoding="utf-8") as f:
        for ex in iter_spider_samples(args.dev_json):
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

            allowed_tables, allowed_cols = parse_allowed_from_schema(schema)
            prompt = PROMPT.format(
                schema=schema,
                allowed_tables=allowed_tables,
                allowed_cols=allowed_cols,
                question=ex["question"].strip(),
            )
            inp = tok(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=args.max_input_len,
            ).to(device)

            with torch.no_grad():
                out_ids = model.generate(
                    **inp,
                    do_sample=False,
                    num_beams=args.num_beams,
                    max_new_tokens=args.max_new_tokens,
                    early_stopping=True,
                )

            raw = tok.decode(out_ids[0], skip_special_tokens=True)
            pred = extract_sql(raw)

            rec = {
                "db_id": ex["db_id"],
                "question": ex["question"],
                "gold": ex["query"],
                "pred": pred,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            n += 1
            if n % 50 == 0 or n == args.limit:
                print(f"[{n}/{args.limit}] db={ex['db_id']} pred_len={len(pred)}")

    print("[OK] wrote:", args.out)


if __name__ == "__main__":
    main()
