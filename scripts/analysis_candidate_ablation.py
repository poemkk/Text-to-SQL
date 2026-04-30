import json
from pathlib import Path

path = Path("runs/outputs/a2v/scored_spider1034.jsonl")
rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]

sources = ["promptonly", "bm25rag", "embedrag", "loraonly_ep3", "lora_rag"]

def get(row, source):
    for c in row["candidates"]:
        if c["source"] == source:
            return c
    raise KeyError(source)

def eval_subset(subset):
    n = len(rows)
    exec_cov = 0
    oracle_acc = 0
    cand_total = 0
    cand_exec = 0
    cand_correct = 0

    for r in rows:
        cs = [get(r, s) for s in subset]
        cand_total += len(cs)
        cand_exec += sum(1 for c in cs if c.get("exec_ok"))
        cand_correct += sum(1 for c in cs if c.get("exec_correct"))
        if any(c.get("exec_ok") for c in cs):
            exec_cov += 1
        if any(c.get("exec_correct") for c in cs):
            oracle_acc += 1

    return {
        "subset": "+".join(subset),
        "num_candidates": len(subset),
        "candidate_exec_rate": cand_exec / cand_total,
        "candidate_acc": cand_correct / cand_total,
        "exec_coverage": exec_cov / n,
        "oracle_acc": oracle_acc / n,
    }

subsets = [
    ["embedrag"],
    ["bm25rag", "embedrag"],
    ["embedrag", "lora_rag"],
    ["bm25rag", "embedrag", "lora_rag"],
    ["promptonly", "bm25rag", "embedrag"],
    ["bm25rag", "embedrag", "loraonly_ep3", "lora_rag"],
    ["promptonly", "bm25rag", "embedrag", "loraonly_ep3", "lora_rag"],
]

print("| Candidate subset | #cand/q | Cand Exec | Cand Acc | Exec Coverage | Oracle Acc |")
print("|---|---:|---:|---:|---:|---:|")
for sub in subsets:
    r = eval_subset(sub)
    print(
        f"| {r['subset']} | {r['num_candidates']} | "
        f"{r['candidate_exec_rate']:.3f} | {r['candidate_acc']:.3f} | "
        f"{r['exec_coverage']:.3f} | {r['oracle_acc']:.3f} |"
    )

print("\n## Unique correct contribution")
for s in sources:
    unique = 0
    correct = 0
    for r in rows:
        c = get(r, s)
        if c.get("exec_correct"):
            correct += 1
            others = [get(r, o) for o in sources if o != s]
            if not any(o.get("exec_correct") for o in others):
                unique += 1
    print(f"{s}: correct={correct}, unique_correct={unique}")
