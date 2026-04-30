import json
import math
import random
from pathlib import Path

def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def get_candidate_correct(row, source):
    for c in row["candidates"]:
        if c.get("source") == source:
            return bool(c.get("exec_correct"))
    raise KeyError(source)

def load_selected(path, key="selected_exec_correct"):
    vals = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                vals.append(bool(row.get(key)))
    return vals

def mcnemar(a, b):
    n01 = sum((not x) and y for x, y in zip(a, b))
    n10 = sum(x and (not y) for x, y in zip(a, b))
    if n01 + n10 == 0:
        chi2 = 0.0
    else:
        chi2 = (abs(n01 - n10) - 1) ** 2 / (n01 + n10)
    p = math.erfc(math.sqrt(chi2 / 2))
    return n01, n10, chi2, p

def bootstrap_ci(diff_values, n_boot=10000, seed=42):
    random.seed(seed)
    n = len(diff_values)
    means = []
    for _ in range(n_boot):
        s = 0
        for _ in range(n):
            s += diff_values[random.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot)]
    return lo, hi

def report_pair(name, a, b):
    acc_a = sum(a) / len(a)
    acc_b = sum(b) / len(b)
    diff = acc_b - acc_a
    n01, n10, chi2, p = mcnemar(a, b)
    diffs = [(1 if y else 0) - (1 if x else 0) for x, y in zip(a, b)]
    lo, hi = bootstrap_ci(diffs)
    print(f"\n## {name}")
    print(f"baseline_acc = {acc_a:.4f}")
    print(f"new_acc      = {acc_b:.4f}")
    print(f"diff         = {diff:.4f}")
    print(f"McNemar n01 baseline_wrong_new_right = {n01}")
    print(f"McNemar n10 baseline_right_new_wrong = {n10}")
    print(f"McNemar chi2 = {chi2:.4f}")
    print(f"McNemar p    = {p:.6f}")
    print(f"Bootstrap 95% CI for diff = [{lo:.4f}, {hi:.4f}]")

rows = load_jsonl("runs/outputs/a2v/scored_spider1034.jsonl")

embed = [get_candidate_correct(r, "embedrag") for r in rows]
bm25 = [get_candidate_correct(r, "bm25rag") for r in rows]
prompt = [get_candidate_correct(r, "promptonly") for r in rows]
lora = [get_candidate_correct(r, "loraonly_ep3") for r in rows]
lora_rag = [get_candidate_correct(r, "lora_rag") for r in rows]

priority = load_selected("runs/outputs/a2v/selected_spider1034.jsonl")
vote = load_selected("runs/outputs/a2v/selected_vote_spider1034.jsonl")

strong = load_selected(
    "runs/outputs/a2v/selected_after_strong_repair_practical_v2_spider1034_full.jsonl",
    key="selected_exec_correct"
)

report_pair("BM25-RAG vs Embedding-RAG", bm25, embed)
report_pair("Embedding-RAG vs Rule selector priority", embed, priority)
report_pair("Embedding-RAG vs Rule selector vote", embed, vote)
report_pair("Rule selector priority vs A2V strong repair practical v2", priority, strong)
report_pair("Embedding-RAG vs A2V strong repair practical v2", embed, strong)
report_pair("Prompt-only vs Embedding-RAG", prompt, embed)
report_pair("LoRA-only vs LoRA+RAG", lora, lora_rag)
