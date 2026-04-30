import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON_OUTPUT_DIR = ROOT / "runs" / "outputs" / "a2v_python"


def summary():
    return {
        "dataset": "APPS-500",
        "validation": "unit-test validation",
        "models": [
            {
                "model": "gpt-5.4-mini",
                "tasks": 500,
                "initial_pass": 0.456,
                "repair_attempted": 272,
                "repair_success": 0.529,
                "final_pass": 0.744,
                "improvement": 0.288,
            },
            {
                "model": "gemini-3.1-flash-lite-preview",
                "tasks": 500,
                "initial_pass": 0.708,
                "repair_attempted": 146,
                "repair_success": 0.699,
                "final_pass": 0.912,
                "improvement": 0.204,
            },
            {
                "model": "claude-haiku-4-5-20251001",
                "tasks": 500,
                "initial_pass": 0.128,
                "repair_attempted": 436,
                "repair_success": 0.798,
                "final_pass": 0.824,
                "improvement": 0.696,
            },
            {
                "model": "deepseek-chat",
                "tasks": 500,
                "initial_pass": 0.164,
                "repair_attempted": 418,
                "repair_success": 0.715,
                "final_pass": 0.762,
                "improvement": 0.598,
            },
            {
                "model": "grok-4-20-non-reasoning",
                "tasks": 500,
                "initial_pass": 0.454,
                "repair_attempted": 273,
                "repair_success": 0.447,
                "final_pass": 0.698,
                "improvement": 0.244,
            },
        ],
    }


@lru_cache(maxsize=1)
def examples():
    paths = [
        PYTHON_OUTPUT_DIR / "apps_gemini_500.jsonl",
        *sorted(PYTHON_OUTPUT_DIR.glob("apps_*_500.jsonl")),
    ]
    rows = []
    seen = set()
    for path in paths:
        if not path.exists() or path in seen:
            continue
        seen.add(path)
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows.append(_shape_example(row))
                if len(rows) >= 12:
                    break
        if len(rows) >= 12:
            break

    repaired = [row for row in rows if not row["initial_pass"] and row["final_pass"]]
    selected = (repaired + rows)[:5]
    return selected or [_fallback_example()]


def _shape_example(row):
    return {
        "question": row.get("question") or row.get("prompt") or "Programming task",
        "model": row.get("model"),
        "initial_code": row.get("initial_code") or "",
        "initial_pass": bool(row.get("initial_pass")),
        "initial_error": row.get("initial_error"),
        "final_code": row.get("final_code") or row.get("initial_code") or "",
        "final_pass": bool(row.get("final_pass")),
        "final_error": row.get("final_error"),
        "repair_attempted": bool(row.get("repair_attempted")),
    }


def _fallback_example():
    return {
        "question": "Given a list of numbers, return the sum.",
        "model": "demo-fallback",
        "initial_code": "def solve(nums):\n    return len(nums)",
        "initial_pass": False,
        "initial_error": "Wrong answer on test 2",
        "final_code": "def solve(nums):\n    return sum(nums)",
        "final_pass": True,
        "final_error": None,
        "repair_attempted": True,
    }


def repair_demo(code: str, error: str):
    return {
        "repair_attempted": True,
        "validation_environment": "unit tests",
        "original_error": error,
        "repair_reason": "The code failed unit tests; repair modifies boundary condition.",
        "final_pass": True,
    }
