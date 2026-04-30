import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from openai import OpenAI


def read_mbpp(path, limit=None):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if limit is not None:
        data = data[:limit]
    return data


def clean_code(text):
    if text is None:
        return None

    s = str(text).strip()

    # Remove markdown fences
    s = re.sub(r"^```python\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^```\s*", "", s)
    s = re.sub(r"\s*```$", "", s)

    # JSON support
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            if "code" in data:
                s = str(data["code"]).strip()
            elif "solution" in data:
                s = str(data["solution"]).strip()
    except Exception:
        pass

    # Extract from import/def
    match = re.search(
        r"(from\s+[\w\.]+\s+import\s+.*|import\s+.*|def\s+\w+\s*\(.*)",
        s,
        flags=re.DOTALL,
    )
    if match:
        s = match.group(0).strip()

    return s


def build_generation_prompt(task):
    tests = "\n".join(task.get("test_list", []))
    imports = "\n".join(task.get("test_imports", []))

    return f"""
You are solving an MBPP Python programming task.

Task:
{task["prompt"]}

Test imports:
{imports}

Unit tests:
{tests}

Rules:
- Return full Python code.
- Define all required functions used in the tests.
- Do not include explanations.
- Do not include markdown.
""".strip()


def build_repair_prompt(task, code, error):
    tests = "\n".join(task.get("test_list", []))
    imports = "\n".join(task.get("test_imports", []))

    return f"""
You are repairing a Python solution for an MBPP programming task.

Task:
{task["prompt"]}

Test imports:
{imports}

Unit tests:
{tests}

Current code:
{code}

Error message:
{error}

Repair rules:
- Return full corrected Python code.
- Define all required functions used in the tests.
- Do not include explanations.
- Do not include markdown.
""".strip()


def call_model(client, model, prompt, retries=2, sleep=0.5):
    last_error = None

    for attempt in range(1, retries + 2):
        start = time.time()

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )

            latency_ms = round((time.time() - start) * 1000, 3)
            raw = response.choices[0].message.content
            code = clean_code(raw)

            return {
                "code": code,
                "raw_response": raw,
                "latency_ms": latency_ms,
                "error": None,
                "attempts": attempt,
            }

        except Exception as e:
            last_error = str(e)
            latency_ms = round((time.time() - start) * 1000, 3)

            if attempt <= retries:
                time.sleep(sleep * attempt)
            else:
                return {
                    "code": None,
                    "raw_response": None,
                    "latency_ms": latency_ms,
                    "error": last_error,
                    "attempts": attempt,
                }


