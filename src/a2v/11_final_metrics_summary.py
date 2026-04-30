import argparse
import json
from pathlib import Path


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        print(f"[WARN] file not found: {path}")
        return []

    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def safe_rate(num, den):
    return num / den if den else 0.0


def fmt(x):
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def candidate_set_metrics(scored_rows):
    total = len(scored_rows)
    any_exec = 0
    any_correct = 0

    total_candidates = 0
    executable_candidates = 0
    correct_candidates = 0

    latencies = []

    for item in scored_rows:
        candidates = item.get("candidates", [])
        total_candidates += len(candidates)

        item_any_exec = False
        item_any_correct = False

        for cand in candidates:
            if cand.get("exec_ok"):
                executable_candidates += 1
                item_any_exec = True

            if cand.get("exec_correct"):
                correct_candidates += 1
                item_any_correct = True

            if cand.get("latency_ms") is not None:
                latencies.append(cand.get("latency_ms"))

        if item_any_exec:
            any_exec += 1
        if item_any_correct:
            any_correct += 1

    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    return {
        "examples": total,
        "total_candidates": total_candidates,
        "candidate_level_executable_rate": safe_rate(executable_candidates, total_candidates),
        "candidate_level_execution_accuracy": safe_rate(correct_candidates, total_candidates),
        "candidate_set_executable_coverage": safe_rate(any_exec, total),
        "candidate_set_oracle_accuracy": safe_rate(any_correct, total),
        "avg_candidate_latency_ms": avg_latency,
    }


def selected_metrics(selected_rows, label="selected"):
    total = len(selected_rows)
    exec_ok = 0
    correct = 0
    selected_repair = 0
    latencies = []

    for item in selected_rows:
        if item.get("selected_exec_ok"):
            exec_ok += 1

        if item.get("selected_exec_correct"):
            correct += 1

        variant = item.get("selected_variant")
        if variant in ("repair", "strong_repair"):
            selected_repair += 1

        selected = (
            item.get("selected")
            or item.get("selected_after_repair")
            or item.get("selected_after_strong_repair")
            or item.get("selected_after_strong_repair_practical")
        )

        if isinstance(selected, dict) and selected.get("latency_ms") is not None:
            latencies.append(selected.get("latency_ms"))

    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    return {
        "label": label,
        "examples": total,
        "executable_rate": safe_rate(exec_ok, total),
        "execution_accuracy": safe_rate(correct, total),
        "selected_repair_ratio": safe_rate(selected_repair, total),
        "selected_repair_count": selected_repair,
        "avg_selected_latency_ms": avg_latency,
    }


def source_metrics(scored_rows):
    stats = {}

    for item in scored_rows:
        for cand in item.get("candidates", []):
            source = cand.get("source", "unknown")

            if source not in stats:
                stats[source] = {
                    "total": 0,
                    "exec_ok": 0,
                    "correct": 0,
                    "latencies": [],
                }

            stats[source]["total"] += 1

            if cand.get("exec_ok"):
                stats[source]["exec_ok"] += 1

            if cand.get("exec_correct"):
                stats[source]["correct"] += 1

            if cand.get("latency_ms") is not None:
                stats[source]["latencies"].append(cand.get("latency_ms"))

    results = []

    for source, s in stats.items():
        total = s["total"]
        avg_latency = (
            sum(s["latencies"]) / len(s["latencies"])
            if s["latencies"]
            else 0.0
        )

        results.append({
            "method": source,
            "examples": total,
            "executable_rate": safe_rate(s["exec_ok"], total),
            "execution_accuracy": safe_rate(s["correct"], total),
            "avg_latency_ms": avg_latency,
        })

    return sorted(results, key=lambda x: x["method"])


def strong_repair_metrics(repaired_rows):
    attempted_candidates = 0
    repair_api_calls = 0
    repair_exec_ok = 0
    repair_correct = 0
    repair_rounds_total = 0

    for item in repaired_rows:
        for cand in item.get("candidates", []):
            if cand.get("strong_repair_attempted"):
                attempted_candidates += 1

                rounds = cand.get("strong_repair_rounds", [])
                repair_api_calls += len(rounds)
                repair_rounds_total += len(rounds)

                if cand.get("strong_repair_exec_ok"):
                    repair_exec_ok += 1

                if cand.get("strong_repair_exec_correct"):
                    repair_correct += 1

    return {
        "repair_attempted_candidates": attempted_candidates,
        "repair_api_calls": repair_api_calls,
        "repair_executable_success_rate": safe_rate(repair_exec_ok, attempted_candidates),
        "repair_correct_success_rate": safe_rate(repair_correct, attempted_candidates),
        "avg_repair_rounds_per_candidate": safe_rate(repair_rounds_total, attempted_candidates),
    }


