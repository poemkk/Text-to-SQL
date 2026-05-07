import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


BACKENDS = {
    "duckdb": {
        "default_path": "runs/outputs/a2v/multibackend_duckdb_spider1034_dialect_repaired.jsonl",
        "raw_sql": "duckdb_sql",
        "raw_exec_ok": "duckdb_exec_ok",
        "raw_same": "crossdb_same_result",
        "raw_result": "duckdb_result",
        "raw_error": "duckdb_exec_error",
        "normalized_sql": "duckdb_after_normalize_sql",
        "normalized_exec_ok": "duckdb_after_normalize_exec_ok",
        "normalized_same": "crossdb_same_result_after_normalize",
        "normalized_result": "duckdb_after_normalize_result",
        "normalized_error": "duckdb_after_normalize_error",
        "normalized_used": "duckdb_after_normalize_used_normalization",
        "repair_sql": "dialect_repair_sql",
        "repair_exec_ok": "dialect_repair_exec_ok",
        "repair_same": "dialect_repair_same_result",
        "repair_result": "dialect_repair_result",
        "repair_error": "dialect_repair_exec_error",
        "repair_attempted": "dialect_repair_attempted",
    },
    "postgres": {
        "default_path": "runs/outputs/a2v/multibackend_postgres_spider1034_dialect_repaired.jsonl",
        "raw_sql": "postgres_sql",
        "raw_exec_ok": "postgres_exec_ok",
        "raw_same": "postgres_crossdb_same_result",
        "raw_result": "postgres_result",
        "raw_error": "postgres_exec_error",
        "normalized_sql": "postgres_after_normalize_sql",
        "normalized_exec_ok": "postgres_after_normalize_exec_ok",
        "normalized_same": "postgres_crossdb_same_result_after_normalize",
        "normalized_result": "postgres_after_normalize_result",
        "normalized_error": "postgres_after_normalize_error",
        "normalized_used": "postgres_after_normalize_used_normalization",
        "repair_sql": "postgres_dialect_repair_sql",
        "repair_exec_ok": "postgres_dialect_repair_exec_ok",
        "repair_same": "postgres_dialect_repair_same_result",
        "repair_result": "postgres_dialect_repair_result",
        "repair_error": "postgres_dialect_repair_error",
        "repair_attempted": "postgres_dialect_repair_attempted",
    },
    "mysql": {
        "default_path": "runs/outputs/a2v/multibackend_mysql_spider1034_dialect_repaired.jsonl",
        "raw_sql": "mysql_sql",
        "raw_exec_ok": "mysql_exec_ok",
        "raw_same": "mysql_crossdb_same_result",
        "raw_result": "mysql_result",
        "raw_error": "mysql_exec_error",
        "normalized_sql": "mysql_after_normalize_sql",
        "normalized_exec_ok": "mysql_after_normalize_exec_ok",
        "normalized_same": "mysql_crossdb_same_result_after_normalize",
        "normalized_result": "mysql_after_normalize_result",
        "normalized_error": "mysql_after_normalize_error",
        "normalized_used": "mysql_after_normalize_used_normalization",
        "repair_sql": "mysql_dialect_repair_sql",
        "repair_exec_ok": "mysql_dialect_repair_exec_ok",
        "repair_same": "mysql_dialect_repair_same_result",
        "repair_result": "mysql_dialect_repair_result",
        "repair_error": "mysql_dialect_repair_error",
        "repair_attempted": "mysql_dialect_repair_attempted",
    },
}


STAGE_RANK = {
    "raw": 3,
    "normalize": 2,
    "llm_repair": 1,
}


def read_jsonl(path):
    rows = []
    path = Path(path)
    if not path.exists():
        print(f"[WARN] missing input: {path}")
        return rows

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    return rows


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def compact_sql(sql):
    if not sql:
        return None
    return re.sub(r"\s+", " ", str(sql).strip()).rstrip(";")


def candidate_key(sql):
    compact = compact_sql(sql)
    if compact is None:
        return None
    return compact.lower()


def normalize_result_for_key(result):
    if result is None:
        return None
    return json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)


def add_candidate(candidates, backend, stage, sql, exec_ok, same_result, result, error):
    key = candidate_key(sql)
    if not key:
        return

    candidates[key]["sql"] = compact_sql(sql)
    candidates[key]["evidence"].append(
        {
            "backend": backend,
            "stage": stage,
            "exec_ok": bool(exec_ok),
            "same_result": bool(same_result),
            "result": result,
            "result_key": normalize_result_for_key(result),
            "error": error,
        }
    )


