#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from typing import Any, Dict, List


def load_spider_json(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_spider_samples(path: str):
    data = load_spider_json(path)
    for ex in data:
        yield {
            "question": ex.get("question", ""),
            "query": ex.get("query", ""),
            "db_id": ex.get("db_id", ""),
            "question_toks": ex.get("question_toks", []),
            "query_toks": ex.get("query_toks", []),
        }