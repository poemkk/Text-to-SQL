#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import time
import urllib.request

from src.common.sqlite_exec import run_sqlite_query
from src.rag.retrieve import retrieve_schema_context

REPAIR_TEMPLATE = """You are a Text-to-SQL expert.
You are given a database schema context, a user question, a SQL query that FAILED, and the SQLite error message.

Task:
- Fix the SQL so it executes successfully on SQLite and answers the question.
Rules:
- Use ONLY tables/columns shown in the schema context.
- JOIN is allowed ONLY if supported by the foreign keys shown.
- Return ONLY the corrected SQL. One statement. No explanation.

Schema context:
{schema_context}

Question:
{question}

Failed SQL:
{bad_sql}

SQLite error:
{error_msg}

Corrected SQL:
"""

def call_chat_api(prompt: str, api_key: str, model: str, base_url: str, timeout_sec: int = 60) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.0,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    return out["choices"][0]["message"]["content"].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred_jsonl", required=True)
    ap.add_argument("--out", default="runs/outputs/pred_dev_deepseek_repaired.jsonl")
    ap.add_argument("--db_root", default="data/spider/database")

    ap.add_argument("--bm25_index", default="runs/cache/bm25_schema")
    ap.add_argument("--topk_table", type=int, default=5)
    ap.add_argument("--topk_col", type=int, default=8)
    ap.add_argument("--topk_fk", type=int, default=8)

    ap.add_argument("--base_url", default="https://api.deepseek.com/chat/completions")
    ap.add_argument("--api_key", default="")
    ap.add_argument("--model", default="deepseek-reasoner")  # repair 用 reasoner 更合适
    ap.add_argument("--sleep", type=float, default=0.2)
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    if not args.api_key:
        raise SystemExit("Missing --api_key")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    repaired = 0
    total = 0

    with open(args.pred_jsonl, "r", encoding="utf-8") as fin, open(args.out, "w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            ex = json.loads(line)
            total += 1

            db_id = ex["db_id"]
            question = ex["question"]
            gold = (ex.get("gold") or "").strip()
            pred = (ex.get("pred") or "").strip()

            sqlite_path = os.path.join(args.db_root, db_id, f"{db_id}.sqlite")
            ok_p, _, err_p = run_sqlite_query(sqlite_path, pred, timeout=float(args.timeout))

            new_pred = pred
            repair_used = False
            repair_error = None

            if not ok_p:
                schema_ctx = retrieve_schema_context(
                    index_dir=args.bm25_index,
                    question=question,
                    db_id=db_id,
                    topk_table=args.topk_table,
                    topk_col=args.topk_col,
                    topk_fk=args.topk_fk,
                )
                prompt = REPAIR_TEMPLATE.format(
                    schema_context=schema_ctx,
                    question=question,
                    bad_sql=pred,
                    error_msg=err_p or ""
                )

                try:
                    new_pred = call_chat_api(prompt, args.api_key, args.model, args.base_url, timeout_sec=args.timeout)
                    repair_used = True
                    repaired += 1
                except Exception as e:
                    repair_error = str(e)

            ex_out = {
                **ex,
                "pred_before": pred,
                "pred": new_pred,
                "repair_used": repair_used,
                "repair_model": args.model if repair_used else None,
                "repair_error": repair_error,
            }
            fout.write(json.dumps(ex_out, ensure_ascii=False) + "\n")
            time.sleep(args.sleep)

    print(f"[OK] repaired {repaired}/{total} (only when pred not executable)")
    print(f"[OK] wrote: {args.out}")


if __name__ == "__main__":
    main()