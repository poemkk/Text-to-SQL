#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
from typing import Any, List, Tuple, Optional, Dict

from src.common.sqlite_exec import run_sqlite_query


def normalize_rows(rows: List[Tuple[Any, ...]]) -> List[Tuple[Any, ...]]:
    """
    Make SQLite results comparable across types.
    Python 3 cannot sort tuples containing mixed types (e.g., int and str),
    so we normalize every cell to a comparable string key: "<type>:<value>".
    """
    def cell_key(x: Any) -> str:
        if x is None:
            return "NULL:"
        if isinstance(x, bytes):
            x = x.decode("utf-8", errors="ignore")
        return f"{type(x).__name__}:{x}"

    norm = []
    for r in rows:
        norm.append(tuple(cell_key(x) for x in r))

    # sort with a stable key (avoid '<' between mixed types)
    return sorted(norm, key=lambda t: "|".join(t))


def load_preds_jsonl(path: str) -> List[Dict[str, Any]]:
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def db_sqlite_path(db_root: str, db_id: str) -> str:
    return os.path.join(db_root, db_id, f"{db_id}.sqlite")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred_jsonl", required=True, help="runs/outputs/*.jsonl with gold/pred")
    ap.add_argument("--db_root", default="data/spider/database", help="Spider database folder")
    ap.add_argument("--out", default="runs/outputs/eval_exec.json")
    ap.add_argument("--timeout", type=float, default=5.0)
    args = ap.parse_args()

    preds = load_preds_jsonl(args.pred_jsonl)

    total = 0
    pred_executable = 0
    gold_executable = 0
    exec_correct = 0

    details = []

    for ex in preds:
        db_id = ex["db_id"]
        print(f"[EVAL {total + 1}/{len(preds)}] db={db_id}")
        gold = (ex.get("gold") or "").strip()
        pred = (ex.get("pred") or "").strip()

        sqlite_path = db_sqlite_path(args.db_root, db_id)

        total += 1

        ok_g, rows_g, err_g = run_sqlite_query(sqlite_path, gold, timeout=args.timeout)
        ok_p, rows_p, err_p = run_sqlite_query(sqlite_path, pred, timeout=args.timeout)

        if ok_g:
            gold_executable += 1
        if ok_p:
            pred_executable += 1

        correct = False
        if ok_g and ok_p:
            # compare result sets
            correct = (normalize_rows(rows_g) == normalize_rows(rows_p))
            if correct:
                exec_correct += 1

        details.append({
            "db_id": db_id,
            "question": ex.get("question", ""),
            "gold": gold,
            "pred": pred,
            "gold_ok": ok_g,
            "pred_ok": ok_p,
            "gold_err": err_g,
            "pred_err": err_p,
            "exec_correct": correct,
        })

    metrics = {
        "total": total,
        "gold_executable": gold_executable,
        "pred_executable": pred_executable,
        "gold_exec_rate": gold_executable / total if total else 0.0,
        "pred_exec_rate": pred_executable / total if total else 0.0,
        "exec_correct": exec_correct,
        "exec_acc": exec_correct / total if total else 0.0,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"metrics": metrics, "details": details}, f, ensure_ascii=False, indent=2)

    print("[OK] Exec evaluation saved to:", args.out)
    print("[METRICS]", metrics)


if __name__ == "__main__":
    main()