def collect_backend_candidates(row, backend, cfg):
    candidates = defaultdict(lambda: {"sql": None, "evidence": []})

    add_candidate(
        candidates,
        backend,
        "raw",
        row.get(cfg["raw_sql"]) or row.get("selected_sql"),
        row.get(cfg["raw_exec_ok"]),
        row.get(cfg["raw_same"]),
        row.get(cfg["raw_result"]),
        row.get(cfg["raw_error"]),
    )

    if row.get(cfg["normalized_used"]):
        add_candidate(
            candidates,
            backend,
            "normalize",
            row.get(cfg["normalized_sql"]),
            row.get(cfg["normalized_exec_ok"]),
            row.get(cfg["normalized_same"]),
            row.get(cfg["normalized_result"]),
            row.get(cfg["normalized_error"]),
        )

    if row.get(cfg["repair_attempted"]):
        add_candidate(
            candidates,
            backend,
            "llm_repair",
            row.get(cfg["repair_sql"]),
            row.get(cfg["repair_exec_ok"]),
            row.get(cfg["repair_same"]),
            row.get(cfg["repair_result"]),
            row.get(cfg["repair_error"]),
        )

    return candidates


def merge_candidates(rows_by_backend, idx):
    merged = defaultdict(lambda: {"sql": None, "evidence": []})

    for backend, rows in rows_by_backend.items():
        row = rows.get(idx)
        if not row:
            continue

        for key, cand in collect_backend_candidates(row, backend, BACKENDS[backend]).items():
            merged[key]["sql"] = cand["sql"]
            merged[key]["evidence"].extend(cand["evidence"])

    return merged


def score_candidate(candidate):
    evidence = candidate["evidence"]
    same_backends = {e["backend"] for e in evidence if e["same_result"]}
    exec_backends = {e["backend"] for e in evidence if e["exec_ok"]}
    total_backends = {e["backend"] for e in evidence}
    best_stage_rank = max(STAGE_RANK.get(e["stage"], 0) for e in evidence)

    # Main idea: select by multi-backend agreement first, then executability,
    # then prefer less invasive SQL changes.
    return (
        len(same_backends),
        len(exec_backends),
        len(total_backends),
        best_stage_rank,
        -len(candidate.get("sql") or ""),
    )


def select_candidate(merged):
    if not merged:
        return None

    return max(merged.values(), key=score_candidate)


def summarize_candidate(candidate):
    evidence = candidate["evidence"]
    same_backends = sorted({e["backend"] for e in evidence if e["same_result"]})
    exec_backends = sorted({e["backend"] for e in evidence if e["exec_ok"]})
    stages = Counter(e["stage"] for e in evidence)
    selected_stage = sorted(
        stages.items(),
        key=lambda x: (-x[1], -STAGE_RANK.get(x[0], 0), x[0]),
    )[0][0]

    if same_backends:
        reason = f"same_result on {len(same_backends)} backend(s): {', '.join(same_backends)}"
    elif exec_backends:
        reason = f"executable on {len(exec_backends)} backend(s), but result agreement not proven"
    else:
        reason = "no backend evidence succeeded; kept best available candidate"

    return {
        "sql": candidate["sql"],
        "score": list(score_candidate(candidate)),
        "reason": reason,
        "same_result_backends": same_backends,
        "exec_ok_backends": exec_backends,
        "selected_stage": selected_stage,
        "stage_votes": dict(stages),
        "evidence": evidence,
    }


def choose_base_row(rows_by_backend, idx):
    for backend in ("duckdb", "postgres", "mysql"):
        row = rows_by_backend.get(backend, {}).get(idx)
        if row:
            return row
    return {}


def make_output_row(rows_by_backend, idx):
    base = choose_base_row(rows_by_backend, idx)
    merged = merge_candidates(rows_by_backend, idx)
    selected = select_candidate(merged)

    out = {
        "idx": idx,
        "db_id": base.get("db_id"),
        "question": base.get("question"),
        "gold": base.get("gold"),
        "original_selected_source": base.get("selected_source"),
        "original_selected_sql": base.get("selected_sql"),
        "original_selected_exec_ok": base.get("selected_exec_ok"),
        "original_selected_exec_correct": base.get("selected_exec_correct"),
        "selector_type": "multibackend_evidence_selector_v1",
        "candidate_count": len(merged),
    }

    if selected:
        summary = summarize_candidate(selected)
        selected_record = {
            "source": "multibackend_select",
            "variant": summary["selected_stage"],
            "sql": summary["sql"],
            "exec_ok": bool(summary["exec_ok_backends"]),
            "crossdb_same_result": bool(summary["same_result_backends"]),
            "same_result_backends": summary["same_result_backends"],
            "exec_ok_backends": summary["exec_ok_backends"],
            "score": summary["score"],
            "reason": summary["reason"],
        }
        out.update(
            {
                "selected": selected_record,
                "selected_source": selected_record["source"],
                "selected_variant": selected_record["variant"],
                "selected_sql": selected_record["sql"],
                "selected_exec_ok": selected_record["exec_ok"],
                "selected_crossdb_same_result": selected_record["crossdb_same_result"],
                "final_selected_sql": summary["sql"],
                "final_selected_score": summary["score"],
                "final_selection_reason": summary["reason"],
                "final_selected_stage": summary["selected_stage"],
                "final_same_result_backends": summary["same_result_backends"],
                "final_exec_ok_backends": summary["exec_ok_backends"],
                "final_stage_votes": summary["stage_votes"],
                "final_backend_evidence": summary["evidence"],
                "final_has_same_result": bool(summary["same_result_backends"]),
                "final_has_exec_ok": bool(summary["exec_ok_backends"]),
            }
        )
    else:
        out.update(
            {
                "selected": {
                    "source": "multibackend_select",
                    "variant": "unavailable",
                    "sql": base.get("selected_sql"),
                    "exec_ok": False,
                    "crossdb_same_result": False,
                    "same_result_backends": [],
                    "exec_ok_backends": [],
                    "score": [0, 0, 0, 0, 0],
                    "reason": "no backend candidate rows were available",
                },
                "selected_source": "multibackend_select",
                "selected_variant": "unavailable",
                "selected_sql": base.get("selected_sql"),
                "selected_exec_ok": False,
                "selected_crossdb_same_result": False,
                "final_selected_sql": base.get("selected_sql"),
                "final_selected_score": [0, 0, 0, 0, 0],
                "final_selection_reason": "no backend candidate rows were available",
                "final_selected_stage": "unavailable",
                "final_same_result_backends": [],
                "final_exec_ok_backends": [],
                "final_stage_votes": {},
                "final_backend_evidence": [],
                "final_has_same_result": False,
                "final_has_exec_ok": False,
            }
        )

    return out


