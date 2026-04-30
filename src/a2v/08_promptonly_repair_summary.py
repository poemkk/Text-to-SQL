import json
from pathlib import Path


PATH = Path("runs/outputs/a2v/repaired_spider100.jsonl")


total = 0

before_exec_ok = 0
before_correct = 0

after_exec_ok = 0
after_correct = 0

repair_attempted = 0
repair_exec_ok = 0
repair_correct = 0


with PATH.open("r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue

        item = json.loads(line)

        prompt_cand = None
        for cand in item["candidates"]:
            if cand.get("source") == "promptonly":
                prompt_cand = cand
                break

        if prompt_cand is None:
            continue

        total += 1

        # before repair
        if prompt_cand.get("exec_ok"):
            before_exec_ok += 1
        if prompt_cand.get("exec_correct"):
            before_correct += 1

        # after repair:
        # if original is executable, keep original;
        # if original failed and repair succeeded, use repaired SQL.
        final_exec_ok = prompt_cand.get("exec_ok", False)
        final_correct = prompt_cand.get("exec_correct", False)

        if prompt_cand.get("repair_attempted"):
            repair_attempted += 1

            if prompt_cand.get("repair_exec_ok"):
                repair_exec_ok += 1
                final_exec_ok = True

            if prompt_cand.get("repair_exec_correct"):
                repair_correct += 1
                final_correct = True

        if final_exec_ok:
            after_exec_ok += 1
        if final_correct:
            after_correct += 1


print("=== Prompt-only Repair Summary ===")
print(f"total examples: {total}")

print("\nBefore repair:")
print(f"Executable Rate: {before_exec_ok}/{total} = {before_exec_ok / total:.3f}")
print(f"Execution Accuracy: {before_correct}/{total} = {before_correct / total:.3f}")

print("\nRepair module:")
print(f"repair attempted: {repair_attempted}")
print(f"repair executable: {repair_exec_ok}/{repair_attempted} = {repair_exec_ok / repair_attempted:.3f}")
print(f"repair correct: {repair_correct}/{repair_attempted} = {repair_correct / repair_attempted:.3f}")

print("\nAfter repair:")
print(f"Executable Rate: {after_exec_ok}/{total} = {after_exec_ok / total:.3f}")
print(f"Execution Accuracy: {after_correct}/{total} = {after_correct / total:.3f}")
