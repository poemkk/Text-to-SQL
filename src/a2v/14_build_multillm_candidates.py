import argparse
import json
from pathlib import Path


DEFAULT_MODELS = [
    "gpt-5.4-mini",
    "gemini-3.1-flash-lite-preview",
    "grok-4-fast",
    "claude-haiku-4-5-20251001",
]


def model_to_filename(model):
    return model.replace("/", "_").replace(":", "_").replace(" ", "_")


def read_jsonl(path):
    rows = []
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pred_dir",
        type=str,
        default="runs/outputs/a2v/multillm",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1034,
    )
    parser.add_argument(
        "--models",
        type=str,
        default=",".join(DEFAULT_MODELS),
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
    )
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    pred_dir = Path(args.pred_dir)

    all_by_model = {}

    for model in models:
        safe_model = model_to_filename(model)
        path = pred_dir / f"pred_spider{args.limit}_{safe_model}.jsonl"

        rows = read_jsonl(path)

        if len(rows) != args.limit:
            print(f"[WARN] {model}: expected {args.limit}, got {len(rows)}")

        all_by_model[model] = rows
        print(f"[OK] loaded {model}: {len(rows)} rows")

    out_path = (
        Path(args.out)
        if args.out
        else pred_dir / f"candidates_multillm_spider{args.limit}.jsonl"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = min(args.limit, *(len(all_by_model[m]) for m in models))

    with out_path.open("w", encoding="utf-8") as out:
        for idx in range(total):
            base = all_by_model[models[0]][idx]

            item = {
                "idx": idx,
                "db_id": base["db_id"],
                "question": base["question"],
                "gold": base["gold"],
                "candidates": [],
            }

            for model in models:
                row = all_by_model[model][idx]

                item["candidates"].append({
                    "source": model,
                    "sql": row.get("pred"),
                    "error": row.get("error"),
                    "model": row.get("model"),
                    "latency_ms_generation": row.get("latency_ms"),
                    "attempts": row.get("attempts"),
                    "raw_response": row.get("raw_response"),
                })

            out.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"[OK] wrote candidates: {total}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
