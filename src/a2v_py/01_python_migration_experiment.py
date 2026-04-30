import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from openai import OpenAI


TASKS = [
    {
        "task_id": "py_001",
        "prompt": "Write a function add(a, b) that returns the sum of a and b.",
        "entry_point": "add",
        "tests": [
            "assert add(1, 2) == 3",
            "assert add(-1, 1) == 0",
            "assert add(0, 0) == 0",
        ],
    },
    {
        "task_id": "py_002",
        "prompt": "Write a function is_even(n) that returns True if n is even, otherwise False.",
        "entry_point": "is_even",
        "tests": [
            "assert is_even(2) is True",
            "assert is_even(3) is False",
            "assert is_even(0) is True",
        ],
    },
    {
        "task_id": "py_003",
        "prompt": "Write a function factorial(n) that returns n factorial. Assume n is a non-negative integer.",
        "entry_point": "factorial",
        "tests": [
            "assert factorial(0) == 1",
            "assert factorial(1) == 1",
            "assert factorial(5) == 120",
        ],
    },
    {
        "task_id": "py_004",
        "prompt": "Write a function reverse_string(s) that returns the reversed string.",
        "entry_point": "reverse_string",
        "tests": [
            "assert reverse_string('abc') == 'cba'",
            "assert reverse_string('') == ''",
            "assert reverse_string('a') == 'a'",
        ],
    },
    {
        "task_id": "py_005",
        "prompt": "Write a function count_vowels(s) that returns the number of vowels in a string. Count both lowercase and uppercase vowels.",
        "entry_point": "count_vowels",
        "tests": [
            "assert count_vowels('hello') == 2",
            "assert count_vowels('HELLO') == 2",
            "assert count_vowels('xyz') == 0",
        ],
    },
    {
        "task_id": "py_006",
        "prompt": "Write a function max_in_list(nums) that returns the maximum number in a non-empty list.",
        "entry_point": "max_in_list",
        "tests": [
            "assert max_in_list([1, 2, 3]) == 3",
            "assert max_in_list([-5, -2, -9]) == -2",
            "assert max_in_list([7]) == 7",
        ],
    },
    {
        "task_id": "py_007",
        "prompt": "Write a function remove_duplicates(nums) that returns a list with duplicates removed while preserving the original order.",
        "entry_point": "remove_duplicates",
        "tests": [
            "assert remove_duplicates([1, 2, 1, 3, 2]) == [1, 2, 3]",
            "assert remove_duplicates([]) == []",
            "assert remove_duplicates([4, 4, 4]) == [4]",
        ],
    },
    {
        "task_id": "py_008",
        "prompt": "Write a function is_palindrome(s) that returns True if the string is a palindrome, otherwise False.",
        "entry_point": "is_palindrome",
        "tests": [
            "assert is_palindrome('level') is True",
            "assert is_palindrome('hello') is False",
            "assert is_palindrome('') is True",
        ],
    },
    {
        "task_id": "py_009",
        "prompt": "Write a function sum_list(nums) that returns the sum of all numbers in a list.",
        "entry_point": "sum_list",
        "tests": [
            "assert sum_list([1, 2, 3]) == 6",
            "assert sum_list([]) == 0",
            "assert sum_list([-1, 1]) == 0",
        ],
    },
    {
        "task_id": "py_010",
        "prompt": "Write a function fibonacci(n) that returns the nth Fibonacci number, where fibonacci(0)=0 and fibonacci(1)=1.",
        "entry_point": "fibonacci",
        "tests": [
            "assert fibonacci(0) == 0",
            "assert fibonacci(1) == 1",
            "assert fibonacci(7) == 13",
        ],
    },
    {
        "task_id": "py_011",
        "prompt": "Write a function square_list(nums) that returns a new list containing the square of each number.",
        "entry_point": "square_list",
        "tests": [
            "assert square_list([1, 2, 3]) == [1, 4, 9]",
            "assert square_list([]) == []",
            "assert square_list([-2, 3]) == [4, 9]",
        ],
    },
    {
        "task_id": "py_012",
        "prompt": "Write a function find_min(nums) that returns the minimum number in a non-empty list.",
        "entry_point": "find_min",
        "tests": [
            "assert find_min([3, 1, 2]) == 1",
            "assert find_min([-1, -5, 0]) == -5",
            "assert find_min([10]) == 10",
        ],
    },
    {
        "task_id": "py_013",
        "prompt": "Write a function word_count(s) that returns the number of words in the string separated by whitespace.",
        "entry_point": "word_count",
        "tests": [
            "assert word_count('hello world') == 2",
            "assert word_count('  one   two three  ') == 3",
            "assert word_count('') == 0",
        ],
    },
    {
        "task_id": "py_014",
        "prompt": "Write a function merge_sorted(a, b) that merges two sorted lists into one sorted list.",
        "entry_point": "merge_sorted",
        "tests": [
            "assert merge_sorted([1, 3], [2, 4]) == [1, 2, 3, 4]",
            "assert merge_sorted([], [1]) == [1]",
            "assert merge_sorted([1, 2], []) == [1, 2]",
        ],
    },
    {
        "task_id": "py_015",
        "prompt": "Write a function is_prime(n) that returns True if n is a prime number, otherwise False.",
        "entry_point": "is_prime",
        "tests": [
            "assert is_prime(2) is True",
            "assert is_prime(9) is False",
            "assert is_prime(1) is False",
        ],
    },
    {
        "task_id": "py_016",
        "prompt": "Write a function flatten(lst) that flattens a list of lists by one level.",
        "entry_point": "flatten",
        "tests": [
            "assert flatten([[1, 2], [3], []]) == [1, 2, 3]",
            "assert flatten([]) == []",
            "assert flatten([[1], [2, 3]]) == [1, 2, 3]",
        ],
    },
    {
        "task_id": "py_017",
        "prompt": "Write a function capitalize_words(s) that capitalizes the first letter of each word.",
        "entry_point": "capitalize_words",
        "tests": [
            "assert capitalize_words('hello world') == 'Hello World'",
            "assert capitalize_words('python') == 'Python'",
            "assert capitalize_words('') == ''",
        ],
    },
    {
        "task_id": "py_018",
        "prompt": "Write a function count_occurrences(nums, x) that returns how many times x appears in nums.",
        "entry_point": "count_occurrences",
        "tests": [
            "assert count_occurrences([1, 2, 1, 3], 1) == 2",
            "assert count_occurrences([], 1) == 0",
            "assert count_occurrences([2, 2, 2], 2) == 3",
        ],
    },
    {
        "task_id": "py_019",
        "prompt": "Write a function second_largest(nums) that returns the second largest distinct number in a list. Assume it exists.",
        "entry_point": "second_largest",
        "tests": [
            "assert second_largest([1, 2, 3]) == 2",
            "assert second_largest([5, 5, 4, 3]) == 4",
            "assert second_largest([-1, -2, -3]) == -2",
        ],
    },
    {
        "task_id": "py_020",
        "prompt": "Write a function are_anagrams(a, b) that returns True if two strings are anagrams, otherwise False.",
        "entry_point": "are_anagrams",
        "tests": [
            "assert are_anagrams('listen', 'silent') is True",
            "assert are_anagrams('hello', 'world') is False",
            "assert are_anagrams('Triangle', 'Integral') is True",
        ],
    },
]


