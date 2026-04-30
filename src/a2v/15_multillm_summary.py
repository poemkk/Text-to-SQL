import argparse
import json
from collections import defaultdict
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--in_file",
        type=str,
        default="runs/outputs/a2v/multillm/scored_multillm_spider1034.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/multillm/summary_multillm_spider1034.md",
    )
    args = parser.parse_args()

    rows = read_jsonl(args.in_file)

    total_examples = len(rows)
    source_stats = defaultdict(lambda: {
        "total": 0,
        "exec_ok": 0,
        "correct": 0,
        "gen_latencies": [],
        "exec_latencies": [],
    })

    oracle_exec = 0
    oracle_correct = 0

    total_candidates = 0
    candidate_exec = 0
    candidate_correct = 0

    for item in rows:
        has_exec = False
        has_correct = False

        for cand in item.get("candidates", []):
            source = cand.get("source", "unknown")
            source_stats[source]["total"] += 1
            total_candidates += 1

            if cand.get("exec_ok"):
                source_stats[source]["exec_ok"] += 1
                candidate_exec += 1
                has_exec = True

            if cand.get("exec_correct"):
                source_stats[source]["correct"] += 1
                candidate_correct += 1
                has_correct = True

            if cand.get("latency_ms_generation") is not None:
                source_stats[source]["gen_latencies"].append(cand.get("latency_ms_generation"))

            if cand.get("latency_ms") is not None:
                source_stats[source]["exec_latencies"].append(cand.get("latency_ms"))

        if has_exec:
            oracle_exec += 1

        if has_correct:
            oracle_correct += 1

    summary_rows = []

    for source, s in sorted(source_stats.items()):
        avg_gen = sum(s["gen_latencies"]) / len(s["gen_latencies"]) if s["gen_latencies"] else 0.0
        avg_exec = sum(s["exec_latencies"]) / len(s["exec_latencies"]) if s["exec_latencies"] else 0.0

        summary_rows.append({
            "setting": source,
            "examples": s["total"],
            "candidates_per_question": 1,
            "executable_rate": rate(s["exec_ok"], s["total"]),
            "execution_accuracy": rate(s["correct"], s["total"]),
            "avg_generation_latency_ms": avg_gen,
            "avg_execution_latency_ms": avg_exec,
        })

    summary_rows.append({
        "setting": "multi_llm_candidate_level",
        "examples": total_examples,
        "candidates_per_question": total_candidates / total_examples if total_examples else 0,
        "executable_rate": rate(candidate_exec, total_candidates),
        "execution_accuracy": rate(candidate_correct, total_candidates),
        "avg_generation_latency_ms": 0.0,
        "avg_execution_latency_ms": 0.0,
    })

    summary_rows.append({
        "setting": "multi_llm_oracle",
        "examples": total_examples,
        "candidates_per_question": total_candidates / total_examples if total_examples else 0,
        "executable_rate": rate(oracle_exec, total_examples),
        "execution_accuracy": rate(oracle_correct, total_examples),
        "avg_generation_latency_ms": 0.0,
        "avg_execution_latency_ms": 0.0,
    })

    lines = []
    lines.append("# Multi-LLM Spider1034 Summary")
    lines.append("")
    lines.append("| Setting | Examples | Candidates / Question | Executable Rate | Execution Accuracy | Avg Generation Latency ms | Avg Execution Latency ms |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")

    for r in summary_rows:
        lines.append(
            f"| {r['setting']} | "
            f"{r['examples']} | "
            f"{r['candidates_per_question']:.1f} | "
            f"{r['executable_rate']:.3f} | "
            f"{r['execution_accuracy']:.3f} | "
            f"{r['avg_generation_latency_ms']:.1f} | "
            f"{r['avg_execution_latency_ms']:.3f} |"
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\n[OK] wrote summary to {out_path}")


if __name__ == "__main__":
    main()