def weak_repair_metrics(repaired_rows):
    attempted = 0
    repair_exec_ok = 0
    repair_correct = 0

    for item in repaired_rows:
        for cand in item.get("candidates", []):
            if cand.get("repair_attempted"):
                attempted += 1

                if cand.get("repair_exec_ok"):
                    repair_exec_ok += 1

                if cand.get("repair_exec_correct"):
                    repair_correct += 1

    return {
        "repair_attempted_candidates": attempted,
        "repair_executable_success_rate": safe_rate(repair_exec_ok, attempted),
        "repair_correct_success_rate": safe_rate(repair_correct, attempted),
    }


def crossdb_metrics(rows):
    total = len(rows)
    sqlite_exec = 0
    duckdb_exec = 0
    crossdb_portable = 0
    crossdb_same_result = 0
    dialect_attempted = 0
    dialect_exec_ok = 0
    dialect_same = 0

    duckdb_latencies = []
    dialect_latencies = []

    for item in rows:
        if item.get("selected_exec_ok"):
            sqlite_exec += 1

        if item.get("duckdb_exec_ok"):
            duckdb_exec += 1

        if item.get("crossdb_portable"):
            crossdb_portable += 1

        if item.get("crossdb_same_result"):
            crossdb_same_result += 1

        if item.get("duckdb_latency_ms") is not None:
            duckdb_latencies.append(item.get("duckdb_latency_ms"))

        if item.get("dialect_repair_attempted"):
            dialect_attempted += 1

            if item.get("dialect_repair_exec_ok"):
                dialect_exec_ok += 1

            if item.get("dialect_repair_same_result"):
                dialect_same += 1

            if item.get("dialect_repair_latency_ms") is not None:
                dialect_latencies.append(item.get("dialect_repair_latency_ms"))

    after_duckdb_exec = duckdb_exec + dialect_exec_ok
    after_same_result = crossdb_same_result + dialect_same

    return {
        "examples": total,
        "sqlite_executable_rate": safe_rate(sqlite_exec, total),
        "duckdb_executable_rate_before_repair": safe_rate(duckdb_exec, total),
        "crossdb_portability_before_repair": safe_rate(crossdb_portable, total),
        "crossdb_same_result_before_repair": safe_rate(crossdb_same_result, total),
        "dialect_repair_attempted": dialect_attempted,
        "dialect_repair_executable_success_rate": safe_rate(dialect_exec_ok, dialect_attempted),
        "dialect_repair_same_result_success_rate": safe_rate(dialect_same, dialect_attempted),
        "duckdb_executable_rate_after_repair": safe_rate(after_duckdb_exec, total),
        "crossdb_same_result_after_repair": safe_rate(after_same_result, total),
        "avg_duckdb_latency_ms": safe_rate(sum(duckdb_latencies), len(duckdb_latencies)),
        "avg_dialect_repair_duckdb_latency_ms": safe_rate(sum(dialect_latencies), len(dialect_latencies)),
    }


