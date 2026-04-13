#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
from typing import Dict, Iterable, List

from src.spider.load_spider import iter_spider_samples

PROMPT_LORAONLY = """You are a Text-to-SQL system.
Write ONE valid SQLite SQL query.

Rules:
- Output SQL ONLY. One statement.
- The SQL must start with SELECT or WITH and end with a semicolon.
- Do NOT output explanations, code, or markdown.

Question:
{question}

SQL:
"""

def build_example_loraonly(ex: Dict) -> Dict:
    q = (ex.get("question") or "").strip()
    tgt = (ex.get("query") or "").strip()

    # normalize target to end with semicolon
    if tgt and not tgt.endswith(";"):
        tgt += ";"

    src = PROMPT_LORAONLY.format(question=q)

    return {
        "input_text": src,
        "target_text": tgt,
        "db_id": ex.get("db_id", ""),
    }

def iter_multi_json(paths: List[str]) -> Iterable[Dict]:
    for p in paths:
        for ex in iter_spider_samples(p):
            yield ex

def dump_jsonl(rows: List[Dict], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train_spider_json", default="data/spider/train_spider.json")
    ap.add_argument("--train_others_json", default="data/spider/train_others.json")
    ap.add_argument("--dev_json", default="data/spider/dev.json")

    ap.add_argument("--train_out", default="runs/cache/loraonly_train_all8659.jsonl")
    ap.add_argument("--dev_out", default="runs/cache/loraonly_dev_1034.jsonl")

    ap.add_argument("--train_limit", type=int, default=0, help="0 means no limit")
    ap.add_argument("--dev_limit", type=int, default=0, help="0 means no limit")

    args = ap.parse_args()

    # ---- train (train_spider + train_others) ----
    train_paths = [args.train_spider_json, args.train_others_json]
    train_rows: List[Dict] = []
    n = 0
    for ex in iter_multi_json(train_paths):
        train_rows.append(build_example_loraonly(ex))
        n += 1
        if args.train_limit and n >= args.train_limit:
            break

    dump_jsonl(train_rows, args.train_out)
    print(f"[OK] wrote {len(train_rows)} to {args.train_out}")

    # ---- dev ----
    dev_rows: List[Dict] = []
    n = 0
    for ex in iter_spider_samples(args.dev_json):
        dev_rows.append(build_example_loraonly(ex))
        n += 1
        if args.dev_limit and n >= args.dev_limit:
            break

    dump_jsonl(dev_rows, args.dev_out)
    print(f"[OK] wrote {len(dev_rows)} to {args.dev_out}")

if __name__ == "__main__":
    main()