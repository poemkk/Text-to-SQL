import json
from pathlib import Path


SCORED_PATH = Path("runs/outputs/a2v/scored_spider1034.jsonl")
SELECTED_PRIORITY_PATH = Path("runs/outputs/a2v/selected_spider1034.jsonl")
SELECTED_VOTE_PATH = Path("runs/outputs/a2v/selected_vote_spider1034.jsonl")
OUT_PATH = Path("runs/outputs/a2v/summary_spider1034.md")


def read_jsonl(path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def source_metrics(rows):
    stats = {}

    for item in rows:
        for cand in item["candidates"]:
            source = cand["source"]
            if source not in stats:
                stats[source] = {
                    "total": 0,
                    "exec_ok": 0,
                    "exec_correct": 0,
                }

            stats[source]["total"] += 1

            if cand.get("exec_ok"):
                stats[source]["exec_ok"] += 1

            if cand.get("exec_correct"):
                stats[source]["exec_correct"] += 1

    result = []

    for source, s in stats.items():
        total = s["total"]
        result.append({
            "method": source,
            "total": total,
            "exec_rate": s["exec_ok"] / total if total else 0,
            "exec_acc": s["exec_correct"] / total if total else 0,
        })

    return result


def candidate_set_metrics(rows):
    total = len(rows)
    any_exec = 0
    any_correct = 0

    for item in rows:
        if any(c.get("exec_ok") for c in item["candidates"]):
            any_exec += 1
        if any(c.get("exec_correct") for c in item["candidates"]):
            any_correct += 1

    return {
        "method": "candidate_set_oracle",
        "total": total,
        "exec_rate": any_exec / total if total else 0,
        "exec_acc": any_correct / total if total else 0,
    }


def selected_metrics(path, name):
    rows = read_jsonl(path)
    total = len(rows)
    exec_ok = sum(1 for x in rows if x.get("selected_exec_ok"))
    exec_correct = sum(1 for x in rows if x.get("selected_exec_correct"))

    return {
        "method": name,
        "total": total,
        "exec_rate": exec_ok / total if total else 0,
        "exec_acc": exec_correct / total if total else 0,
    }


def main():
    scored_rows = read_jsonl(SCORED_PATH)

    table_rows = []
    table_rows.extend(source_metrics(scored_rows))
    table_rows.append(candidate_set_metrics(scored_rows))
    table_rows.append(selected_metrics(SELECTED_PRIORITY_PATH, "rule_selector_priority"))
    table_rows.append(selected_metrics(SELECTED_VOTE_PATH, "rule_selector_vote"))

    preferred_order = {
        "promptonly": 1,
        "bm25rag": 2,
        "embedrag": 3,
        "loraonly_ep3": 4,
        "lora_rag": 5,
        "candidate_set_oracle": 6,
        "rule_selector_priority": 7,
        "rule_selector_vote": 8,
    }

    table_rows = sorted(
        table_rows,
        key=lambda x: preferred_order.get(x["method"], 999)
    )

    lines = []
    lines.append("# A²V-SQL Spider1034 Summary")
    lines.append("")
    lines.append("| Method / Setting | Examples | Executable Rate | Execution Accuracy |")
    lines.append("|---|---:|---:|---:|")

    for row in table_rows:
        lines.append(
            f"| {row['method']} | {row['total']} | "
            f"{row['exec_rate']:.3f} | {row['exec_acc']:.3f} |"
        )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\n[OK] wrote summary to {OUT_PATH}")


if __name__ == "__main__":
    main()
