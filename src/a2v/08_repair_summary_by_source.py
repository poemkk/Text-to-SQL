import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--in_file",
        type=str,
        default="runs/outputs/a2v/repaired_spider100.jsonl",
    )
    parser.add_argument(
        "--source",
        type=str,
        required=True,
        help="candidate source, e.g. promptonly, bm25rag, embedrag, loraonly_ep3, lora_rag",
    )
    args = parser.parse_args()

    path = Path(args.in_file)
    source_name = args.source

    total = 0

    before_exec_ok = 0
    before_correct = 0

    after_exec_ok = 0
    after_correct = 0

    repair_attempted = 0
    repair_exec_ok = 0
    repair_correct = 0

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            item = json.loads(line)

            target_cand = None
            for cand in item["candidates"]:
                if cand.get("source") == source_name:
                    target_cand = cand
                    break

            if target_cand is None:
                continue

            total += 1

            # before repair
            if target_cand.get("exec_ok"):
                before_exec_ok += 1
            if target_cand.get("exec_correct"):
                before_correct += 1

            # after repair:
            # if original is executable, keep original;
            # if original failed and repair succeeded, use repaired SQL.
            final_exec_ok = target_cand.get("exec_ok", False)
            final_correct = target_cand.get("exec_correct", False)

            if target_cand.get("repair_attempted"):
                repair_attempted += 1

                if target_cand.get("repair_exec_ok"):
                    repair_exec_ok += 1
                    final_exec_ok = True

                if target_cand.get("repair_exec_correct"):
                    repair_correct += 1
                    final_correct = True

            if final_exec_ok:
                after_exec_ok += 1
            if final_correct:
                after_correct += 1

    print(f"=== Repair Summary: {source_name} ===")
    print(f"total examples: {total}")

    print("\nBefore repair:")
    print(f"Executable Rate: {before_exec_ok}/{total} = {before_exec_ok / total:.3f}")
    print(f"Execution Accuracy: {before_correct}/{total} = {before_correct / total:.3f}")

    print("\nRepair module:")
    print(f"repair attempted: {repair_attempted}")

    if repair_attempted > 0:
        print(f"repair executable: {repair_exec_ok}/{repair_attempted} = {repair_exec_ok / repair_attempted:.3f}")
        print(f"repair correct: {repair_correct}/{repair_attempted} = {repair_correct / repair_attempted:.3f}")
    else:
        print("repair executable: 0/0 = N/A")
        print("repair correct: 0/0 = N/A")

    print("\nAfter repair:")
    print(f"Executable Rate: {after_exec_ok}/{total} = {after_exec_ok / total:.3f}")
    print(f"Execution Accuracy: {after_correct}/{total} = {after_correct / total:.3f}")


if __name__ == "__main__":
    main()