def clean_code(text):
    if text is None:
        return None

    s = str(text).strip()

    s = re.sub(r"^```python\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^```\s*", "", s)
    s = re.sub(r"\s*```$", "", s)

    match = re.search(r"(def\s+\w+\s*\(.*)", s, flags=re.DOTALL)
    if match:
        s = match.group(1).strip()

    return s


def build_generation_prompt(task):
    return f"""
You are a Python code generation system.

Task:
{task["prompt"]}

Entry point:
{task["entry_point"]}

Rules:
- Return only Python code.
- Define the required function.
- Do not include explanations.
- Do not include markdown.
""".strip()


def build_repair_prompt(task, code, error):
    tests_text = "\n".join(task["tests"])

    return f"""
You are a Python code repair system.

The following Python function failed unit tests.

Task:
{task["prompt"]}

Entry point:
{task["entry_point"]}

Current code:
{code}

Unit tests:
{tests_text}

Error message:
{error}

Repair rules:
- Return only corrected Python code.
- Preserve the required function name and signature.
- Do not include explanations.
- Do not include markdown.
""".strip()


def call_model(client, model, prompt):
    start = time.time()

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    latency_ms = round((time.time() - start) * 1000, 3)
    content = response.choices[0].message.content
    return clean_code(content), content, latency_ms


