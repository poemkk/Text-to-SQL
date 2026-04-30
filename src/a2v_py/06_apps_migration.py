import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from datasets import load_dataset
from openai import OpenAI


def clean_code(text):
    if text is None:
        return None

    s = str(text).strip()

    s = re.sub(r"^```python\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^```\s*", "", s)
    s = re.sub(r"\s*```$", "", s)

    try:
        data = json.loads(s)
        if isinstance(data, dict):
            if "code" in data:
                s = str(data["code"]).strip()
            elif "solution" in data:
                s = str(data["solution"]).strip()
    except Exception:
        pass

    match = re.search(
        r"(import\s+.*|from\s+[\w\.]+\s+import\s+.*|def\s+.*|class\s+.*|if\s+__name__\s*==.*|[\s\S]*)",
        s,
        flags=re.DOTALL,
    )
    if match:
        s = match.group(0).strip()

    return s


def parse_input_output(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def normalize_output(s):
    if s is None:
        return ""
    return str(s).strip()


def build_generation_prompt(task):
    io = parse_input_output(task["input_output"])

    examples = []
    inputs = io.get("inputs", [])
    outputs = io.get("outputs", [])

    for i in range(min(2, len(inputs), len(outputs))):
        examples.append(
            f"Example input:\n{inputs[i]}\nExpected output:\n{outputs[i]}"
        )

    examples_text = "\n\n".join(examples)

    starter_code = task.get("starter_code") or ""

    return f"""
You are solving an APPS competitive programming problem in Python.

Problem:
{task["question"]}

Starter code, if any:
{starter_code}

Sample tests:
{examples_text}

Rules:
- Return a complete Python 3 program.
- The program must read from standard input and write to standard output.
- Do not include explanations.
- Do not include markdown.
- Use only the Python standard library.
""".strip()


def build_repair_prompt(task, code, error_report):
    io = parse_input_output(task["input_output"])

    examples = []
    inputs = io.get("inputs", [])
    outputs = io.get("outputs", [])

    for i in range(min(3, len(inputs), len(outputs))):
        examples.append(
            f"Test input:\n{inputs[i]}\nExpected output:\n{outputs[i]}"
        )

    examples_text = "\n\n".join(examples)

    return f"""
You are repairing a Python 3 program for an APPS competitive programming problem.

Problem:
{task["question"]}

Current code:
{code}

Available tests:
{examples_text}

Failure report:
{error_report}

Repair rules:
- Return a complete corrected Python 3 program.
- The program must read from standard input and write to standard output.
- Preserve the original problem meaning.
- Do not include explanations.
- Do not include markdown.
- Use only the Python standard library.
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


def run_single_test(code, test_input, expected_output, timeout=5):
    if not code:
        return {
            "pass": False,
            "stdout": "",
            "stderr": "empty_code",
            "error": "empty_code",
        }

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        temp_path = f.name

    try:
        result = subprocess.run(
            ["python", temp_path],
            input=str(test_input),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        stdout = normalize_output(result.stdout)
        expected = normalize_output(expected_output)

        ok = result.returncode == 0 and stdout == expected

        error = None
        if not ok:
            if result.returncode != 0:
                error = result.stderr.strip() or f"nonzero_return_code={result.returncode}"
            else:
                error = f"wrong_answer | expected={repr(expected[:300])} | got={repr(stdout[:300])}"

        return {
            "pass": ok,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "error": error,
        }

    except subprocess.TimeoutExpired:
        return {
            "pass": False,
            "stdout": "",
            "stderr": "timeout",
            "error": "timeout",
        }

    finally:
        try:
            Path(temp_path).unlink()
        except Exception:
            pass


def run_apps_tests(code, task, max_tests=10, timeout=5):
    io = parse_input_output(task["input_output"])

    inputs = io.get("inputs", [])
    outputs = io.get("outputs", [])

    n = min(len(inputs), len(outputs), max_tests)

    if n == 0:
        return {
            "pass": False,
            "passed": 0,
            "total": 0,
            "first_error": "no_tests",
            "details": [],
        }

    passed = 0
    details = []
    first_error = None

    for i in range(n):
        result = run_single_test(
            code=code,
            test_input=inputs[i],
            expected_output=outputs[i],
            timeout=timeout,
        )

        details.append({
            "test_id": i,
            "pass": result["pass"],
            "error": result["error"],
            "stdout_preview": result["stdout"][:500],
            "stderr_preview": result["stderr"][:500],
        })

        if result["pass"]:
            passed += 1
        elif first_error is None:
            first_error = result["error"]

    return {
        "pass": passed == n,
        "passed": passed,
        "total": n,
        "first_error": first_error,
        "details": details,
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--dataset", type=str, default="codeparrot/apps")
    parser.add_argument("--split", type=str, default="test")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--model", type=str, default="grok-4-fast")
    parser.add_argument("--max_tests", type=int, default=10)
    parser.add_argument("--test_timeout", type=int, default=5)
    parser.add_argument("--max_repairs", type=int, default=1)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--progress_every", type=int, default=1)
    parser.add_argument("--base_url", type=str, default="https://yunwu.ai/v1")

    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v_python/apps_grok_20.jsonl",
    )
    parser.add_argument(
        "--summary_out",
        type=str,
        default="runs/outputs/a2v_python/apps_grok_20_summary.md",
    )

    args = parser.parse_args()

    api_key = os.environ.get("YUNWU_API_KEY")
    if not api_key:
        raise RuntimeError("YUNWU_API_KEY is not set.")

    client = OpenAI(
        api_key=api_key,
        base_url=args.base_url,
        timeout=180,
    )

    print("[LOAD] loading APPS dataset...")
    ds = load_dataset(
        args.dataset,
        split=f"{args.split}[:{args.limit}]",
        trust_remote_code=True,
    )

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
        for idx, task in enumerate(ds):
            if idx == 0 or (idx + 1) % args.progress_every == 0:
                elapsed = time.time() - start_all
                print(
                    f"[PROGRESS] task {idx + 1}/{len(ds)} "
                    f"| problem_id={task.get('problem_id')} "
                    f"| difficulty={task.get('difficulty')} "
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

            test_result = run_apps_tests(
                code=code,
                task=task,
                max_tests=args.max_tests,
                timeout=args.test_timeout,
            )

            row = {
                "idx": idx,
                "problem_id": task.get("problem_id"),
                "difficulty": task.get("difficulty"),
                "url": task.get("url"),
                "question": task.get("question"),
                "model": args.model,
                "initial_code": code,
                "initial_raw_response": gen_result["raw_response"],
                "generation_error": gen_result["error"],
                "generation_attempts": gen_result["attempts"],
                "generation_latency_ms": gen_result["latency_ms"],
                "initial_pass": test_result["pass"],
                "initial_passed_tests": test_result["passed"],
                "initial_total_tests": test_result["total"],
                "initial_error": test_result["first_error"],
                "initial_details": test_result["details"],
                "repair_attempted": False,
                "repair_rounds": [],
                "final_code": code,
                "final_pass": test_result["pass"],
                "final_passed_tests": test_result["passed"],
                "final_total_tests": test_result["total"],
                "final_error": test_result["first_error"],
            }

            total += 1

            if test_result["pass"]:
                initial_pass += 1
                final_pass += 1
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                continue

            current_code = code
            current_error = test_result["first_error"]

            if args.max_repairs > 0:
                repair_attempted_tasks += 1
                row["repair_attempted"] = True

            for repair_round in range(1, args.max_repairs + 1):
                repair_api_calls += 1

                error_report = (
                    f"First error: {current_error}\n"
                    f"Passed tests: {test_result['passed']}/{test_result['total']}"
                )

                repair_prompt = build_repair_prompt(
                    task=task,
                    code=current_code,
                    error_report=error_report,
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

                repaired_test = run_apps_tests(
                    code=repaired_code,
                    task=task,
                    max_tests=args.max_tests,
                    timeout=args.test_timeout,
                )

                round_info = {
                    "round": repair_round,
                    "repair_code": repaired_code,
                    "repair_raw_response": repair_result["raw_response"],
                    "repair_generation_error": repair_result["error"],
                    "repair_attempts": repair_result["attempts"],
                    "repair_latency_ms": repair_result["latency_ms"],
                    "repair_pass": repaired_test["pass"],
                    "repair_passed_tests": repaired_test["passed"],
                    "repair_total_tests": repaired_test["total"],
                    "repair_error": repaired_test["first_error"],
                    "repair_details": repaired_test["details"],
                }

                row["repair_rounds"].append(round_info)

                current_code = repaired_code
                current_error = repaired_test["first_error"]
                test_result = repaired_test

                row["final_code"] = repaired_code
                row["final_pass"] = repaired_test["pass"]
                row["final_passed_tests"] = repaired_test["passed"]
                row["final_total_tests"] = repaired_test["total"]
                row["final_error"] = repaired_test["first_error"]

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
    lines.append("# APPS Python Migration Experiment Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Model | {args.model} |")
    lines.append(f"| Total tasks | {total} |")
    lines.append(f"| Max tests per task | {args.max_tests} |")
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
