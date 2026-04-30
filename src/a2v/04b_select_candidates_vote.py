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


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def normalize_result_for_key(result):
    """
    Convert SQL execution result into a stable comparable key.
    """
    if result is None:
        return "NULL_RESULT"

    normalized_rows = []
    for row in result:
        normalized_rows.append(tuple(str(x) for x in row))

    normalized_rows = sorted(normalized_rows)

    return json.dumps(normalized_rows, ensure_ascii=False, sort_keys=True)


def select_candidate_vote(candidates):
    """
    Result-consistency selector:
    1. Only consider executable candidates.
    2. Group candidates by execution result.
    3. Select the largest result group.
    4. Inside that group, select by source priority.
    5. If no executable candidate exists, fall back to source priority.
    """

    executable = [c for c in candidates if c.get("exec_ok")]

    if not executable:
        return sorted(
            candidates,
            key=lambda c: SOURCE_PRIORITY.get(c.get("source"), 999)
        )[0]

    groups = defaultdict(list)

    for cand in executable:
        key = normalize_result_for_key(cand.get("result"))
        groups[key].append(cand)

    # choose the result group with most candidates
    best_group = sorted(
        groups.values(),
        key=lambda group: (
            -len(group),
            min(SOURCE_PRIORITY.get(c.get("source"), 999) for c in group)
        )
    )[0]

    selected = sorted(
        best_group,
        key=lambda c: SOURCE_PRIORITY.get(c.get("source"), 999)
    )[0]

    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--in_file",
        type=str,
        default="runs/outputs/a2v/scored_spider100.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/selected_vote_spider100.jsonl",
    )
    args = parser.parse_args()

    rows = read_jsonl(args.in_file)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    selected_exec_ok = 0
    selected_exec_correct = 0

    with out_path.open("w", encoding="utf-8") as out:
        for item in rows:
            selected = select_candidate_vote(item["candidates"])

            item["selected"] = selected
            item["selected_source"] = selected.get("source")
            item["selected_sql"] = selected.get("sql")
            item["selected_exec_ok"] = selected.get("exec_ok", False)
            item["selected_exec_correct"] = selected.get("exec_correct", False)
            item["selector_type"] = "result_consistency_vote"

            total += 1

            if item["selected_exec_ok"]:
                selected_exec_ok += 1

            if item["selected_exec_correct"]:
                selected_exec_correct += 1

            out.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"[OK] selected examples: {total}")
    print(f"[OK] selected executable: {selected_exec_ok}/{total} = {selected_exec_ok / total:.3f}")
    print(f"[OK] selected correct: {selected_exec_correct}/{total} = {selected_exec_correct / total:.3f}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
