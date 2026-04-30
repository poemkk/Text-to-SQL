import json
from pathlib import Path


path = Path("runs/outputs/a2v/scored_spider100.jsonl")

total_examples = 0
examples_with_any_exec = 0
examples_with_any_correct = 0

source_stats = {}

with path.open("r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue

        item = json.loads(line)
        total_examples += 1

        any_exec = False
        any_correct = False

        for cand in item["candidates"]:
            source = cand["source"]

            if source not in source_stats:
                source_stats[source] = {
                    "total": 0,
                    "exec_ok": 0,
                    "exec_correct": 0,
                }

            source_stats[source]["total"] += 1

            if cand.get("exec_ok"):
                source_stats[source]["exec_ok"] += 1
                any_exec = True

            if cand.get("exec_correct"):
                source_stats[source]["exec_correct"] += 1
                any_correct = True

        if any_exec:
            examples_with_any_exec += 1

        if any_correct:
            examples_with_any_correct += 1


print("=== A2V scored summary ===")
print(f"total examples: {total_examples}")
print(f"examples with at least one executable candidate: {examples_with_any_exec}")
print(f"candidate-set executable coverage: {examples_with_any_exec / total_examples:.3f}")
print(f"examples with at least one correct candidate: {examples_with_any_correct}")
print(f"candidate-set oracle accuracy: {examples_with_any_correct / total_examples:.3f}")

print("\n=== By source ===")
for source, stat in source_stats.items():
    exec_rate = stat["exec_ok"] / stat["total"] if stat["total"] else 0
    acc = stat["exec_correct"] / stat["total"] if stat["total"] else 0
    print(
        f"{source}: "
        f"exec={stat['exec_ok']}/{stat['total']}={exec_rate:.3f}, "
        f"acc={stat['exec_correct']}/{stat['total']}={acc:.3f}"
    )
