import json
from pathlib import Path


path = Path("runs/outputs/a2v/validated_spider100.jsonl")

total_examples = 0
examples_with_any_exec = 0
examples_all_failed = 0

source_stats = {}

with path.open("r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue

        item = json.loads(line)
        total_examples += 1

        any_exec = False

        for cand in item["candidates"]:
            source = cand["source"]

            if source not in source_stats:
                source_stats[source] = {
                    "total": 0,
                    "exec_ok": 0,
                }

            source_stats[source]["total"] += 1

            if cand.get("exec_ok"):
                source_stats[source]["exec_ok"] += 1
                any_exec = True

        if any_exec:
            examples_with_any_exec += 1
        else:
            examples_all_failed += 1


print("=== A2V validated summary ===")
print(f"total examples: {total_examples}")
print(f"examples with at least one executable candidate: {examples_with_any_exec}")
print(f"examples all failed: {examples_all_failed}")
print(f"candidate-set executable coverage: {examples_with_any_exec / total_examples:.3f}")

print("\n=== By source ===")
for source, stat in source_stats.items():
    rate = stat["exec_ok"] / stat["total"] if stat["total"] else 0
    print(f"{source}: {stat['exec_ok']}/{stat['total']} = {rate:.3f}")
