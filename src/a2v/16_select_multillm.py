import argparse
import json
from collections import defaultdict
from pathlib import Path


MODEL_PRIORITY = {
    "gemini-3.1-flash-lite-preview": 1,
    "grok-4-fast": 2,
    "gpt-5.4-mini": 3,
    "claude-haiku-4-5-20251001": 4,
}


BEST_MODEL = "gemini-3.1-flash-lite-preview"


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def is_non_empty_result(result):
    return result not in (None, [])


def normalize_result_key(result):
    if result is None:
        return "NULL_RESULT"

    normalized_rows = []
    for row in result:
        normalized_rows.append(tuple(str(x) for x in row))

    normalized_rows = sorted(normalized_rows)
    return json.dumps(normalized_rows, ensure_ascii=False, sort_keys=True)


def model_score(candidate):
    return MODEL_PRIORITY.get(candidate.get("source"), 999)


def enrich_candidates(candidates):
    pool = []

    for cand in candidates:
        c = dict(cand)
        c["result_key"] = normalize_result_key(cand.get("result"))
        c["non_empty"] = is_non_empty_result(cand.get("result"))
        pool.append(c)

    return pool


def group_by_result(executable):
    groups = defaultdict(list)

    for cand in executable:
        groups[cand["result_key"]].append(cand)

    return groups


def result_group_size(candidate, groups):
    return len(groups.get(candidate.get("result_key"), []))


def select_best_model(candidates):
    """
    Gemini baseline.
    Does not use gold.
    """
    pool = enrich_candidates(candidates)

    best = [c for c in pool if c.get("source") == BEST_MODEL]
    if best:
        return best[0]

    executable = [c for c in pool if c.get("exec_ok")]
    if executable:
        return sorted(executable, key=lambda c: model_score(c))[0]

    return sorted(pool, key=lambda c: model_score(c))[0]


def select_consensus_first(candidates):
    """
    Previous style selector:
    prefer executable, then result consistency, then non-empty, then model priority.
    Does not use gold.
    """
    pool = enrich_candidates(candidates)
    executable = [c for c in pool if c.get("exec_ok")]

    if not executable:
        return sorted(pool, key=lambda c: model_score(c))[0]

    groups = group_by_result(executable)

    selected = sorted(
        executable,
        key=lambda c: (
            -result_group_size(c, groups),
            0 if c.get("non_empty") else 1,
            model_score(c),
            c.get("latency_ms_generation") if c.get("latency_ms_generation") is not None else 999999,
        ),
    )[0]

    return selected


def select_conservative_switch(candidates):
    """
    Improved practical selector.

    Main idea:
    - Gemini is the strongest single model, so use it as default.
    - Switch away from Gemini only when there is a strong reason:
      1. Gemini is not executable.
      2. Gemini returns an empty result while another executable candidate returns non-empty.
      3. At least two non-Gemini models agree on the same non-empty result and Gemini is alone.
      4. Three or more models agree on a result.

    This selector does NOT use gold / exec_correct.
    """
    pool = enrich_candidates(candidates)
    executable = [c for c in pool if c.get("exec_ok")]

    gemini_list = [c for c in pool if c.get("source") == BEST_MODEL]
    gemini = gemini_list[0] if gemini_list else None

    if not executable:
        return gemini if gemini is not None else sorted(pool, key=lambda c: model_score(c))[0]

    groups = group_by_result(executable)

    # If Gemini is missing or not executable, fall back to best consensus.
    if gemini is None or not gemini.get("exec_ok"):
        return sorted(
            executable,
            key=lambda c: (
                -result_group_size(c, groups),
                0 if c.get("non_empty") else 1,
                model_score(c),
            ),
        )[0]

    gemini_group_size = result_group_size(gemini, groups)

    # If Gemini result has support from another model and is non-empty, keep it.
    if gemini_group_size >= 2 and gemini.get("non_empty"):
        return gemini

    # Strong majority: any result supported by 3 or more executable candidates.
    majority_candidates = [
        c for c in executable
        if result_group_size(c, groups) >= 3 and c.get("non_empty")
    ]
    if majority_candidates:
        return sorted(
            majority_candidates,
            key=lambda c: (
                -result_group_size(c, groups),
                model_score(c),
            ),
        )[0]

    # If Gemini result is empty, prefer a non-empty executable candidate.
    if not gemini.get("non_empty"):
        non_empty_candidates = [c for c in executable if c.get("non_empty")]
        if non_empty_candidates:
            return sorted(
                non_empty_candidates,
                key=lambda c: (
                    -result_group_size(c, groups),
                    model_score(c),
                ),
            )[0]

    # If two non-Gemini models agree on the same non-empty result,
    # and Gemini is alone, switch to that consensus.
    non_gemini_consensus = []
    for c in executable:
        if c.get("source") == BEST_MODEL:
            continue
        if not c.get("non_empty"):
            continue

        group = groups.get(c["result_key"], [])
        non_gemini_count = sum(1 for x in group if x.get("source") != BEST_MODEL)

        if non_gemini_count >= 2 and gemini_group_size == 1:
            non_gemini_consensus.append(c)

    if non_gemini_consensus:
        return sorted(
            non_gemini_consensus,
            key=lambda c: (
                -result_group_size(c, groups),
                model_score(c),
            ),
        )[0]

    # Otherwise keep Gemini.
    return gemini


