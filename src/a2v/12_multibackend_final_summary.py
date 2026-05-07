import json
from pathlib import Path


FILES = {
    "DuckDB": "runs/outputs/a2v/multibackend_duckdb_spider1034_dialect_repaired.jsonl",
    "PostgreSQL": "runs/outputs/a2v/multibackend_postgres_spider1034_dialect_repaired.jsonl",
    "MySQL": "runs/outputs/a2v/multibackend_mysql_spider1034_dialect_repaired.jsonl",
}


SELECT_FILE = "runs/outputs/a2v/multibackend_selected_spider1034.jsonl"


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


def rate(num, den):
    return num / den if den else 0.0


def any_true(item, keys):
    return any(bool(item.get(k)) for k in keys)


def any_true_with_stage(item, base_keys, stage_key, legacy_key):
    if any_true(item, base_keys):
        return True

    if stage_key in item:
        return bool(item.get(stage_key))

    return bool(item.get(legacy_key))


def summarize_backend(name, rows):
    total = len(rows)

    if name == "DuckDB":
        before_exec = sum(1 for x in rows if x.get("duckdb_exec_ok"))
        before_same = sum(1 for x in rows if x.get("crossdb_same_result"))
        repair_attempted = sum(1 for x in rows if x.get("dialect_repair_attempted"))
        repair_exec = sum(1 for x in rows if x.get("dialect_repair_exec_ok"))
        repair_same = sum(1 for x in rows if x.get("dialect_repair_same_result"))
        after_exec = sum(
            1 for x in rows
            if any_true(x, ["duckdb_exec_ok", "duckdb_after_normalize_exec_ok", "dialect_repair_exec_ok"])
        )
        after_same = sum(
            1 for x in rows
            if any_true(x, ["crossdb_same_result", "crossdb_same_result_after_normalize", "dialect_repair_same_result"])
        )
        after_first_exec = sum(
            1 for x in rows
            if any_true_with_stage(x, ["duckdb_exec_ok", "duckdb_after_normalize_exec_ok"], "dialect_repair_first_candidate_exec_ok", "dialect_repair_exec_ok")
        )
        after_first_same = sum(
            1 for x in rows
            if any_true_with_stage(x, ["crossdb_same_result", "crossdb_same_result_after_normalize"], "dialect_repair_first_candidate_same_result", "dialect_repair_same_result")
        )
        after_select_exec = sum(
            1 for x in rows
            if any_true_with_stage(x, ["duckdb_exec_ok", "duckdb_after_normalize_exec_ok"], "dialect_repair_selected_exec_ok", "dialect_repair_exec_ok")
        )
        after_select_same = sum(
            1 for x in rows
            if any_true_with_stage(x, ["crossdb_same_result", "crossdb_same_result_after_normalize"], "dialect_repair_selected_same_result", "dialect_repair_same_result")
        )

    elif name == "PostgreSQL":
        before_exec = sum(1 for x in rows if x.get("postgres_exec_ok"))
        before_same = sum(1 for x in rows if x.get("postgres_crossdb_same_result"))
        repair_attempted = sum(1 for x in rows if x.get("postgres_dialect_repair_attempted"))
        repair_exec = sum(1 for x in rows if x.get("postgres_dialect_repair_exec_ok"))
        repair_same = sum(1 for x in rows if x.get("postgres_dialect_repair_same_result"))
        after_exec = sum(
            1 for x in rows
            if any_true(x, ["postgres_exec_ok", "postgres_after_normalize_exec_ok", "postgres_dialect_repair_exec_ok"])
        )
        after_same = sum(
            1 for x in rows
            if any_true(x, ["postgres_crossdb_same_result", "postgres_crossdb_same_result_after_normalize", "postgres_dialect_repair_same_result"])
        )
        after_first_exec = sum(
            1 for x in rows
            if any_true_with_stage(x, ["postgres_exec_ok", "postgres_after_normalize_exec_ok"], "postgres_dialect_repair_first_candidate_exec_ok", "postgres_dialect_repair_exec_ok")
        )
        after_first_same = sum(
            1 for x in rows
            if any_true_with_stage(x, ["postgres_crossdb_same_result", "postgres_crossdb_same_result_after_normalize"], "postgres_dialect_repair_first_candidate_same_result", "postgres_dialect_repair_same_result")
        )
        after_select_exec = sum(
            1 for x in rows
            if any_true_with_stage(x, ["postgres_exec_ok", "postgres_after_normalize_exec_ok"], "postgres_dialect_repair_selected_exec_ok", "postgres_dialect_repair_exec_ok")
        )
        after_select_same = sum(
            1 for x in rows
            if any_true_with_stage(x, ["postgres_crossdb_same_result", "postgres_crossdb_same_result_after_normalize"], "postgres_dialect_repair_selected_same_result", "postgres_dialect_repair_same_result")
        )

    elif name == "MySQL":
        before_exec = sum(1 for x in rows if x.get("mysql_exec_ok"))
        before_same = sum(1 for x in rows if x.get("mysql_crossdb_same_result"))
        repair_attempted = sum(1 for x in rows if x.get("mysql_dialect_repair_attempted"))
        repair_exec = sum(1 for x in rows if x.get("mysql_dialect_repair_exec_ok"))
        repair_same = sum(1 for x in rows if x.get("mysql_dialect_repair_same_result"))
        after_exec = sum(
            1 for x in rows
            if any_true(x, ["mysql_exec_ok", "mysql_after_normalize_exec_ok", "mysql_dialect_repair_exec_ok"])
        )
        after_same = sum(
            1 for x in rows
            if any_true(x, ["mysql_crossdb_same_result", "mysql_crossdb_same_result_after_normalize", "mysql_dialect_repair_same_result"])
        )
        after_first_exec = sum(
            1 for x in rows
            if any_true_with_stage(x, ["mysql_exec_ok", "mysql_after_normalize_exec_ok"], "mysql_dialect_repair_first_candidate_exec_ok", "mysql_dialect_repair_exec_ok")
        )
        after_first_same = sum(
            1 for x in rows
            if any_true_with_stage(x, ["mysql_crossdb_same_result", "mysql_crossdb_same_result_after_normalize"], "mysql_dialect_repair_first_candidate_same_result", "mysql_dialect_repair_same_result")
        )
        after_select_exec = sum(
            1 for x in rows
            if any_true_with_stage(x, ["mysql_exec_ok", "mysql_after_normalize_exec_ok"], "mysql_dialect_repair_selected_exec_ok", "mysql_dialect_repair_exec_ok")
        )
        after_select_same = sum(
            1 for x in rows
            if any_true_with_stage(x, ["mysql_crossdb_same_result", "mysql_crossdb_same_result_after_normalize"], "mysql_dialect_repair_selected_same_result", "mysql_dialect_repair_same_result")
        )

    else:
        raise ValueError(name)

    return {
        "backend": name,
        "examples": total,
        "before_exec_rate": rate(before_exec, total),
        "before_same_result_rate": rate(before_same, total),
        "repair_attempted": repair_attempted,
        "repair_exec_success": rate(repair_exec, repair_attempted),
        "repair_same_success": rate(repair_same, repair_attempted),
        "after_exec_rate": rate(after_exec, total),
        "after_same_result_rate": rate(after_same, total),
        "after_first_exec_rate": rate(after_first_exec, total),
        "after_first_same_result_rate": rate(after_first_same, total),
        "after_select_exec_rate": rate(after_select_exec, total),
        "after_select_same_result_rate": rate(after_select_same, total),
    }


