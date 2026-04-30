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


def clean_java_code(text):
    if text is None:
        return ""

    s = str(text).strip()

    s = re.sub(r"^```java\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^```\s*", "", s)
    s = re.sub(r"\s*```$", "", s)

    candidates = []
    for marker in ["import ", "public class Problem", "class Problem"]:
        idx = s.find(marker)
        if idx != -1:
            candidates.append(idx)

    if candidates:
        s = s[min(candidates):]

    s = re.sub(r"^\s*import\s+org\.javatuples\.\*;\s*\n", "", s, flags=re.MULTILINE)
    s = re.sub(r"public\s+public\s+class\s+Problem", "public class Problem", s)

    return s.strip()


def build_generation_prompt(task):
    return f"""
You are solving a MultiPL-E Java task.

Below is an incomplete Java program and the official test code.

Incomplete Java prompt:
{task["prompt"]}

Official test code:
{task["tests"]}

Your task:
Return a complete Java 11 program that passes the official tests.

Strict rules:
- Return only Java code.
- The code must define class Problem.
- The code must include the target method implementation.
- The code must include a public static void main(String[] args) method that runs the provided tests.
- Do not include markdown.
- Do not include explanations.
- Do not use external libraries. Use only Java standard library.
""".strip()


def build_repair_prompt(task, current_code, error):
    return f"""
You are repairing a Java solution for a MultiPL-E Java task.

The current Java code failed compilation or tests.

Original incomplete Java prompt:
{task["prompt"]}

Official test code:
{task["tests"]}

Current Java code:
{current_code}

Compilation or runtime error:
{error}

Repair rules:
- Return the full corrected Java 11 code.
- The code must define class Problem.
- The code must include the target method implementation.
- The code must include a public static void main(String[] args) method that runs the provided tests.
- The code must compile with javac.
- Do not include markdown.
- Do not include explanations.
- Do not use external libraries. Use only Java standard library.
""".strip()


def call_model(client, model, prompt, retries=2, sleep=0.5):
    last_error = None

    for attempt in range(1, retries + 2):
        start = time.time()

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            latency_ms = round((time.time() - start) * 1000, 3)
            raw = resp.choices[0].message.content
            code = clean_java_code(raw)

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
                    "code": "",
                    "raw_response": None,
                    "latency_ms": latency_ms,
                    "error": last_error,
                    "attempts": attempt,
                }


def ensure_main_if_missing(task, code):
    code = clean_java_code(code)

    if "class Problem" not in code:
        return clean_java_code(task["prompt"] + "\n" + code + "\n" + task["tests"])

    if "public static void main" in code or "static void main" in code:
        return code

    last_brace = code.rfind("}")
    if last_brace == -1:
        return clean_java_code(task["prompt"] + "\n" + code + "\n" + task["tests"])

    test_code = task["tests"].strip()

    if test_code.startswith("}"):
        test_code = test_code[1:].strip()

    return code[:last_brace] + "\n" + test_code + "\n" + code[last_brace:]


def run_java_code(full_code, timeout=10):
    full_code = clean_java_code(full_code)

    if not full_code:
        return {
            "pass": False,
            "error": "empty_code",
            "stdout": "",
            "stderr": "empty_code",
        }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        java_path = tmp_path / "Problem.java"
        java_path.write_text(full_code, encoding="utf-8")

        try:
            compile_result = subprocess.run(
                ["javac", "Problem.java"],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "pass": False,
                "error": "compile_timeout",
                "stdout": "",
                "stderr": "compile_timeout",
            }

        if compile_result.returncode != 0:
            return {
                "pass": False,
                "error": compile_result.stderr.strip() or compile_result.stdout.strip(),
                "stdout": compile_result.stdout,
                "stderr": compile_result.stderr,
            }

        try:
            run_result = subprocess.run(
                ["java", "-ea", "Problem"],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "pass": False,
                "error": "runtime_timeout",
                "stdout": "",
                "stderr": "runtime_timeout",
            }

        ok = run_result.returncode == 0

        return {
            "pass": ok,
            "error": None if ok else (run_result.stderr.strip() or run_result.stdout.strip()),
            "stdout": run_result.stdout,
            "stderr": run_result.stderr,
        }


def read_done_indices(out_path):
    p = Path(out_path)
    done = set()

    if not p.exists():
        return done

    with p.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                done.add(row["idx"])
            except Exception:
                continue

    return done


def read_existing_rows(out_path):
    p = Path(out_path)
    rows = []

    if not p.exists():
        return rows

    with p.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass

    return rows


