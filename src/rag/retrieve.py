#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import math
import os
import re
from collections import defaultdict
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


def load_jsonl_map(path: str, key_field: str) -> Dict[str, Any]:
    m = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            m[obj[key_field]] = obj
    return m


def load_postings(path: str) -> Dict[str, List[Tuple[int, int]]]:
    post = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            # postings list is [ [doc_idx, tf], ... ]
            post[obj["t"]] = [(int(a), int(b)) for a, b in obj["p"]]
    return post


def load_doc_store(path: str) -> List[Dict[str, Any]]:
    docs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            docs.append(json.loads(line))
    return docs


def bm25_score(query_toks: List[str],
               postings: Dict[str, List[Tuple[int, int]]],
               idf: Dict[str, float],
               doc_len: List[int],
               avgdl: float,
               k1: float,
               b: float) -> Dict[int, float]:
    scores = defaultdict(float)
    for t in query_toks:
        plist = postings.get(t)
        if not plist:
            continue
        idf_t = idf.get(t, 0.0)
        for doc_idx, tf in plist:
            dl = doc_len[doc_idx]
            denom = tf + k1 * (1 - b + b * dl / (avgdl + 1e-9))
            scores[doc_idx] += idf_t * (tf * (k1 + 1)) / (denom + 1e-9)
    return scores


def retrieve_schema_context(index_dir: str, question: str, db_id: str,
                            topk_table: int = 5, topk_col: int = 8, topk_fk: int = 8) -> str:
    """
    Returns a text block for prompting: tables + columns + foreign keys.
    Strategy:
      1) BM25 retrieve within db_id
      2) keep top tables + columns
      3) add FK chunks that touch any selected table
    """
    # load index (reuse your existing loaders in retrieve.py)
    doc_store = load_doc_store(os.path.join(index_dir, "doc_store.jsonl"))
    meta = json.load(open(os.path.join(index_dir, "doc_len.json"), "r", encoding="utf-8"))
    doc_len = meta["doc_len"]; avgdl = float(meta["avgdl"])
    k1 = float(meta["k1"]); b = float(meta["b"])
    idf_map = load_jsonl_map(os.path.join(index_dir, "idf.jsonl"), "t")
    idf = {k: float(v["idf"]) for k, v in idf_map.items()}
    postings = load_postings(os.path.join(index_dir, "postings.jsonl"))

    q_toks = tokenize(question)
    scores = bm25_score(q_toks, postings, idf, doc_len, avgdl, k1, b)

    # collect candidates in this db
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    cand = []
    for doc_idx, sc in ranked:
        d = doc_store[doc_idx]
        if d["db_id"] != db_id:
            continue
        cand.append((sc, d))
        if len(cand) >= 200:
            break

    tables, cols, fks = [], [], []
    touched_tables = set()

    for sc, d in cand:
        if d["type"] == "table" and len(tables) < topk_table:
            tables.append(d)
            touched_tables.add(d["meta"]["table"])
        elif d["type"] == "column" and len(cols) < topk_col:
            cols.append(d)
            touched_tables.add(d["meta"]["table"])

        if len(tables) >= topk_table and len(cols) >= topk_col:
            break

    # add FK chunks that connect selected tables
    for sc, d in cand:
        if d["type"] != "fk":
            continue
        fr = d["meta"]["from"].split(".")[0]
        to = d["meta"]["to"].split(".")[0]
        if fr in touched_tables or to in touched_tables:
            fks.append(d)
        if len(fks) >= topk_fk:
            break

    def pack(title: str, items):
        if not items:
            return f"{title}\n(EMPTY)\n"
        return title + "\n" + "\n\n".join([x["text"] for x in items]) + "\n"

    context = (
        pack("=== TABLES (Top) ===", tables) +
        pack("=== COLUMNS (Top) ===", cols) +
        pack("=== FOREIGN KEYS / JOIN HINTS ===", fks)
    )
    return context

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True, help="bm25 index dir")
    ap.add_argument("--q", required=True, help="query text")
    ap.add_argument("--db_id", default="", help="optional db_id filter")
    ap.add_argument("--topk", type=int, default=10)
    args = ap.parse_args()

    doc_store = load_doc_store(os.path.join(args.index, "doc_store.jsonl"))
    meta = json.load(open(os.path.join(args.index, "doc_len.json"), "r", encoding="utf-8"))
    doc_len = meta["doc_len"]
    avgdl = float(meta["avgdl"])
    k1 = float(meta["k1"])
    b = float(meta["b"])

    idf_map = load_jsonl_map(os.path.join(args.index, "idf.jsonl"), "t")
    idf = {k: float(v["idf"]) for k, v in idf_map.items()}
    postings = load_postings(os.path.join(args.index, "postings.jsonl"))

    q_toks = tokenize(args.q)
    scores = bm25_score(q_toks, postings, idf, doc_len, avgdl, k1, b)

    # rank
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    out = []
    for doc_idx, sc in ranked:
        d = doc_store[doc_idx]
        if args.db_id and d["db_id"] != args.db_id:
            continue
        out.append((doc_idx, sc, d))
        if len(out) >= args.topk:
            break

    for i, (doc_idx, sc, d) in enumerate(out, 1):
        print(f"--- #{i} score={sc:.4f} {d['doc_id']} ({d['type']})")
        print(d["text"])
        print()

    print(f"[OK] returned {len(out)} docs (db_id filter='{args.db_id}')")


if __name__ == "__main__":
    main()