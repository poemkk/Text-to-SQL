import argparse
import json
import random
from collections import Counter, defaultdict
from math import comb
from pathlib import Path


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def rate(num, den):
    return num / den if den else 0.0


def selected_correct(row):
    return bool(row.get("selected_exec_correct"))


def selected_exec_ok(row):
    return bool(row.get("selected_exec_ok"))


def count_by(rows, field):
    return dict(sorted(Counter(row.get(field, "unknown") for row in rows).items()))


def correct_by(rows, field):
    stats = defaultdict(int)
    for row in rows:
        if selected_correct(row):
            stats[row.get(field, "unknown")] += 1
    return dict(sorted(stats.items()))


def mcnemar_exact(old_vals, new_vals):
    n01 = sum((not old) and new for old, new in zip(old_vals, new_vals))
    n10 = sum(old and (not new) for old, new in zip(old_vals, new_vals))
    discordant = n01 + n10
    if discordant == 0:
        return n01, n10, 1.0

    tail = min(n01, n10)
    cumulative = sum(comb(discordant, k) for k in range(tail + 1))
    p_value = min(1.0, 2.0 * cumulative / (2 ** discordant))
    return n01, n10, p_value


def bootstrap_ci(diff_values, n_boot=10000, seed=42):
    rng = random.Random(seed)
    n = len(diff_values)
    if n == 0:
        return 0.0, 0.0

    means = []
    for _ in range(n_boot):
        total = 0
        for _ in range(n):
            total += diff_values[rng.randrange(n)]
        means.append(total / n)

    means.sort()
    lo_idx = int(0.025 * n_boot)
    hi_idx = int(0.975 * n_boot)
    return means[lo_idx], means[min(hi_idx, n_boot - 1)]


def align_by_idx(old_rows, new_rows):
    old_by_idx = {row.get("idx"): row for row in old_rows}
    new_by_idx = {row.get("idx"): row for row in new_rows}
    shared = sorted(set(old_by_idx) & set(new_by_idx))
    if len(shared) != len(old_rows) or len(shared) != len(new_rows):
        raise ValueError(
            f"old/new files are not aligned by idx: "
            f"old={len(old_rows)} new={len(new_rows)} shared={len(shared)}"
        )
    return [old_by_idx[idx] for idx in shared], [new_by_idx[idx] for idx in shared]


def print_selector_metrics(rows):
    total = len(rows)
    exec_ok = sum(1 for row in rows if selected_exec_ok(row))
    correct = sum(1 for row in rows if selected_correct(row))

    print(f"examples: {total}")
    print(f"selected_exec_rate: {rate(exec_ok, total):.4f}")
    print(f"selected_execution_accuracy: {rate(correct, total):.4f}")
    print(
        "selected_source_count: "
        + json.dumps(count_by(rows, "selected_source"), ensure_ascii=False)
    )
    print(
        "selected_source_correct: "
        + json.dumps(correct_by(rows, "selected_source"), ensure_ascii=False)
    )
    print(
        "selected_variant_count: "
        + json.dumps(count_by(rows, "selected_variant"), ensure_ascii=False)
    )
    print(
        "selected_variant_correct: "
        + json.dumps(correct_by(rows, "selected_variant"), ensure_ascii=False)
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--new",
        default="runs/outputs/a2v/selected_after_strong_repair_scored_v3_spider1034_full.jsonl",
    )
    parser.add_argument(
        "--old",
        default="runs/outputs/a2v/selected_after_strong_repair_practical_v2_spider1034_full.jsonl",
    )
    parser.add_argument("--bootstrap", type=int, default=10000)
    args = parser.parse_args()

    new_rows = read_jsonl(args.new)
    old_rows = read_jsonl(args.old)
    old_rows, new_rows = align_by_idx(old_rows, new_rows)

    print("=== New Selector Metrics ===")
    print_selector_metrics(new_rows)

    old_vals = [selected_correct(row) for row in old_rows]
    new_vals = [selected_correct(row) for row in new_rows]

    old_acc = rate(sum(old_vals), len(old_vals))
    new_acc = rate(sum(new_vals), len(new_vals))
    diff = new_acc - old_acc
    n01, n10, p_value = mcnemar_exact(old_vals, new_vals)
    diff_values = [
        (1 if new else 0) - (1 if old else 0)
        for old, new in zip(old_vals, new_vals)
    ]
    ci_low, ci_high = bootstrap_ci(diff_values, n_boot=args.bootstrap)

    print("\n=== Paired Comparison vs Practical v2 ===")
    print(f"old_acc: {old_acc:.4f}")
    print(f"new_acc: {new_acc:.4f}")
    print(f"diff: {diff:.4f}")
    print(f"McNemar n01 old_wrong_new_right: {n01}")
    print(f"McNemar n10 old_right_new_wrong: {n10}")
    print(f"p-value: {p_value:.6f}")
    print(f"CI: [{ci_low:.4f}, {ci_high:.4f}]")


if __name__ == "__main__":
    main()