def summarize_select(rows):
    total = len(rows)
    selected_exec = sum(1 for x in rows if x.get("selected_exec_ok") or x.get("final_has_exec_ok"))
    selected_same = sum(
        1 for x in rows
        if x.get("selected_crossdb_same_result") or x.get("final_has_same_result")
    )
    selected_same_2plus = sum(
        1 for x in rows
        if len(x.get("final_same_result_backends") or []) >= 2
    )
    selected_same_3 = sum(
        1 for x in rows
        if len(x.get("final_same_result_backends") or []) == 3
    )
    selected_exec_3 = sum(
        1 for x in rows
        if len(x.get("final_exec_ok_backends") or []) == 3
    )

    by_variant = {}
    for item in rows:
        variant = item.get("selected_variant") or item.get("final_selected_stage") or "unknown"
        by_variant[variant] = by_variant.get(variant, 0) + 1

    return {
        "examples": total,
        "selected_exec_rate": rate(selected_exec, total),
        "selected_same_rate": rate(selected_same, total),
        "selected_same_2plus_rate": rate(selected_same_2plus, total),
        "selected_same_3_rate": rate(selected_same_3, total),
        "selected_exec_3_rate": rate(selected_exec_3, total),
        "selected_exec": selected_exec,
        "selected_same": selected_same,
        "selected_same_2plus": selected_same_2plus,
        "selected_same_3": selected_same_3,
        "selected_exec_3": selected_exec_3,
        "by_variant": by_variant,
    }


def main():
    rows = []

    for backend, path in FILES.items():
        data = read_jsonl(path)
        if data:
            rows.append(summarize_backend(backend, data))

    selected_rows = read_jsonl(SELECT_FILE)
    select_summary = summarize_select(selected_rows) if selected_rows else None

    out_path = Path("runs/outputs/a2v/multibackend_final_summary.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("# Multi-backend Validate, Repair, and Select Summary")
    lines.append("")
    lines.append("| Backend | Examples | Before Exec. | Before Same Result | Repair Attempted | Repair Exec. Success | Repair Same Success | After Exec. | After Same Result | After First Repair Same | After Select Same |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    for r in rows:
        lines.append(
            f"| {r['backend']} | {r['examples']} | "
            f"{r['before_exec_rate']:.3f} | "
            f"{r['before_same_result_rate']:.3f} | "
            f"{r['repair_attempted']} | "
            f"{r['repair_exec_success']:.3f} | "
            f"{r['repair_same_success']:.3f} | "
            f"{r['after_exec_rate']:.3f} | "
            f"{r['after_same_result_rate']:.3f} | "
            f"{r['after_first_same_result_rate']:.3f} | "
            f"{r['after_select_same_result_rate']:.3f} |"
        )

    if select_summary:
        lines.append("")
        lines.append("## Select Stage")
        lines.append("")
        lines.append("| Examples | Selected Exec. >=1 Backend | Selected Same >=1 Backend | Selected Same >=2 Backends | Selected Same 3 Backends | Selected Exec. 3 Backends |")
        lines.append("|---:|---:|---:|---:|---:|---:|")
        lines.append(
            f"| {select_summary['examples']} | "
            f"{select_summary['selected_exec_rate']:.3f} | "
            f"{select_summary['selected_same_rate']:.3f} | "
            f"{select_summary['selected_same_2plus_rate']:.3f} | "
            f"{select_summary['selected_same_3_rate']:.3f} | "
            f"{select_summary['selected_exec_3_rate']:.3f} |"
        )
        lines.append("")
        lines.append("## Selected Variant Distribution")
        lines.append("")
        lines.append("| Variant | Count |")
        lines.append("|---|---:|")
        for variant, count in sorted(select_summary["by_variant"].items()):
            lines.append(f"| {variant} | {count} |")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\n[OK] wrote summary to {out_path}")


if __name__ == "__main__":
    main()
