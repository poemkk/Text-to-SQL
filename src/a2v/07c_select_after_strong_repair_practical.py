import argparse
import json
from collections import defaultdict
from pathlib import Path


SOURCE_PRIORITY = {
    "embedrag": 1,
    "bm25rag": 2,
    "lora_rag": 3,
    "loraonly_ep3": 4,
    "promptonly": 5,
}


VARIANT_PRIORITY = {
    "original": 1,
    "strong_repair": 2,
}


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def is_non_empty_result(result):
    return result not in (None, [])


def normalize_result_key(result):
    """
    Convert execution result into a stable key for result-consistency grouping.
    This does NOT use gold result.
    """
    if result is None:
        return "NULL_RESULT"

    normalized_rows = []
    for row in result:
        normalized_rows.append(tuple(str(x) for x in row))

    normalized_rows = sorted(normalized_rows)
    return json.dumps(normalized_rows, ensure_ascii=False, sort_keys=True)


def build_pool(candidates):
    """
    Build selectable pool from original candidates and strong repair candidates.
    exec_correct is kept only for final offline evaluation, not used by selector.
    """
    pool = []

    for cand in candidates:
        source = cand.get("source")

        pool.append({
            "source": source,
            "variant": "original",
            "sql": cand.get("sql"),
            "exec_ok": cand.get("exec_ok", False),
            "exec_correct": cand.get("exec_correct", False),
            "exec_error": cand.get("exec_error"),
            "result": cand.get("result"),
            "latency_ms": cand.get("latency_ms"),
            "result_key": normalize_result_key(cand.get("result")),
        })

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
                "result_key": normalize_result_key(cand.get("strong_repair_result")),
            })

    return pool


def result_consistency_score(candidate, groups):
    """
    Number of executable candidates that produced the same result.
    A higher score means the result is supported by more candidates.
    """
    key = candidate.get("result_key")
    return len(groups.get(key, []))


def source_score(candidate):
    return SOURCE_PRIORITY.get(candidate.get("source"), 999)


def variant_score(candidate):
    return VARIANT_PRIORITY.get(candidate.get("variant"), 999)


def select_candidate_practical(pool):
    """
    Improved practical selector after strong repair.
    Does NOT use gold result or exec_correct.

    Rules:
    1. Prefer executable candidates.
    2. Prefer candidates whose execution result is supported by more candidates.
    3. Prefer non-empty result.
    4. Prefer stronger source priority.
    5. Prefer original over repair only as a later tie-breaker.
    6. Prefer lower latency if available.

    The key change compared with the previous practical selector:
    repair candidates can be selected if their result is consistent with other candidates.
    """

    executable = [c for c in pool if c.get("exec_ok")]

    if not executable:
        return sorted(
            pool,
            key=lambda c: (
                source_score(c),
                variant_score(c),
            )
        )[0]

    groups = defaultdict(list)
    for cand in executable:
        groups[cand["result_key"]].append(cand)

    selected = sorted(
        executable,
        key=lambda c: (
            -result_consistency_score(c, groups),
            0 if is_non_empty_result(c.get("result")) else 1,
            source_score(c),
            variant_score(c),
            c.get("latency_ms") if c.get("latency_ms") is not None else 999999,
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
        default="runs/outputs/a2v/selected_after_strong_repair_practical_spider1034_full.jsonl",
    )
    args = parser.parse_args()

    rows = read_jsonl(args.in_file)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    selected_exec_ok = 0
    selected_exec_correct = 0
    selected_repair_count = 0

    selected_by_source = {}
    selected_by_variant = {}

    with out_path.open("w", encoding="utf-8") as out:
        for item in rows:
            pool = build_pool(item["candidates"])
            selected = select_candidate_practical(pool)

            item["selected_after_strong_repair_practical"] = selected
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

            selected_by_source[item["selected_source"]] = selected_by_source.get(item["selected_source"], 0) + 1
            selected_by_variant[item["selected_variant"]] = selected_by_variant.get(item["selected_variant"], 0) + 1

            out.write(json.dumps(item, ensure_ascii=False) + "\n")

    print("=== Improved Practical Strong Repair Selector Summary ===")
    print(f"selected examples: {total}")
    print(f"selected executable: {selected_exec_ok}/{total} = {selected_exec_ok / total:.3f}")
    print(f"selected correct: {selected_exec_correct}/{total} = {selected_exec_correct / total:.3f}")
    print(f"selected strong repair variant: {selected_repair_count}/{total}")

    print("\nSelected by source:")
    for source, count in sorted(selected_by_source.items(), key=lambda x: x[0]):
        print(f"{source}: {count}")

    print("\nSelected by variant:")
    for variant, count in sorted(selected_by_variant.items(), key=lambda x: x[0]):
        print(f"{variant}: {count}")

    print(f"\n[OK] output: {out_path}")


if __name__ == "__main__":
    main()