def select_oracle(candidates):
    """
    Oracle upper bound.
    Uses exec_correct only for analysis.
    """
    pool = enrich_candidates(candidates)

    correct = [c for c in pool if c.get("exec_correct")]
    if correct:
        return sorted(correct, key=lambda c: model_score(c))[0]

    executable = [c for c in pool if c.get("exec_ok")]
    if executable:
        return sorted(executable, key=lambda c: model_score(c))[0]

    return sorted(pool, key=lambda c: model_score(c))[0]


def summarize(rows, key):
    total = len(rows)
    exec_ok = 0
    correct = 0
    by_source = defaultdict(int)
    gen_latencies = []

    for item in rows:
        selected = item[key]

        if selected.get("exec_ok"):
            exec_ok += 1

        if selected.get("exec_correct"):
            correct += 1

        by_source[selected.get("source")] += 1

        if selected.get("latency_ms_generation") is not None:
            gen_latencies.append(selected.get("latency_ms_generation"))

    return {
        "examples": total,
        "exec_rate": exec_ok / total if total else 0.0,
        "acc": correct / total if total else 0.0,
        "avg_generation_latency_ms": sum(gen_latencies) / len(gen_latencies) if gen_latencies else 0.0,
        "by_source": dict(by_source),
    }


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
        default="runs/outputs/a2v/multillm/selected_multillm_spider1034_v2.jsonl",
    )
    parser.add_argument(
        "--summary_out",
        type=str,
        default="runs/outputs/a2v/multillm/summary_multillm_selector_spider1034_v2.md",
    )
    args = parser.parse_args()

    rows = read_jsonl(args.in_file)

    selected_rows = []

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as out:
        for item in rows:
            candidates = item.get("candidates", [])

            gemini_baseline = select_best_model(candidates)
            consensus_first = select_consensus_first(candidates)
            conservative_switch = select_conservative_switch(candidates)
            oracle = select_oracle(candidates)

            item["selected_gemini_baseline"] = gemini_baseline
            item["selected_consensus_first"] = consensus_first
            item["selected_conservative_switch"] = conservative_switch
            item["selected_oracle"] = oracle

            out.write(json.dumps(item, ensure_ascii=False) + "\n")
            selected_rows.append(item)

    summaries = {
        "gemini_baseline": summarize(selected_rows, "selected_gemini_baseline"),
        "consensus_first": summarize(selected_rows, "selected_consensus_first"),
        "conservative_switch": summarize(selected_rows, "selected_conservative_switch"),
        "oracle": summarize(selected_rows, "selected_oracle"),
    }

    lines = []
    lines.append("# Multi-LLM Selector Summary v2")
    lines.append("")
    lines.append("| Selector | Examples | Executable Rate | Execution Accuracy | Avg Generation Latency ms |")
    lines.append("|---|---:|---:|---:|---:|")

    for name, s in summaries.items():
        lines.append(
            f"| {name} | {s['examples']} | "
            f"{s['exec_rate']:.3f} | "
            f"{s['acc']:.3f} | "
            f"{s['avg_generation_latency_ms']:.1f} |"
        )

    for name, s in summaries.items():
        lines.append("")
        lines.append(f"## Selected by source: {name}")
        lines.append("")
        lines.append("| Source | Count |")
        lines.append("|---|---:|")

        for source, count in sorted(s["by_source"].items()):
            lines.append(f"| {source} | {count} |")

    summary_path = Path(args.summary_out)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\n[OK] output: {out_path}")
    print(f"[OK] summary: {summary_path}")


if __name__ == "__main__":
    main()