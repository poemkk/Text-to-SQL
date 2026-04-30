import argparse
import json
from pathlib import Path


SOURCE_PRIORITY = {
    "embedrag": 1,
    "bm25rag": 2,
    "lora_rag": 3,
    "loraonly_ep3": 4,
    "promptonly": 5,
}


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def build_pool(candidates):
    """
    Build selectable pool from:
    1. original candidates
    2. strong repair candidates
    """
    pool = []

    for cand in candidates:
        source = cand.get("source")

        # Original candidate
        pool.append({
            "source": source,
            "variant": "original",
            "sql": cand.get("sql"),
            "exec_ok": cand.get("exec_ok", False),
            "exec_correct": cand.get("exec_correct", False),
            "exec_error": cand.get("exec_error"),
            "result": cand.get("result"),
            "latency_ms": cand.get("latency_ms"),
        })

        # Strong repair candidate
        if cand.get("strong_repair_attempted"):
            pool.append({
                "source": source,
                "variant": "strong_repair",
                "sql": cand.get("strong_repair_final_sql"),
                "exec_ok": cand.get("strong_repair_exec_ok", False),
                "exec_correct": cand.get("strong_repair_exec_correct", False),
                "exec_error": cand.get("strong_repair_exec_error"),
                "result": cand.get("strong_repair_result"),
                "latency_ms": None,
            })

    return pool


def select_candidate(pool):
    """
    Strong selector:
    1. Prefer executable candidates.
    2. Prefer candidates marked exec_correct if available in offline evaluation.
       This is an oracle-style selector for analysis.
    3. Prefer original over repair if both are correct.
    4. Prefer source priority:
       embedrag > bm25rag > lora_rag > loraonly_ep3 > promptonly.
    """

    executable = [c for c in pool if c.get("exec_ok")]
    selectable = executable if executable else pool

    selected = sorted(
        selectable,
        key=lambda c: (
            0 if c.get("exec_correct") else 1,
            0 if c.get("variant") == "original" else 1,
            SOURCE_PRIORITY.get(c.get("source"), 999),
        )
    )[0]

    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--in_file",
        type=str,
        default="runs/outputs/a2v/repaired_strong_spider1034_full.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/selected_after_strong_repair_spider1034_full.jsonl",
    )
    args = parser.parse_args()

    rows = read_jsonl(args.in_file)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    selected_exec_ok = 0
    selected_exec_correct = 0
    selected_repair_count = 0

    with out_path.open("w", encoding="utf-8") as out:
        for item in rows:
            pool = build_pool(item["candidates"])
            selected = select_candidate(pool)

            item["selected_after_strong_repair"] = selected
            item["selected_source"] = selected.get("source")
            item["selected_variant"] = selected.get("variant")
            item["selected_sql"] = selected.get("sql")
            item["selected_exec_ok"] = selected.get("exec_ok", False)
            item["selected_exec_correct"] = selected.get("exec_correct", False)

            total += 1

            if item["selected_exec_ok"]:
                selected_exec_ok += 1

            if item["selected_exec_correct"]:
                selected_exec_correct += 1

            if item["selected_variant"] == "strong_repair":
                selected_repair_count += 1

            out.write(json.dumps(item, ensure_ascii=False) + "\n")

    print("=== Strong Repair Selector Summary ===")
    print(f"selected examples: {total}")
    print(f"selected executable: {selected_exec_ok}/{total} = {selected_exec_ok / total:.3f}")
    print(f"selected correct: {selected_exec_correct}/{total} = {selected_exec_correct / total:.3f}")
    print(f"selected strong repair variant: {selected_repair_count}/{total}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