def summarize_outputs(rows):
    total = len(rows)
    same = sum(1 for r in rows if r["final_has_same_result"])
    exec_ok = sum(1 for r in rows if r["final_has_exec_ok"])
    all_three_same = sum(1 for r in rows if len(r["final_same_result_backends"]) == 3)
    all_three_exec = sum(1 for r in rows if len(r["final_exec_ok_backends"]) == 3)

    stage_counter = Counter()
    support_counter = Counter()
    for row in rows:
        for stage, count in row["final_stage_votes"].items():
            stage_counter[stage] += count
        support_counter[len(row["final_same_result_backends"])] += 1

    return {
        "total": total,
        "final_has_same_result": same,
        "final_has_exec_ok": exec_ok,
        "final_same_result_rate": same / total if total else 0.0,
        "final_exec_ok_rate": exec_ok / total if total else 0.0,
        "all_three_same_result": all_three_same,
        "all_three_exec_ok": all_three_exec,
        "stage_votes": dict(stage_counter),
        "same_backend_support_distribution": dict(sorted(support_counter.items())),
    }


def write_summary(path, summary):
    lines = [
        "# Multi-backend Select Summary",
        "",
        "This file summarizes the final `select` stage after `generate -> validate -> repair`.",
        "",
        f"- total examples: {summary['total']}",
        f"- final executable on at least one backend: {summary['final_has_exec_ok']}/{summary['total']} = {summary['final_exec_ok_rate']:.3f}",
        f"- final same-result on at least one backend: {summary['final_has_same_result']}/{summary['total']} = {summary['final_same_result_rate']:.3f}",
        f"- final same-result on all three backends: {summary['all_three_same_result']}/{summary['total']}",
        f"- final executable on all three backends: {summary['all_three_exec_ok']}/{summary['total']}",
        "",
        "## Stage Evidence Votes",
    ]

    for stage, count in sorted(summary["stage_votes"].items()):
        lines.append(f"- {stage}: {count}")

    lines.append("")
    lines.append("## Same-result Backend Support Distribution")
    for support, count in summary["same_backend_support_distribution"].items():
        lines.append(f"- {support} backend(s): {count}")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args():
    p = argparse.ArgumentParser(
        description="Select final SQL using evidence from DuckDB/PostgreSQL/MySQL validation and repair outputs."
    )
    p.add_argument("--duckdb", default=BACKENDS["duckdb"]["default_path"])
    p.add_argument("--postgres", default=BACKENDS["postgres"]["default_path"])
    p.add_argument("--mysql", default=BACKENDS["mysql"]["default_path"])
    p.add_argument(
        "--out",
        default="runs/outputs/a2v/multibackend_selected_spider1034.jsonl",
    )
    p.add_argument(
        "--summary",
        default="runs/outputs/a2v/multibackend_select_summary.md",
    )
    return p.parse_args()


def main():
    args = parse_args()
    input_paths = {
        "duckdb": args.duckdb,
        "postgres": args.postgres,
        "mysql": args.mysql,
    }

    rows_by_backend = {}
    all_indices = set()
    for backend, path in input_paths.items():
        rows = {row["idx"]: row for row in read_jsonl(path)}
        rows_by_backend[backend] = rows
        all_indices.update(rows.keys())
        print(f"[LOAD] {backend}: {len(rows)} rows")

    outputs = [make_output_row(rows_by_backend, idx) for idx in sorted(all_indices)]
    write_jsonl(args.out, outputs)

    summary = summarize_outputs(outputs)
    write_summary(args.summary, summary)

    print(f"[OK] wrote selected SQL to {args.out}")
    print(f"[OK] wrote select summary to {args.summary}")
    print(
        "final same-result >=1 backend: "
        f"{summary['final_has_same_result']}/{summary['total']} = {summary['final_same_result_rate']:.3f}"
    )
    print(
        "final executable >=1 backend: "
        f"{summary['final_has_exec_ok']}/{summary['total']} = {summary['final_exec_ok_rate']:.3f}"
    )


if __name__ == "__main__":
    main()