def summarize_rows(rows, model, config):
    total = len(rows)
    initial_pass = sum(1 for r in rows if r.get("initial_pass"))
    final_pass = sum(1 for r in rows if r.get("final_pass"))
    generation_errors = sum(1 for r in rows if r.get("generation_error"))

    repair_attempted = sum(1 for r in rows if r.get("repair_attempted"))
    repair_api_calls = sum(len(r.get("repair_rounds", [])) for r in rows)
    repair_success = sum(
        1
        for r in rows
        if r.get("repair_attempted")
        and r.get("final_pass")
        and not r.get("initial_pass")
    )

    gen_lats = [
        r.get("generation_latency_ms")
        for r in rows
        if r.get("generation_latency_ms") is not None
    ]

    repair_lats = []
    for r in rows:
        for rr in r.get("repair_rounds", []):
            if rr.get("repair_latency_ms") is not None:
                repair_lats.append(rr.get("repair_latency_ms"))

    avg_gen = sum(gen_lats) / len(gen_lats) if gen_lats else 0.0
    avg_repair = sum(repair_lats) / len(repair_lats) if repair_lats else 0.0

    initial_rate = initial_pass / total if total else 0.0
    final_rate = final_pass / total if total else 0.0
    repair_success_rate = repair_success / repair_attempted if repair_attempted else 0.0

    lines = []
    lines.append("# MultiPL-E Java Migration Experiment Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Dataset | {config} |")
    lines.append(f"| Model | {model} |")
    lines.append(f"| Total tasks | {total} |")
    lines.append(f"| Initial pass | {initial_pass}/{total} = {initial_rate:.3f} |")
    lines.append(f"| Repair attempted | {repair_attempted} |")
    lines.append(f"| Repair API calls | {repair_api_calls} |")
    lines.append(
        f"| Repair success | {repair_success}/{repair_attempted if repair_attempted else 1} = {repair_success_rate:.3f} |"
    )
    lines.append(f"| Final pass | {final_pass}/{total} = {final_rate:.3f} |")
    lines.append(f"| Generation errors | {generation_errors} |")
    lines.append(f"| Avg generation latency ms | {avg_gen:.1f} |")
    lines.append(f"| Avg repair latency ms | {avg_repair:.1f} |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="nuprl/MultiPL-E")
    parser.add_argument("--config", type=str, default="humaneval-java")
    parser.add_argument("--split", type=str, default="test")
    parser.add_argument("--model", type=str, default="gpt-5.4-mini")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max_repairs", type=int, default=1)
    parser.add_argument("--base_url", type=str, default="https://yunwu.ai/v1")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--progress_every", type=int, default=1)
    parser.add_argument("--java_timeout", type=int, default=10)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v_java/multiple_java_gpt_20_v2.jsonl",
    )
    parser.add_argument(
        "--summary_out",
        type=str,
        default="runs/outputs/a2v_java/multiple_java_gpt_20_v2_summary.md",
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

    print(f"[LOAD] loading MultiPL-E {args.config}...")
    ds = load_dataset(args.dataset, args.config, split=args.split)

    if args.limit:
        ds = ds.select(range(min(args.limit, len(ds))))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done_indices = read_done_indices(out_path) if args.resume else set()
    rows_for_summary = read_existing_rows(out_path) if args.resume else []

    mode = "a" if args.resume else "w"

    print(f"[INFO] model: {args.model}")
    print(f"[INFO] config: {args.config}")
    print(f"[INFO] limit: {len(ds)}")
    print(f"[INFO] resume: {args.resume}")
    print(f"[INFO] already done: {len(done_indices)}")

    start_all = time.time()

    with out_path.open(mode, encoding="utf-8") as out:
        for idx, task in enumerate(ds):
            if idx in done_indices:
                continue

            if idx == 0 or (idx + 1) % args.progress_every == 0:
                elapsed = time.time() - start_all
                print(f"[PROGRESS] {idx + 1}/{len(ds)} | {task['name']} | elapsed={elapsed:.1f}s")

            gen_result = call_model(
                client=client,
                model=args.model,
                prompt=build_generation_prompt(task),
                retries=args.retries,
                sleep=args.sleep,
            )

            initial_code = ensure_main_if_missing(task, gen_result["code"])
            initial_result = run_java_code(initial_code, timeout=args.java_timeout)

            row = {
                "idx": idx,
                "name": task["name"],
                "language": task["language"],
                "model": args.model,
                "config": args.config,
                "prompt": task["prompt"],
                "tests": task["tests"],
                "initial_code": initial_code,
                "initial_raw_response": gen_result["raw_response"],
                "generation_error": gen_result["error"],
                "generation_attempts": gen_result["attempts"],
                "generation_latency_ms": gen_result["latency_ms"],
                "initial_pass": initial_result["pass"],
                "initial_error": initial_result["error"],
                "repair_attempted": False,
                "repair_rounds": [],
                "final_code": initial_code,
                "final_pass": initial_result["pass"],
                "final_error": initial_result["error"],
            }

            if not initial_result["pass"] and args.max_repairs > 0:
                row["repair_attempted"] = True

                current_code = initial_code
                current_error = initial_result["error"]

                for repair_round in range(1, args.max_repairs + 1):
                    repair_result = call_model(
                        client=client,
                        model=args.model,
                        prompt=build_repair_prompt(task, current_code, current_error),
                        retries=args.retries,
                        sleep=args.sleep,
                    )

                    repaired_code = ensure_main_if_missing(task, repair_result["code"])
                    repaired_result = run_java_code(repaired_code, timeout=args.java_timeout)

                    row["repair_rounds"].append({
                        "round": repair_round,
                        "repair_code": repaired_code,
                        "repair_raw_response": repair_result["raw_response"],
                        "repair_generation_error": repair_result["error"],
                        "repair_attempts": repair_result["attempts"],
                        "repair_latency_ms": repair_result["latency_ms"],
                        "repair_pass": repaired_result["pass"],
                        "repair_error": repaired_result["error"],
                    })

                    row["final_code"] = repaired_code
                    row["final_pass"] = repaired_result["pass"]
                    row["final_error"] = repaired_result["error"]

                    if repaired_result["pass"]:
                        break

                    current_code = repaired_code
                    current_error = repaired_result["error"]

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            rows_for_summary.append(row)

    summary_text = summarize_rows(rows_for_summary, args.model, args.config)

    summary_path = Path(args.summary_out)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary_text, encoding="utf-8")

    print(summary_text)
    print(f"\n[OK] output: {out_path}")
    print(f"[OK] summary: {summary_path}")


if __name__ == "__main__":
    main()