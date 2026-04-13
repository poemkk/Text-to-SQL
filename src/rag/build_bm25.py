#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Build a lightweight BM25 index over schema docs (JSONL).
No external deps. Saves:
- vocab (token -> id)
- doc lens
- inverted index postings with tf
- doc metadata (doc_id, db_id, type, text)

This is intentionally simple but good enough for thesis-grade RAG baseline.
"""

import argparse
import json
import math
import os
import re
from collections import Counter, defaultdict
from typing import Dict, List, Tuple, Any


TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+", re.UNICODE)

STOP = set([
    "select","from","where","join","on","and","or","group","by","order","limit","distinct",
    "count","sum","avg","min","max","as","in","like","between","is","null",
    "database","table","columns","column","type","foreignkey","joinhint"
])


def _stem(t: str) -> str:
    # super simple English plural normalization
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("es") and len(t) > 3:
        return t[:-2]
    if t.endswith("s") and len(t) > 3:
        return t[:-1]
    return t

def tokenize(text: str) -> List[str]:
    toks = [t.lower() for t in TOKEN_RE.findall(text)]
    out = []
    for t in toks:
        if t in STOP:
            continue
        if len(t) < 2:
            continue
        out.append(_stem(t))
    return out


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    docs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            docs.append(json.loads(line))
    return docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", required=True, help="schema docs jsonl")
    ap.add_argument("--out", required=True, help="output directory for bm25 index")
    ap.add_argument("--k1", type=float, default=1.2)
    ap.add_argument("--b", type=float, default=0.75)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    docs = read_jsonl(args.docs)

    # store minimal doc store
    doc_store = [{
        "doc_id": d["doc_id"],
        "db_id": d["db_id"],
        "type": d["type"],
        "text": d["text"],
        "meta": d.get("meta", {})
    } for d in docs]

    N = len(doc_store)

    # postings: term -> list of (doc_idx, tf)
    postings: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    df: Counter = Counter()
    doc_len: List[int] = [0] * N

    for i, d in enumerate(doc_store):
        toks = tokenize(d["text"])
        doc_len[i] = len(toks)
        tf = Counter(toks)
        for term, cnt in tf.items():
            postings[term].append((i, int(cnt)))
        for term in tf.keys():
            df[term] += 1

    avgdl = sum(doc_len) / max(1, N)

    # precompute idf
    idf: Dict[str, float] = {}
    for term, dfi in df.items():
        # BM25+ style smoothing
        idf[term] = math.log(1 + (N - dfi + 0.5) / (dfi + 0.5))

    # save index
    with open(os.path.join(args.out, "doc_store.jsonl"), "w", encoding="utf-8") as f:
        for d in doc_store:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    with open(os.path.join(args.out, "doc_len.json"), "w", encoding="utf-8") as f:
        json.dump({"doc_len": doc_len, "avgdl": avgdl, "N": N, "k1": args.k1, "b": args.b}, f)

    # postings & idf
    with open(os.path.join(args.out, "postings.jsonl"), "w", encoding="utf-8") as f:
        for term, plist in postings.items():
            f.write(json.dumps({"t": term, "p": plist}, ensure_ascii=False) + "\n")

    with open(os.path.join(args.out, "idf.jsonl"), "w", encoding="utf-8") as f:
        for term, val in idf.items():
            f.write(json.dumps({"t": term, "idf": val}, ensure_ascii=False) + "\n")

    print(f"[OK] BM25 index built at: {args.out}")
    print(f"[OK] docs={N}, vocab={len(df)}, avgdl={avgdl:.2f}")
    print(f"[OK] example term: {next(iter(df)) if df else 'EMPTY'}")


if __name__ == "__main__":
    main()