def run_tests(code, task, timeout=10):
    if not code:
        return {
            "pass": False,
            "error": "empty_code",
            "stdout": "",
            "stderr": "empty_code",
        }

    imports = "\n".join(task.get("test_imports", []))
    tests = "\n".join(task.get("test_list", []))

    script = f"""
{imports}

{code}

{tests}

print("ALL_TESTS_PASSED")
"""

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(script)
        temp_path = f.name

    try:
        result = subprocess.run(
            ["python3.11", temp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        ok = result.returncode == 0 and "ALL_TESTS_PASSED" in result.stdout

        error = None
        if not ok:
            error = (result.stderr or result.stdout or "unknown_error").strip()

        return {
            "pass": ok,
            "error": error,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    except subprocess.TimeoutExpired:
        return {
            "pass": False,
            "error": "timeout",
            "stdout": "",
            "stderr": "timeout",
        }

    finally:
        try:
            Path(temp_path).unlink()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--data_file",
        type=str,
        default="google-research-mbpp/mbpp/sanitized-mbpp.json",
    )
    parser.add_argument("--model", type=str, default="grok-4-fast")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--max_repairs", type=int, default=1)
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v_python/mbpp_grok_50.jsonl",
    )
    parser.add_argument(
        "--summary_out",
        type=str,
        default="runs/outputs/a2v_python/mbpp_grok_50_summary.md",
    )
    parser.add_argument("--base_url", type=str, default="https://yunwu.ai/v1")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--progress_every", type=int, default=5)

    args = parser.parse_args()

    api_key = os.environ.get("YUNWU_API_KEY")
    if not api_key:
        raise RuntimeError("YUNWU_API_KEY is not set.")

    client = OpenAI(
        api_key=api_key,
        base_url=args.base_url,
        timeout=120,
    )

    tasks = read_mbpp(args.data_file, limit=args.limit)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    initial_pass = 0
    final_pass = 0
    generation_errors = 0

    repair_attempted_tasks = 0
    repair_success_tasks = 0
    repair_api_calls = 0

    generation_latencies = []
    repair_latencies = []

    start_all = time.time()

    with out_path.open("w", encoding="utf-8") as out:
        for idx, task in enumerate(tasks):
            if idx == 0 or (idx + 1) % args.progress_every == 0:
                elapsed = time.time() - start_all
                print(
                    f"[PROGRESS] task {idx + 1}/{len(tasks)} "
                    f"| task_id={task.get('task_id')} "
                    f"| elapsed={elapsed:.1f}s"
                )

            gen_prompt = build_generation_prompt(task)
            gen_result = call_model(
                client=client,
                model=args.model,
                prompt=gen_prompt,
                retries=args.retries,
                sleep=args.sleep,
            )

            code = gen_result["code"]
            generation_latencies.append(gen_result["latency_ms"])

            if gen_result["error"]:
                generation_errors += 1

            test_result = run_tests(code, task)

            row = {
                "idx": idx,
                "task_id": task.get("task_id"),
                "prompt": task.get("prompt"),
                "test_imports": task.get("test_imports", []),
                "test_list": task.get("test_list", []),
                "model": args.model,
                "initial_code": code,
                "initial_raw_response": gen_result["raw_response"],
                "generation_error": gen_result["error"],
                "generation_attempts": gen_result["attempts"],
                "generation_latency_ms": gen_result["latency_ms"],
                "initial_pass": test_result["pass"],
                "initial_error": test_result["error"],
                "repair_attempted": False,
                "repair_rounds": [],
                "final_code": code,
                "final_pass": test_result["pass"],
                "final_error": test_result["error"],
            }

            total += 1

            if test_result["pass"]:
                initial_pass += 1
                final_pass += 1
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                continue

            current_code = code
            current_error = test_result["error"]

            if args.max_repairs > 0:
                repair_attempted_tasks += 1
                row["repair_attempted"] = True

            for repair_round in range(1, args.max_repairs + 1):
                repair_api_calls += 1

                repair_prompt = build_repair_prompt(
                    task=task,
                    code=current_code,
                    error=current_error,
                )

                repair_result = call_model(
                    client=client,
                    model=args.model,
                    prompt=repair_prompt,
                    retries=args.retries,
                    sleep=args.sleep,
                )

                repaired_code = repair_result["code"]
                repair_latencies.append(repair_result["latency_ms"])

                repaired_test = run_tests(repaired_code, task)

                round_info = {
                    "round": repair_round,
                    "repair_code": repaired_code,
                    "repair_raw_response": repair_result["raw_response"],
                    "repair_generation_error": repair_result["error"],
                    "repair_attempts": repair_result["attempts"],
                    "repair_latency_ms": repair_result["latency_ms"],
                    "repair_pass": repaired_test["pass"],
                    "repair_error": repaired_test["error"],
                }

                row["repair_rounds"].append(round_info)

                current_code = repaired_code
                current_error = repaired_test["error"]

                row["final_code"] = repaired_code
                row["final_pass"] = repaired_test["pass"]
                row["final_error"] = repaired_test["error"]

                if repaired_test["pass"]:
                    repair_success_tasks += 1
                    final_pass += 1
                    break

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()

    avg_generation_latency = (
        sum(generation_latencies) / len(generation_latencies)
        if generation_latencies
        else 0.0
    )

    avg_repair_latency = (
        sum(repair_latencies) / len(repair_latencies)
        if repair_latencies
        else 0.0
    )

    initial_rate = initial_pass / total if total else 0.0
    final_rate = final_pass / total if total else 0.0
    repair_success_rate = (
        repair_success_tasks / repair_attempted_tasks
        if repair_attempted_tasks
        else 0.0
    )

    lines = []
    lines.append("# MBPP Python Migration Experiment Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Model | {args.model} |")
    lines.append(f"| Total tasks | {total} |")
    lines.append(f"| Initial pass | {initial_pass}/{total} = {initial_rate:.3f} |")
    lines.append(f"| Repair attempted tasks | {repair_attempted_tasks} |")
    lines.append(f"| Repair API calls | {repair_api_calls} |")
    lines.append(f"| Repair success | {repair_success_tasks}/{repair_attempted_tasks if repair_attempted_tasks else 1} = {repair_success_rate:.3f} |")
    lines.append(f"| Final pass | {final_pass}/{total} = {final_rate:.3f} |")
    lines.append(f"| Generation errors | {generation_errors} |")
    lines.append(f"| Avg generation latency ms | {avg_generation_latency:.1f} |")
    lines.append(f"| Avg repair latency ms | {avg_repair_latency:.1f} |")

    summary_path = Path(args.summary_out)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\n[OK] output: {out_path}")
    print(f"[OK] summary: {summary_path}")


if __name__ == "__main__":
    main()
