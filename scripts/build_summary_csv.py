import csv
import json
from pathlib import Path

# 改成你的真实目录
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "runs" / "outputs"

FILES = [
    ("BM25 Schema-RAG", "eval_dev1034_bm25rag_20260120_080337.json"),
    ("Embedding Schema-RAG", "eval_dev1034_embedrag_20260120_080337.json"),
    ("LoRA + RAG", "eval_dev1034_lora_all8659_egs_aggrrepair_20260120_175500.json"),
    ("LoRA-only (epoch1)", "eval_dev1034_loraonly_ep1_20260120_111133.json"),
    ("LoRA-only (epoch3)", "eval_dev1034_loraonly_ep3_20260120_143003.json"),
    ("Prompt-only", "eval_dev1034_promptonly_20260120_080337.json"),
]


def load_metrics(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    m = data["metrics"]

    return m["total"], m["pred_exec_rate"], m["exec_acc"]


def main():

    rows = []

    for name, file in FILES:

        path = OUT_DIR / file

        if not path.exists():
            print(f"[WARN] file not found: {path}")
            continue

        total, exec_rate, exec_acc = load_metrics(path)

        rows.append({
            "setting": name,
            "n": total,
            "exec_rate": round(exec_rate, 3),
            "exec_acc": round(exec_acc, 3)
        })

    out_csv = OUT_DIR / "summary.csv"

    out_csv.parent.mkdir(parents=True, exist_ok=True)

    with open(out_csv, "w", newline="", encoding="utf-8") as f:

        writer = csv.DictWriter(
            f,
            fieldnames=["setting", "n", "exec_rate", "exec_acc"]
        )

        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ summary written to {out_csv}")


if __name__ == "__main__":
    main()