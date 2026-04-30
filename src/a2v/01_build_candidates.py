import argparse
import json
from pathlib import Path


DEFAULT_SOURCES = {
    "promptonly": "runs/outputs/pred_dev1034_promptonly_20260120_080337.jsonl",
    "bm25rag": "runs/outputs/pred_dev1034_bm25rag_20260120_080337.jsonl",
    "embedrag": "runs/outputs/pred_dev1034_embedrag_20260120_080337.jsonl",
    "loraonly_ep3": "runs/outputs/pred_dev1034_loraonly_ep3_20260120_143003.jsonl",
    "lora_rag": "runs/outputs/pred_dev1034_lora_all8659_egs_aggrrepair_20260120_175500.jsonl",
}


def read_jsonl(path):
    rows = []
    path = Path(path)
    if not path.exists():
        print(f"[WARN] missing file: {path}")
        return rows

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/candidates_spider100.jsonl",
    )
    args = parser.parse_args()

    all_sources = {}
    for name, path in DEFAULT_SOURCES.items():
        rows = read_jsonl(path)
        if rows:
            all_sources[name] = rows
            print(f"[OK] loaded {name}: {len(rows)} rows")

    if not all_sources:
        raise RuntimeError("No prediction files loaded.")

    first_source_name = next(iter(all_sources))
    base_rows = all_sources[first_source_name]
    n = min(args.limit, len(base_rows))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0

    with out_path.open("w", encoding="utf-8") as out:
        for i in range(n):
            base = base_rows[i]

            item = {
                "idx": i,
                "db_id": base.get("db_id"),
                "question": base.get("question"),
                "gold": base.get("gold"),
                "candidates": [],
            }

            for source_name, rows in all_sources.items():
                if i >= len(rows):
                    continue

                row = rows[i]

                candidate = {
                    "source": source_name,
                    "sql": row.get("pred"),
                    "error": row.get("error"),
                    "model": row.get("model"),
                }

                item["candidates"].append(candidate)

            out.write(json.dumps(item, ensure_ascii=False) + "\n")
            written += 1

    print(f"[OK] wrote {written} examples to {out_path}")


if __name__ == "__main__":
    main()
