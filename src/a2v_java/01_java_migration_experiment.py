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
        "task_id": "java_001",
        "prompt": "Implement method add that returns the sum of two integers.",
        "method_signature": "public static int add(int a, int b)",
        "tests": [
            "if (Solution.add(1, 2) != 3) throw new RuntimeException();",
            "if (Solution.add(-1, 1) != 0) throw new RuntimeException();",
            "if (Solution.add(0, 0) != 0) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_002",
        "prompt": "Implement method isEven that returns true if n is even.",
        "method_signature": "public static boolean isEven(int n)",
        "tests": [
            "if (!Solution.isEven(2)) throw new RuntimeException();",
            "if (Solution.isEven(3)) throw new RuntimeException();",
            "if (!Solution.isEven(0)) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_003",
        "prompt": "Implement method factorial that returns factorial of a non-negative integer n.",
        "method_signature": "public static int factorial(int n)",
        "tests": [
            "if (Solution.factorial(0) != 1) throw new RuntimeException();",
            "if (Solution.factorial(1) != 1) throw new RuntimeException();",
            "if (Solution.factorial(5) != 120) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_004",
        "prompt": "Implement method reverse that returns the reversed string.",
        "method_signature": "public static String reverse(String s)",
        "tests": [
            "if (!Solution.reverse(\"abc\").equals(\"cba\")) throw new RuntimeException();",
            "if (!Solution.reverse(\"\").equals(\"\")) throw new RuntimeException();",
            "if (!Solution.reverse(\"a\").equals(\"a\")) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_005",
        "prompt": "Implement method countVowels that counts lowercase and uppercase vowels in a string.",
        "method_signature": "public static int countVowels(String s)",
        "tests": [
            "if (Solution.countVowels(\"hello\") != 2) throw new RuntimeException();",
            "if (Solution.countVowels(\"HELLO\") != 2) throw new RuntimeException();",
            "if (Solution.countVowels(\"xyz\") != 0) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_006",
        "prompt": "Implement method maxInArray that returns the maximum value in a non-empty int array.",
        "method_signature": "public static int maxInArray(int[] nums)",
        "tests": [
            "if (Solution.maxInArray(new int[]{1,2,3}) != 3) throw new RuntimeException();",
            "if (Solution.maxInArray(new int[]{-5,-2,-9}) != -2) throw new RuntimeException();",
            "if (Solution.maxInArray(new int[]{7}) != 7) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_007",
        "prompt": "Implement method sumArray that returns the sum of all elements in an int array.",
        "method_signature": "public static int sumArray(int[] nums)",
        "tests": [
            "if (Solution.sumArray(new int[]{1,2,3}) != 6) throw new RuntimeException();",
            "if (Solution.sumArray(new int[]{}) != 0) throw new RuntimeException();",
            "if (Solution.sumArray(new int[]{-1,1}) != 0) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_008",
        "prompt": "Implement method isPalindrome that returns true if a string is a palindrome.",
        "method_signature": "public static boolean isPalindrome(String s)",
        "tests": [
            "if (!Solution.isPalindrome(\"level\")) throw new RuntimeException();",
            "if (Solution.isPalindrome(\"hello\")) throw new RuntimeException();",
            "if (!Solution.isPalindrome(\"\")) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_009",
        "prompt": "Implement method fibonacci where fibonacci(0)=0 and fibonacci(1)=1.",
        "method_signature": "public static int fibonacci(int n)",
        "tests": [
            "if (Solution.fibonacci(0) != 0) throw new RuntimeException();",
            "if (Solution.fibonacci(1) != 1) throw new RuntimeException();",
            "if (Solution.fibonacci(7) != 13) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_010",
        "prompt": "Implement method isPrime that returns true if n is a prime number.",
        "method_signature": "public static boolean isPrime(int n)",
        "tests": [
            "if (!Solution.isPrime(2)) throw new RuntimeException();",
            "if (Solution.isPrime(9)) throw new RuntimeException();",
            "if (Solution.isPrime(1)) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_011",
        "prompt": "Implement method secondLargest that returns the second largest distinct integer in an array. Assume it exists.",
        "method_signature": "public static int secondLargest(int[] nums)",
        "tests": [
            "if (Solution.secondLargest(new int[]{1,2,3}) != 2) throw new RuntimeException();",
            "if (Solution.secondLargest(new int[]{5,5,4,3}) != 4) throw new RuntimeException();",
            "if (Solution.secondLargest(new int[]{-1,-2,-3}) != -2) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_012",
        "prompt": "Implement method removeDuplicates that returns an int array with duplicates removed while preserving order.",
        "method_signature": "public static int[] removeDuplicates(int[] nums)",
        "tests": [
            "if (!java.util.Arrays.equals(Solution.removeDuplicates(new int[]{1,2,1,3,2}), new int[]{1,2,3})) throw new RuntimeException();",
            "if (!java.util.Arrays.equals(Solution.removeDuplicates(new int[]{}), new int[]{})) throw new RuntimeException();",
            "if (!java.util.Arrays.equals(Solution.removeDuplicates(new int[]{4,4,4}), new int[]{4})) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_013",
        "prompt": "Implement method areAnagrams that returns true if two strings are anagrams ignoring case.",
        "method_signature": "public static boolean areAnagrams(String a, String b)",
        "tests": [
            "if (!Solution.areAnagrams(\"listen\", \"silent\")) throw new RuntimeException();",
            "if (Solution.areAnagrams(\"hello\", \"world\")) throw new RuntimeException();",
            "if (!Solution.areAnagrams(\"Triangle\", \"Integral\")) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_014",
        "prompt": "Implement method mergeSorted that merges two sorted int arrays into one sorted array.",
        "method_signature": "public static int[] mergeSorted(int[] a, int[] b)",
        "tests": [
            "if (!java.util.Arrays.equals(Solution.mergeSorted(new int[]{1,3}, new int[]{2,4}), new int[]{1,2,3,4})) throw new RuntimeException();",
            "if (!java.util.Arrays.equals(Solution.mergeSorted(new int[]{}, new int[]{1}), new int[]{1})) throw new RuntimeException();",
            "if (!java.util.Arrays.equals(Solution.mergeSorted(new int[]{1,2}, new int[]{}), new int[]{1,2})) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_015",
        "prompt": "Implement method wordCount that returns the number of words separated by whitespace.",
        "method_signature": "public static int wordCount(String s)",
        "tests": [
            "if (Solution.wordCount(\"hello world\") != 2) throw new RuntimeException();",
            "if (Solution.wordCount(\"  one   two three  \") != 3) throw new RuntimeException();",
            "if (Solution.wordCount(\"\") != 0) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_016",
        "prompt": "Implement method gcd that returns the greatest common divisor of two positive integers.",
        "method_signature": "public static int gcd(int a, int b)",
        "tests": [
            "if (Solution.gcd(12, 18) != 6) throw new RuntimeException();",
            "if (Solution.gcd(7, 5) != 1) throw new RuntimeException();",
            "if (Solution.gcd(9, 9) != 9) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_017",
        "prompt": "Implement method countOccurrences that returns how many times x appears in an array.",
        "method_signature": "public static int countOccurrences(int[] nums, int x)",
        "tests": [
            "if (Solution.countOccurrences(new int[]{1,2,1,3}, 1) != 2) throw new RuntimeException();",
            "if (Solution.countOccurrences(new int[]{}, 1) != 0) throw new RuntimeException();",
            "if (Solution.countOccurrences(new int[]{2,2,2}, 2) != 3) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_018",
        "prompt": "Implement method rotateLeft that rotates an int array left by k positions.",
        "method_signature": "public static int[] rotateLeft(int[] nums, int k)",
        "tests": [
            "if (!java.util.Arrays.equals(Solution.rotateLeft(new int[]{1,2,3,4}, 1), new int[]{2,3,4,1})) throw new RuntimeException();",
            "if (!java.util.Arrays.equals(Solution.rotateLeft(new int[]{1,2,3,4}, 2), new int[]{3,4,1,2})) throw new RuntimeException();",
            "if (!java.util.Arrays.equals(Solution.rotateLeft(new int[]{1}, 5), new int[]{1})) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_019",
        "prompt": "Implement method longestWord that returns the longest word in a sentence. If tied, return the first one.",
        "method_signature": "public static String longestWord(String s)",
        "tests": [
            "if (!Solution.longestWord(\"a bb ccc\").equals(\"ccc\")) throw new RuntimeException();",
            "if (!Solution.longestWord(\"hello world\").equals(\"hello\")) throw new RuntimeException();",
            "if (!Solution.longestWord(\"x\").equals(\"x\")) throw new RuntimeException();",
        ],
    },
    {
        "task_id": "java_020",
        "prompt": "Implement method balancedParentheses that returns true if parentheses in a string are balanced.",
        "method_signature": "public static boolean balancedParentheses(String s)",
        "tests": [
            "if (!Solution.balancedParentheses(\"(())\")) throw new RuntimeException();",
            "if (Solution.balancedParentheses(\"(()\")) throw new RuntimeException();",
            "if (!Solution.balancedParentheses(\"a(b)c\")) throw new RuntimeException();",
        ],
    },
]


def clean_java_code(text):
    if text is None:
        return None

    s = str(text).strip()
    s = re.sub(r"^```java\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^```\s*", "", s)
    s = re.sub(r"\s*```$", "", s)

    match = re.search(r"(import\s+.*|public\s+class\s+Solution\s*\{.*|class\s+Solution\s*\{.*)", s, flags=re.DOTALL)
    if match:
        s = match.group(0).strip()

    if "class Solution" not in s:
        s = f"public class Solution {{\n{s}\n}}"

    s = re.sub(r"\bclass\s+Solution\b", "public class Solution", s, count=1)
    s = re.sub(r"public\s+public\s+class\s+Solution", "public class Solution", s)

    return s


def build_generation_prompt(task):
    return f"""
You are a Java code generation system.

Task:
{task["prompt"]}

Required method signature:
{task["method_signature"]}

Rules:
- Return only Java code.
- The code must define exactly one public class named Solution.
- The method must be public static.
- Use Java 11.
- Do not include markdown.
- Do not include explanations.
""".strip()


def build_repair_prompt(task, code, error):
    tests = "\n".join(task["tests"])

    return f"""
You are repairing Java code.

Task:
{task["prompt"]}

Required method signature:
{task["method_signature"]}

Current code:
{code}

Tests:
{tests}

Compilation or runtime error:
{error}

Repair rules:
- Return only corrected Java code.
- The code must define exactly one public class named Solution.
- The method must be public static.
- Use Java 11.
- Do not include markdown.
- Do not include explanations.
""".strip()


def call_model(client, model, prompt):
    start = time.time()
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    latency_ms = round((time.time() - start) * 1000, 3)
    raw = resp.choices[0].message.content
    return clean_java_code(raw), raw, latency_ms


def run_java_tests(code, tests, timeout=10):
    if not code:
        return {"pass": False, "error": "empty_code", "stdout": "", "stderr": ""}

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        solution_path = tmp_path / "Solution.java"
        main_path = tmp_path / "Main.java"

        solution_path.write_text(code, encoding="utf-8")

        main_code = "public class Main {\n"
        main_code += "  public static void main(String[] args) throws Exception {\n"
        for t in tests:
            main_code += "    " + t + "\n"
        main_code += "    System.out.println(\"ALL_TESTS_PASSED\");\n"
        main_code += "  }\n"
        main_code += "}\n"

        main_path.write_text(main_code, encoding="utf-8")

        compile_result = subprocess.run(
            ["javac", "Solution.java", "Main.java"],
            cwd=tmp,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if compile_result.returncode != 0:
            return {
                "pass": False,
                "error": compile_result.stderr.strip() or compile_result.stdout.strip(),
                "stdout": compile_result.stdout,
                "stderr": compile_result.stderr,
            }

        run_result = subprocess.run(
            ["java", "Main"],
            cwd=tmp,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        ok = run_result.returncode == 0 and "ALL_TESTS_PASSED" in run_result.stdout

        return {
            "pass": ok,
            "error": None if ok else (run_result.stderr.strip() or run_result.stdout.strip()),
            "stdout": run_result.stdout,
            "stderr": run_result.stderr,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="gpt-5.4-mini")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max_repairs", type=int, default=1)
    parser.add_argument("--base_url", type=str, default="https://yunwu.ai/v1")
    parser.add_argument("--out", type=str, default="runs/outputs/a2v_java/java_migration_20.jsonl")
    parser.add_argument("--summary_out", type=str, default="runs/outputs/a2v_java/java_migration_20_summary.md")
    args = parser.parse_args()

    api_key = os.environ.get("YUNWU_API_KEY")
    if not api_key:
        raise RuntimeError("YUNWU_API_KEY is not set.")

    client = OpenAI(api_key=api_key, base_url=args.base_url, timeout=120)
    tasks = TASKS[:args.limit]

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
            print(f"[PROGRESS] {idx + 1}/{len(tasks)} | {task['task_id']}")

            code, raw, gen_latency = call_model(client, args.model, build_generation_prompt(task))
            generation_latencies.append(gen_latency)

            result = run_java_tests(code, task["tests"])

            row = {
                "idx": idx,
                "task_id": task["task_id"],
                "prompt": task["prompt"],
                "method_signature": task["method_signature"],
                "model": args.model,
                "initial_code": code,
                "initial_raw_response": raw,
                "initial_pass": result["pass"],
                "initial_error": result["error"],
                "generation_latency_ms": gen_latency,
                "repair_attempted": False,
                "repair_code": None,
                "repair_raw_response": None,
                "repair_pass": False,
                "repair_error": None,
                "repair_latency_ms": None,
                "final_pass": result["pass"],
            }

            total += 1

            if result["pass"]:
                initial_pass += 1
                final_pass += 1
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                continue

            if args.max_repairs > 0:
                repair_attempted += 1
                row["repair_attempted"] = True

            current_code = code
            current_error = result["error"]

            for _ in range(args.max_repairs):
                repaired_code, repaired_raw, repair_latency = call_model(
                    client,
                    args.model,
                    build_repair_prompt(task, current_code, current_error),
                )
                repair_latencies.append(repair_latency)

                repaired_result = run_java_tests(repaired_code, task["tests"])

                row["repair_code"] = repaired_code
                row["repair_raw_response"] = repaired_raw
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

    avg_gen = sum(generation_latencies) / len(generation_latencies) if generation_latencies else 0.0
    avg_repair = sum(repair_latencies) / len(repair_latencies) if repair_latencies else 0.0

    lines = []
    lines.append("# Java Migration Experiment Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Model | {args.model} |")
    lines.append(f"| Total tasks | {total} |")
    lines.append(f"| Initial pass | {initial_pass}/{total} = {initial_pass / total:.3f} |")
    lines.append(f"| Repair attempted | {repair_attempted} |")
    lines.append(f"| Repair success | {repair_success}/{repair_attempted if repair_attempted else 1} = {repair_success / repair_attempted if repair_attempted else 0:.3f} |")
    lines.append(f"| Final pass | {final_pass}/{total} = {final_pass / total:.3f} |")
    lines.append(f"| Avg generation latency ms | {avg_gen:.1f} |")
    lines.append(f"| Avg repair latency ms | {avg_repair:.1f} |")

    summary_path = Path(args.summary_out)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\n[OK] output: {out_path}")
    print(f"[OK] summary: {summary_path}")


if __name__ == "__main__":
    main()