def write_markdown(path, sections):
    lines = []

    lines.append("# A²V-SQL Final Metrics Summary")
    lines.append("")

    for title, rows in sections:
        lines.append(f"## {title}")
        lines.append("")

        if not rows:
            lines.append("_No data._")
            lines.append("")
            continue

        if isinstance(rows, dict):
            lines.append("| Metric | Value |")
            lines.append("|---|---:|")
            for k, v in rows.items():
                lines.append(f"| {k} | {fmt(v)} |")
            lines.append("")
            continue

        if isinstance(rows, list):
            keys = list(rows[0].keys())
            lines.append("| " + " | ".join(keys) + " |")
            lines.append("|" + "|".join(["---" for _ in keys]) + "|")
            for row in rows:
                lines.append("| " + " | ".join(fmt(row.get(k, "")) for k in keys) + " |")
            lines.append("")

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--scored",
        type=str,
        default="runs/outputs/a2v/scored_spider1034.jsonl",
    )
    parser.add_argument(
        "--selected_priority",
        type=str,
        default="runs/outputs/a2v/selected_spider1034.jsonl",
    )
    parser.add_argument(
        "--selected_vote",
        type=str,
        default="runs/outputs/a2v/selected_vote_spider1034.jsonl",
    )
    parser.add_argument(
        "--selected_strong_practical",
        type=str,
        default="runs/outputs/a2v/selected_after_strong_repair_practical_v2_spider1034_full.jsonl",
    )
    parser.add_argument(
        "--selected_strong_oracle",
        type=str,
        default="runs/outputs/a2v/selected_after_strong_repair_spider1034_full.jsonl",
    )
    parser.add_argument(
        "--strong_repair",
        type=str,
        default="runs/outputs/a2v/repaired_strong_spider1034_full.jsonl",
    )
    parser.add_argument(
        "--weak_repair",
        type=str,
        default="runs/outputs/a2v/repaired_spider100.jsonl",
    )
    parser.add_argument(
        "--crossdb_duckdb",
        type=str,
        default="runs/outputs/a2v/multibackend_duckdb_spider1034_dialect_repaired.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/final_metrics_summary.md",
    )

    args = parser.parse_args()

    scored_rows = read_jsonl(args.scored)
    selected_priority_rows = read_jsonl(args.selected_priority)
    selected_vote_rows = read_jsonl(args.selected_vote)
    selected_strong_practical_rows = read_jsonl(args.selected_strong_practical)
    selected_strong_oracle_rows = read_jsonl(args.selected_strong_oracle)
    strong_repair_rows = read_jsonl(args.strong_repair)
    weak_repair_rows = read_jsonl(args.weak_repair)
    crossdb_rows = read_jsonl(args.crossdb_duckdb)

    candidate_metrics = candidate_set_metrics(scored_rows)
    per_source = source_metrics(scored_rows)

    selected_rows = [
        selected_metrics(selected_priority_rows, "rule_selector_priority"),
        selected_metrics(selected_vote_rows, "rule_selector_vote"),
        selected_metrics(selected_strong_practical_rows, "A2V_full_strong_repair_practical_v2"),
        selected_metrics(selected_strong_oracle_rows, "strong_repair_oracle_upper_bound"),
    ]

    strong_repair = strong_repair_metrics(strong_repair_rows)
    weak_repair = weak_repair_metrics(weak_repair_rows)
    crossdb = crossdb_metrics(crossdb_rows)

    main_table = []

    for row in per_source:
        main_table.append({
            "method": row["method"],
            "examples": row["examples"],
            "executable_rate": row["executable_rate"],
            "execution_accuracy": row["execution_accuracy"],
            "avg_latency_ms": row["avg_latency_ms"],
        })

    main_table.append({
        "method": "candidate_set_oracle",
        "examples": candidate_metrics["examples"],
        "executable_rate": candidate_metrics["candidate_set_executable_coverage"],
        "execution_accuracy": candidate_metrics["candidate_set_oracle_accuracy"],
        "avg_latency_ms": candidate_metrics["avg_candidate_latency_ms"],
    })

    for row in selected_rows:
        main_table.append({
            "method": row["label"],
            "examples": row["examples"],
            "executable_rate": row["executable_rate"],
            "execution_accuracy": row["execution_accuracy"],
            "selected_repair_ratio": row["selected_repair_ratio"],
            "avg_latency_ms": row["avg_selected_latency_ms"],
        })

    sections = [
        ("Main Horizontal Metrics", main_table),
        ("Candidate-set Metrics", candidate_metrics),
        ("Strong Repair Success", strong_repair),
        ("Weak Repair Success Spider100", weak_repair),
        ("Cross-DB Portability DuckDB", crossdb),
    ]

    write_markdown(args.out, sections)

    print("=== Main Horizontal Metrics ===")
    print("| Method | Examples | Executable Rate | Execution Accuracy | Selected Repair Ratio | Avg Latency ms |")
    print("|---|---:|---:|---:|---:|---:|")

    for row in main_table:
        print(
            f"| {row.get('method')} | "
            f"{row.get('examples', '')} | "
            f"{fmt(row.get('executable_rate', 0))} | "
            f"{fmt(row.get('execution_accuracy', 0))} | "
            f"{fmt(row.get('selected_repair_ratio', 0))} | "
            f"{fmt(row.get('avg_latency_ms', 0))} |"
        )

    print("\n=== Strong Repair Success ===")
    for k, v in strong_repair.items():
        print(f"{k}: {fmt(v)}")

    print("\n=== Cross-DB Portability DuckDB ===")
    for k, v in crossdb.items():
        print(f"{k}: {fmt(v)}")

    print(f"\n[OK] wrote final metrics summary to {args.out}")


if __name__ == "__main__":
    main()
