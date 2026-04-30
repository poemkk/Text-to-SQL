import json
from pathlib import Path


FILES = {
    "DuckDB": "runs/outputs/a2v/multibackend_duckdb_spider1034_dialect_repaired.jsonl",
    "PostgreSQL": "runs/outputs/a2v/multibackend_postgres_spider1034_dialect_repaired.jsonl",
    "MySQL": "runs/outputs/a2v/multibackend_mysql_spider1034_dialect_repaired.jsonl",
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


def rate(num, den):
    return num / den if den else 0.0


def summarize_backend(name, rows):
    total = len(rows)

    if name == "DuckDB":
        before_exec = sum(1 for x in rows if x.get("duckdb_exec_ok"))
        before_same = sum(1 for x in rows if x.get("crossdb_same_result"))
        repair_attempted = sum(1 for x in rows if x.get("dialect_repair_attempted"))
        repair_exec = sum(1 for x in rows if x.get("dialect_repair_exec_ok"))
        repair_same = sum(1 for x in rows if x.get("dialect_repair_same_result"))

    elif name == "PostgreSQL":
        before_exec = sum(1 for x in rows if x.get("postgres_exec_ok"))
        before_same = sum(1 for x in rows if x.get("postgres_crossdb_same_result"))
        repair_attempted = sum(1 for x in rows if x.get("postgres_dialect_repair_attempted"))
        repair_exec = sum(1 for x in rows if x.get("postgres_dialect_repair_exec_ok"))
        repair_same = sum(1 for x in rows if x.get("postgres_dialect_repair_same_result"))

    elif name == "MySQL":
        before_exec = sum(1 for x in rows if x.get("mysql_exec_ok"))
        before_same = sum(1 for x in rows if x.get("mysql_crossdb_same_result"))
        repair_attempted = sum(1 for x in rows if x.get("mysql_dialect_repair_attempted"))
        repair_exec = sum(1 for x in rows if x.get("mysql_dialect_repair_exec_ok"))
        repair_same = sum(1 for x in rows if x.get("mysql_dialect_repair_same_result"))

    else:
        raise ValueError(name)

    after_exec = before_exec + repair_exec
    after_same = before_same + repair_same

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
    }


def main():
    rows = []

    for backend, path in FILES.items():
        data = read_jsonl(path)
        if data:
            rows.append(summarize_backend(backend, data))

    out_path = Path("runs/outputs/a2v/multibackend_final_summary.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("# Multi-backend Execution and Dialect Repair Summary")
    lines.append("")
    lines.append("| Backend | Examples | Before Exec. | Before Same Result | Repair Attempted | Repair Exec. Success | Repair Same Success | After Exec. | After Same Result |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    for r in rows:
        lines.append(
            f"| {r['backend']} | {r['examples']} | "
            f"{r['before_exec_rate']:.3f} | "
            f"{r['before_same_result_rate']:.3f} | "
            f"{r['repair_attempted']} | "
            f"{r['repair_exec_success']:.3f} | "
            f"{r['repair_same_success']:.3f} | "
            f"{r['after_exec_rate']:.3f} | "
            f"{r['after_same_result_rate']:.3f} |"
        )

    out_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\n[OK] wrote summary to {out_path}")


if __name__ == "__main__":
    main()
