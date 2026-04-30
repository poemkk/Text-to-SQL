import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAVA_OUTPUT_DIR = ROOT / "runs" / "outputs" / "a2v_java"


def summary():
    return {
        "dataset": "MBPP-Java-386",
        "validation": "javac compilation + test validation",
        "models": [
            {
                "model": "gpt-5.4-mini",
                "tasks": 386,
                "initial_pass": 0.803,
                "repair_attempted": 76,
                "repair_success": 0.605,
                "final_pass": 0.922,
                "improvement": 0.119,
            },
            {
                "model": "gemini-3.1-flash-lite-preview",
                "tasks": 386,
                "initial_pass": 0.847,
                "repair_attempted": 59,
                "repair_success": 0.780,
                "final_pass": 0.966,
                "improvement": 0.119,
            },
            {
                "model": "claude-haiku-4-5-20251001",
                "tasks": 386,
                "initial_pass": 0.741,
                "repair_attempted": 100,
                "repair_success": 0.600,
                "final_pass": 0.896,
                "improvement": 0.155,
            },
            {
                "model": "grok-4-20-non-reasoning",
                "tasks": 386,
                "initial_pass": 0.715,
                "repair_attempted": 110,
                "repair_success": 0.527,
                "final_pass": 0.865,
                "improvement": 0.150,
            },
            {
                "model": "deepseek-chat",
                "tasks": 386,
                "initial_pass": 0.731,
                "repair_attempted": 104,
                "repair_success": 0.644,
                "final_pass": 0.904,
                "improvement": 0.173,
            },
        ],
    }


@lru_cache(maxsize=1)
def examples():
    paths = [
        JAVA_OUTPUT_DIR / "multiple_mbpp_java_gemini_386_v2.jsonl",
        *sorted(JAVA_OUTPUT_DIR.glob("multiple_mbpp_java_*_386_v2.jsonl")),
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
        "name": row.get("name") or "mbpp_demo",
        "prompt": row.get("prompt") or "",
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
        "name": "mbpp_3_is_not_prime",
        "prompt": "Write a Java function to identify non-prime numbers.",
        "initial_code": "class Problem {\n  public static boolean isNotPrime(long n) { return n % 2 == 0; }\n}",
        "initial_pass": False,
        "initial_error": "AssertionError",
        "final_code": "class Problem {\n  public static boolean isNotPrime(long n) {\n    if (n <= 1) return true;\n    for (long i = 2; i * i <= n; i++) if (n % i == 0) return true;\n    return false;\n  }\n}",
        "final_pass": True,
        "final_error": None,
        "repair_attempted": True,
    }


def repair_demo(code: str, error: str):
    return {
        "repair_attempted": True,
        "validation_environment": "javac + tests",
        "original_error": error,
        "repair_reason": "The javac error indicates a missing symbol or type mismatch.",
        "final_pass": True,
    }
