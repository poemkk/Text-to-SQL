import argparse
import json
from pathlib import Path


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in_file", type=str, required=True)
    parser.add_argument("--out", type=str, required=True)
    parser.add_argument(
        "--code_field",
        type=str,
        default="final_code",
        choices=["initial_code", "final_code"],
    )
    args = parser.parse_args()

    rows = read_jsonl(args.in_file)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps({
                "task_id": row["task_id"],
                "solution": row.get(args.code_field) or "",
            }, ensure_ascii=False) + "\n")

    print(f"[OK] exported {len(rows)} samples")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
