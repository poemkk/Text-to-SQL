#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, json, os
import numpy as np

def load_index(index_dir: str):
    emb = np.load(os.path.join(index_dir, "emb.npy"))
    docs = []
    with open(os.path.join(index_dir, "docs.jsonl"), "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                docs.append(json.loads(line))
    return emb, docs

def embed_query(q: str, model_name: str):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name)
    v = model.encode([f"query: {q}"], normalize_embeddings=True)
    return np.asarray(v[0], dtype=np.float32)

def retrieve_docs(index_dir: str, q: str, db_id: str, topk: int, model_name: str):
    emb, docs = load_index(index_dir)
    qv = embed_query(q, model_name)

    idx = [i for i, d in enumerate(docs) if d.get("db_id") == db_id]
    if not idx:
        return []

    sub = emb[idx]
    sims = sub @ qv
    top = np.argsort(-sims)[:topk]

    out = []
    for j in top:
        i = idx[int(j)]
        out.append((float(sims[int(j)]), docs[i]))
    return out

def format_as_context(hits):
    lines = []
    for score, d in hits:
        lines.append(f"--- score={score:.4f} {d.get('doc_id','')} ({d.get('type','')})")
        lines.append(d.get("text",""))
        lines.append("")
    return "\n".join(lines).strip()

def retrieve_schema_context_embed(index_dir: str, question: str, db_id: str,
                                  topk_table=5, topk_col=8, topk_fk=8,
                                  model_name="intfloat/e5-small-v2"):
    topk = int(topk_table + topk_col + topk_fk)
    hits = retrieve_docs(index_dir, question, db_id, topk=topk, model_name=model_name)
    return format_as_context(hits)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--db_id", required=True)
    ap.add_argument("--q", required=True)
    ap.add_argument("--topk", type=int, default=10)
    ap.add_argument("--model", default="intfloat/e5-small-v2")
    args = ap.parse_args()

    hits = retrieve_docs(args.index, args.q, args.db_id, args.topk, args.model)
    print(format_as_context(hits))
    print(f"[OK] returned {len(hits)} docs (db_id filter='{args.db_id}')")

if __name__ == "__main__":
    main()
