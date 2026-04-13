#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import re
from typing import Dict

import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from peft import PeftModel

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


def pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def extract_sql(text: str) -> str:
    t = (text or "").strip()

    # find first SELECT/WITH
    m = re.search(r"\b(SELECT|WITH)\b", t, flags=re.IGNORECASE)
    if m:
        t = t[m.start():].strip()

    # keep only first statement
    if ";" in t:
        t = t.split(";", 1)[0].strip() + ";"

    # if still no semicolon, add it if it looks like sql
    if t and not t.endswith(";"):
        t += ";"
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev_json", default="data/spider/dev.json")
    ap.add_argument("--adapter_dir", required=True)
    ap.add_argument("--base_model", default="google/flan-t5-base")

    ap.add_argument("--out", default="runs/outputs/pred_dev1034_loraonly.jsonl")
    ap.add_argument("--limit", type=int, default=1034)

    ap.add_argument("--max_input_len", type=int, default=256)
    ap.add_argument("--max_new_tokens", type=int, default=128)
    ap.add_argument("--num_beams", type=int, default=4)

    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    device = pick_device()
    print("[INFO] device:", device)

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

            prompt = PROMPT_LORAONLY.format(question=ex["question"].strip())
            inp = tok(prompt, return_tensors="pt", truncation=True, max_length=args.max_input_len).to(device)

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
                print(f"[{n}/{args.limit}] pred_len={len(pred)}")

    print("[OK] wrote:", args.out)


if __name__ == "__main__":
    main()