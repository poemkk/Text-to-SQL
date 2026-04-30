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


def select_candidate(candidates):
    """
    Rule-based selector:
    1. Prefer executable candidates.
    2. Among executable candidates, prefer source priority:
       embedrag > bm25rag > lora_rag > loraonly_ep3 > promptonly.
    3. If no candidate is executable, choose by source priority anyway.
    """

    executable = [c for c in candidates if c.get("exec_ok")]

    pool = executable if executable else candidates

    selected = sorted(
        pool,
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
        default="runs/outputs/a2v/selected_spider100.jsonl",
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
            selected = select_candidate(item["candidates"])

            item["selected"] = selected
            item["selected_source"] = selected.get("source")
            item["selected_sql"] = selected.get("sql")
            item["selected_exec_ok"] = selected.get("exec_ok", False)
            item["selected_exec_correct"] = selected.get("exec_correct", False)

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
