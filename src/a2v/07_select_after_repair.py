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
    Build a selectable pool from:
    1. original candidates
    2. repaired candidates if repair was attempted
    """
    pool = []

    for cand in candidates:
        # Original candidate
        pool.append({
            "source": cand.get("source"),
            "variant": "original",
            "sql": cand.get("sql"),
            "exec_ok": cand.get("exec_ok", False),
            "exec_correct": cand.get("exec_correct", False),
            "exec_error": cand.get("exec_error"),
            "result": cand.get("result"),
            "latency_ms": cand.get("latency_ms"),
        })

        # Repaired candidate
        if cand.get("repair_attempted"):
            pool.append({
                "source": cand.get("source"),
                "variant": "repair",
                "sql": cand.get("repair_sql"),
                "exec_ok": cand.get("repair_exec_ok", False),
                "exec_correct": cand.get("repair_exec_correct", False),
                "exec_error": cand.get("repair_exec_error"),
                "result": cand.get("repair_result"),
                "latency_ms": cand.get("repair_latency_ms"),
            })

    return pool


def select_candidate(pool):
    """
    Rule-based selector after repair:
    1. Prefer executable candidates.
    2. Prefer original candidates over repaired candidates.
    3. Prefer source priority:
       embedrag > bm25rag > lora_rag > loraonly_ep3 > promptonly.
    4. If no executable candidate exists, fall back to source priority.
    """

    executable = [c for c in pool if c.get("exec_ok")]
    selectable = executable if executable else pool

    selected = sorted(
        selectable,
        key=lambda c: (
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
        default="runs/outputs/a2v/repaired_spider100.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/selected_after_repair_spider100.jsonl",
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

            item["selected_after_repair"] = selected
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

            if item["selected_variant"] == "repair":
                selected_repair_count += 1

            out.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"[OK] selected examples: {total}")
    print(f"[OK] selected executable: {selected_exec_ok}/{total} = {selected_exec_ok / total:.3f}")
    print(f"[OK] selected correct: {selected_exec_correct}/{total} = {selected_exec_correct / total:.3f}")
    print(f"[OK] selected repaired variant: {selected_repair_count}/{total}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
