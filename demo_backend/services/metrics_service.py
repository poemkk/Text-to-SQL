from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUMMARY_PATH = (
    ROOT
    / "runs"
    / "outputs"
    / "a2v"
    / "semantic_selector"
    / "summary_gpt54_pairwise_full_conf070_margin05.md"
)


def _safe_float(value: str, default: float):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _selector_from_summary():
    fallback = {
        "rule_based_practical": 0.779,
        "multi_llm_practical": 0.816,
        "ease_practical": 0.834,
        "oracle_upper_bound": 0.868,
        "gap_rule": 0.089,
        "gap_ease": 0.034,
        "selector_summary_file": str(SUMMARY_PATH.relative_to(ROOT)),
    }
    if not SUMMARY_PATH.exists():
        return fallback

    rows = {}
    with SUMMARY_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|"):
                continue
            parts = [item.strip() for item in line.split("|")]
            if len(parts) < 8:
                continue
            selector = parts[1]
            if selector in {"practical_baseline", "llm_pairwise_correction", "oracle"}:
                rows[selector] = {
                    "exec_acc": _safe_float(parts[5], 0.0),
                    "oracle_gap": _safe_float(parts[7], 0.0),
                }

    if len(rows) < 3:
        return fallback

    return {
        "rule_based_practical": rows["practical_baseline"]["exec_acc"],
        "multi_llm_practical": fallback["multi_llm_practical"],
        "ease_practical": rows["llm_pairwise_correction"]["exec_acc"],
        "oracle_upper_bound": rows["oracle"]["exec_acc"],
        "gap_rule": rows["practical_baseline"]["oracle_gap"],
        "gap_ease": rows["llm_pairwise_correction"]["oracle_gap"],
        "selector_summary_file": str(SUMMARY_PATH.relative_to(ROOT)),
    }


def metrics_overview():
    selector = _selector_from_summary()
    return {
        "sql": [
            {"method": "promptonly", "exec_rate": 0.144, "exec_acc": 0.114},
            {"method": "bm25rag", "exec_rate": 0.940, "exec_acc": 0.642},
            {"method": "embedrag", "exec_rate": 0.997, "exec_acc": 0.734},
            {"method": "rule_selector_priority", "exec_rate": 0.998, "exec_acc": 0.745},
            {
                "method": "A2V_full_strong_repair_practical_v2",
                "exec_rate": 0.998,
                "exec_acc": 0.779,
            },
            {
                "method": "strong_repair_oracle_upper_bound",
                "exec_rate": 0.998,
                "exec_acc": selector["oracle_upper_bound"],
            },
        ],
        "selector_analysis": selector,
        "python": {
            "dataset": "APPS-500",
            "best_initial_model": "gemini-3.1-flash-lite-preview",
            "best_initial_pass": 0.708,
            "best_final_model": "gemini-3.1-flash-lite-preview",
            "best_final_pass": 0.912,
        },
        "java": {
            "dataset": "MBPP-Java-386",
            "best_initial_model": "gemini-3.1-flash-lite-preview",
            "best_initial_pass": 0.847,
            "best_final_model": "gemini-3.1-flash-lite-preview",
            "best_final_pass": 0.966,
        },
        "multi_backend": [
            {"backend": "DuckDB", "after_exec": 0.996, "same_result": 0.760},
            {"backend": "PostgreSQL", "after_exec": 0.994, "same_result": 0.755},
            {"backend": "MySQL", "after_exec": 0.998, "same_result": 0.755},
        ],
    }
