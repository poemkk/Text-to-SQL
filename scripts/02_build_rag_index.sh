#!/usr/bin/env bash
set -euo pipefail

# 1) schema docs
python3 src/spider/schema_docs.py \
  --tables data/spider/tables.json \
  --out runs/cache/spider_schema_docs.jsonl

# 2) bm25 index
python3 src/rag/build_bm25.py \
  --docs runs/cache/spider_schema_docs.jsonl \
  --out runs/cache/bm25_schema

echo "Preview docs:"
head -n 1 runs/cache/spider_schema_docs.jsonl

echo "Index files:"
ls runs/cache/bm25_schema | sed -n '1,20p'