def run_tests(code, tests, timeout=5):
    test_code = code + "\n\n" + "\n".join(tests) + "\nprint('ALL_TESTS_PASSED')\n"

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(test_code)
        path = f.name

    try:
        result = subprocess.run(
            ["python3.11", path],
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
            Path(path).unlink()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="gpt-5.4-mini")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max_repairs", type=int, default=1)
    parser.add_argument("--out", type=str, default="runs/outputs/a2v_python/python_migration_20.jsonl")
    parser.add_argument("--summary_out", type=str, default="runs/outputs/a2v_python/python_migration_20_summary.md")
    parser.add_argument("--base_url", type=str, default="https://yunwu.ai/v1")
    args = parser.parse_args()

    api_key = os.environ.get("YUNWU_API_KEY")
    if not api_key:
        raise RuntimeError("YUNWU_API_KEY is not set.")

    client = OpenAI(
        api_key=api_key,
        base_url=args.base_url,
        timeout=120,
    )

    tasks = TASKS[: args.limit]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    initial_pass = 0
    final_pass = 0
    repair_attempted = 0
    repair_success = 0

    generation_latencies = []
    repair_latencies = []

    with out_path.open("w", encoding="utf-8") as out:
        for idx, task in enumerate(tasks):
            print(f"[PROGRESS] task {idx + 1}/{len(tasks)} | {task['task_id']}")

            gen_prompt = build_generation_prompt(task)
            code, raw_response, gen_latency = call_model(
                client=client,
                model=args.model,
                prompt=gen_prompt,
            )
            generation_latencies.append(gen_latency)

            test_result = run_tests(code, task["tests"])

            row = {
                "task_id": task["task_id"],
                "prompt": task["prompt"],
                "entry_point": task["entry_point"],
                "tests": task["tests"],
                "model": args.model,
                "initial_code": code,
                "initial_raw_response": raw_response,
                "initial_pass": test_result["pass"],
                "initial_error": test_result["error"],
                "generation_latency_ms": gen_latency,
                "repair_attempted": False,
                "repair_code": None,
                "repair_raw_response": None,
                "repair_pass": False,
                "repair_error": None,
                "repair_latency_ms": None,
                "final_pass": test_result["pass"],
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

            for repair_round in range(args.max_repairs):
                repair_attempted += 1
                row["repair_attempted"] = True

                repair_prompt = build_repair_prompt(task, current_code, current_error)
                repaired_code, repair_raw, repair_latency = call_model(
                    client=client,
                    model=args.model,
                    prompt=repair_prompt,
                )
                repair_latencies.append(repair_latency)

                repaired_result = run_tests(repaired_code, task["tests"])

                row["repair_code"] = repaired_code
                row["repair_raw_response"] = repair_raw
                row["repair_pass"] = repaired_result["pass"]
                row["repair_error"] = repaired_result["error"]
                row["repair_latency_ms"] = repair_latency
                row["final_pass"] = repaired_result["pass"]

                if repaired_result["pass"]:
                    repair_success += 1
                    final_pass += 1
                    break

                current_code = repaired_code
                current_error = repaired_result["error"]

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()

    avg_gen_latency = sum(generation_latencies) / len(generation_latencies) if generation_latencies else 0.0
    avg_repair_latency = sum(repair_latencies) / len(repair_latencies) if repair_latencies else 0.0

    lines = []
    lines.append("# Python Migration Experiment Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Model | {args.model} |")
    lines.append(f"| Total tasks | {total} |")
    lines.append(f"| Initial pass | {initial_pass}/{total} = {initial_pass / total:.3f} |")
    lines.append(f"| Repair attempted | {repair_attempted} |")
    lines.append(f"| Repair success | {repair_success}/{repair_attempted if repair_attempted else 1} = {repair_success / repair_attempted if repair_attempted else 0:.3f} |")
    lines.append(f"| Final pass | {final_pass}/{total} = {final_pass / total:.3f} |")
    lines.append(f"| Avg generation latency ms | {avg_gen_latency:.1f} |")
    lines.append(f"| Avg repair latency ms | {avg_repair_latency:.1f} |")

    summary_path = Path(args.summary_out)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\n[OK] output: {out_path}")
    print(f"[OK] summary: {summary_path}")


if __name__ == "__main__":
    main()
