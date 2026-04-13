#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, json, os
import numpy as np

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="runs/cache/spider_schema_docs.jsonl")
    ap.add_argument("--out", default="runs/cache/embed_schema")
    ap.add_argument("--model", default="intfloat/e5-small-v2")
    ap.add_argument("--batch_size", type=int, default=64)
    args = ap.parse_args()

    try:
        from sentence_transformers import SentenceTransformer
    except Exception as e:
        raise SystemExit(
            "Missing dependency: sentence-transformers\n"
            "Install: pip3 install -U sentence-transformers\n"
            f"Import error: {e}"
        )

    os.makedirs(args.out, exist_ok=True)

    docs = []
    with open(args.docs, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                docs.append(json.loads(line))

    texts = [d["text"] for d in docs]

    model = SentenceTransformer(args.model)
    # e5 习惯加前缀（更稳）
    emb = model.encode([f"passage: {t}" for t in texts],
                       batch_size=args.batch_size,
                       normalize_embeddings=True,
                       show_progress_bar=True)
    emb = np.asarray(emb, dtype=np.float32)

    np.save(os.path.join(args.out, "emb.npy"), emb)

    with open(os.path.join(args.out, "docs.jsonl"), "w", encoding="utf-8") as w:
        for d in docs:
            w.write(json.dumps(d, ensure_ascii=False) + "\n")

    meta = {
        "model": args.model,
        "n_docs": len(docs),
        "dim": int(emb.shape[1]),
        "docs_path": args.docs,
    }
    with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as w:
        json.dump(meta, w, ensure_ascii=False, indent=2)

    print("[OK] wrote:", args.out, "docs=", len(docs), "dim=", emb.shape[1])

if __name__ == "__main__":
    main()