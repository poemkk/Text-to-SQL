import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

try:
    from semantic_selector_common import (
        compact_selected,
        load_schema_info_by_db,
        make_item_candidates,
        read_jsonl,
        select_consensus_practical,
        select_oracle,
        source_rank,
        truncate_text,
        write_jsonl,
    )
except ImportError:
    from .semantic_selector_common import (
        compact_selected,
        load_schema_info_by_db,
        make_item_candidates,
        read_jsonl,
        select_consensus_practical,
        select_oracle,
        source_rank,
        truncate_text,
        write_jsonl,
    )


CRITERIA = [
    "selected_output",
    "filters",
    "aggregation_grouping",
    "join_schema_grounding",
    "ordering_limit_distinct",
    "result_plausibility",
]


def stable_key(*parts):
    payload = "\n---\n".join(str(part or "") for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def strip_code_fence(text):
    text = (text or "").strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


def parse_json_response(text):
    cleaned = strip_code_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def load_cache(path):
    cache = {}
    path = Path(path)
    if not path.exists():
        return cache

    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                print(f"[WARN] skip broken cache line {line_no}: {path}")
                continue

            key = row.get("cache_key")
            if key:
                cache[key] = row

    return cache


def append_cache(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def candidate_label(candidate):
    if not candidate:
        return "None"

    return (
        f"source={candidate.get('source')}; "
        f"variant={candidate.get('variant')}; "
        f"candidate_index={candidate.get('candidate_index')}; "
        f"exec_ok={candidate.get('exec_ok')}; "
        f"result_support={candidate.get('result_support')}; "
        f"non_empty={candidate.get('non_empty_result')}"
    )


def candidate_prompt_block(name, candidate, max_candidate_chars):
    text = candidate.get("selector_text") or ""
    return (
        f"Candidate {name} metadata:\n"
        f"{candidate_label(candidate)}\n\n"
        f"Candidate {name} evidence:\n"
        f"{truncate_text(text, max_candidate_chars)}"
    )


def build_pairwise_prompt(item, schema_info, candidate_a, candidate_b, max_schema_chars, max_candidate_chars):
    schema_text = schema_info.get("text", "") if isinstance(schema_info, dict) else ""
    schema_text = truncate_text(schema_text, max_schema_chars)

    return f"""
You are a strict Text-to-SQL semantic judge.

Task:
Compare Candidate A and Candidate B. Decide which SQL better answers the user's question.

Important rules:
- Use only the question, schema, SQL text, execution evidence, result shape/sample, result-consistency support, SQL structure, and repair trace.
- Do not use gold SQL or gold execution results.
- Do not prefer a candidate only because of its source/model name.
- Execution success is necessary, but executable SQL can still be semantically wrong.
- Return strict JSON only. Do not use markdown.

Question:
{item.get("question")}

Database id:
{item.get("db_id")}

Schema:
{schema_text}

{candidate_prompt_block("A", candidate_a, max_candidate_chars)}

{candidate_prompt_block("B", candidate_b, max_candidate_chars)}

Score each candidate from 0 to 2 on each criterion:
1. selected_output: selected columns/values match the question
2. filters: WHERE/HAVING conditions cover all constraints without adding unasked constraints
3. aggregation_grouping: COUNT/SUM/AVG/MIN/MAX/GROUP BY match the question
4. join_schema_grounding: tables, columns, and join path are semantically grounded in the schema
5. ordering_limit_distinct: ORDER BY/LIMIT/DISTINCT match the requested intent
6. result_plausibility: execution result shape/sample is plausible, but not used as sole evidence

Return exactly this JSON shape:
{{
  "scores": {{
    "selected_output": {{"A": 0, "B": 0, "evidence": "..."}},
    "filters": {{"A": 0, "B": 0, "evidence": "..."}},
    "aggregation_grouping": {{"A": 0, "B": 0, "evidence": "..."}},
    "join_schema_grounding": {{"A": 0, "B": 0, "evidence": "..."}},
    "ordering_limit_distinct": {{"A": 0, "B": 0, "evidence": "..."}},
    "result_plausibility": {{"A": 0, "B": 0, "evidence": "..."}}
  }},
  "winner": "A",
  "confidence": 0.0,
  "brief_reason": "one sentence"
}}
""".strip()


def score_total(judgment, side):
    scores = judgment.get("scores", {})
    total = 0.0

    for criterion in CRITERIA:
        value = scores.get(criterion, {}).get(side, 0)
        total += safe_float(value, 0.0)

    return total


def call_llm_judge_once(client, args, prompt):
    if args.api_mode == "responses":
        response = client.responses.create(
            model=args.model,
            input=[
                {
                    "role": "system",
                    "content": "You are a precise Text-to-SQL semantic judge that returns strict JSON.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )

        content = getattr(response, "output_text", None)

        if content is None:
            try:
                content = response.output[0].content[0].text
            except Exception:
                content = str(response)

        return parse_json_response(content), content

    response = client.chat.completions.create(
        model=args.model,
        messages=[
            {
                "role": "system",
                "content": "You are a precise Text-to-SQL semantic judge that returns strict JSON.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=args.temperature,
    )

    content = response.choices[0].message.content
    return parse_json_response(content), content


def call_llm_judge(client, args, prompt):
    last_error = None

    for attempt in range(args.max_retries + 1):
        try:
            return call_llm_judge_once(client, args, prompt)
        except Exception as e:
            last_error = e
            if attempt < args.max_retries:
                sleep_seconds = args.retry_sleep * (attempt + 1)
                print(f"[WARN] LLM call failed, retry {attempt + 1}/{args.max_retries}: {e}")
                time.sleep(sleep_seconds)

    raise RuntimeError(f"LLM judge failed after retries: {last_error}")


def failed_judgment(error):
    return {
        "scores": {
            "selected_output": {"A": 0, "B": 0, "evidence": "LLM call failed."},
            "filters": {"A": 0, "B": 0, "evidence": "LLM call failed."},
            "aggregation_grouping": {"A": 0, "B": 0, "evidence": "LLM call failed."},
            "join_schema_grounding": {"A": 0, "B": 0, "evidence": "LLM call failed."},
            "ordering_limit_distinct": {"A": 0, "B": 0, "evidence": "LLM call failed."},
            "result_plausibility": {"A": 0, "B": 0, "evidence": "LLM call failed."},
        },
        "winner": "A",
        "confidence": 0.0,
        "brief_reason": f"LLM call or JSON parse failed: {str(error)}",
        "failed": True,
    }


def executable_alternatives(pool, baseline, top_k):
    if not baseline:
        return []

    candidates = [
        cand for cand in pool
        if cand is not baseline
        and cand.get("exec_ok")
        and cand.get("sql")
    ]

    different = [
        cand for cand in candidates
        if cand.get("result_key") != baseline.get("result_key")
        or cand.get("sql") != baseline.get("sql")
    ]

    ranked = sorted(
        different,
        key=lambda cand: (
            -int(cand.get("result_support") or 0),
            0 if cand.get("non_empty_result") else 1,
            source_rank(cand.get("source")),
            0 if cand.get("variant") == "original" else 1,
            cand.get("order", 999999),
        ),
    )

    return ranked[:top_k]


def should_send_case_to_llm(pool, baseline, alternatives, min_alternatives):
    if not baseline or not baseline.get("exec_ok"):
        return False

    if len(alternatives) < min_alternatives:
        return False

    result_keys = {
        cand.get("result_key")
        for cand in pool
        if cand.get("exec_ok")
    }

    return len(result_keys) >= 2


def make_cache_key(args, item, current, alternative):
    return stable_key(
        "llm_pairwise_correction_v2",
        args.model,
        args.api_mode,
        args.min_confidence,
        args.score_margin,
        args.max_schema_chars,
        args.max_candidate_chars,
        item.get("idx"),
        item.get("db_id"),
        item.get("question"),
        current.get("sql"),
        alternative.get("sql"),
        current.get("result_key"),
        alternative.get("result_key"),
    )


def judge_case(item, schema_info, pool, baseline, alternatives, client, cache, args):
    current = baseline
    judgments = []
    api_calls = 0
    failures = 0

    for alternative in alternatives:
        key = make_cache_key(args, item, current, alternative)

        if key in cache and not args.force_refresh_cache:
            cached = cache[key]
            judgment = cached["judgment"]
            raw_response = cached.get("raw_response")
            from_cache = True
        else:
            prompt = build_pairwise_prompt(
                item=item,
                schema_info=schema_info,
                candidate_a=current,
                candidate_b=alternative,
                max_schema_chars=args.max_schema_chars,
                max_candidate_chars=args.max_candidate_chars,
            )

            try:
                judgment, raw_response = call_llm_judge(client, args, prompt)
            except Exception as e:
                judgment = failed_judgment(e)
                raw_response = ""
                failures += 1
                print(f"[WARN] failed judgment idx={item.get('idx')} db={item.get('db_id')}: {e}")

            cached = {
                "cache_key": key,
                "cache_version": "llm_pairwise_correction_v2",
                "model": args.model,
                "api_mode": args.api_mode,
                "min_confidence": args.min_confidence,
                "score_margin": args.score_margin,
                "idx": item.get("idx"),
                "db_id": item.get("db_id"),
                "question": item.get("question"),
                "candidate_a": candidate_label(current),
                "candidate_b": candidate_label(alternative),
                "judgment": judgment,
                "raw_response": raw_response,
            }

            cache[key] = cached
            append_cache(args.cache, cached)
            api_calls += 1
            from_cache = False

            if args.sleep:
                time.sleep(args.sleep)

        total_a = score_total(judgment, "A")
        total_b = score_total(judgment, "B")
        winner = str(judgment.get("winner", "")).strip()
        confidence = safe_float(judgment.get("confidence"), 0.0)

        accepted_switch = (
            winner == "B"
            and confidence >= args.min_confidence
            and total_b >= total_a + args.score_margin
        )

        judgments.append({
            "candidate_a": compact_selected(current),
            "candidate_b": compact_selected(alternative),
            "winner": winner,
            "confidence": confidence,
            "score_a": total_a,
            "score_b": total_b,
            "accepted_switch": accepted_switch,
            "from_cache": from_cache,
            "brief_reason": judgment.get("brief_reason"),
            "judgment": judgment,
        })

        if accepted_switch:
            current = alternative

    return current, judgments, api_calls, failures


def summarize_records(records, key):
    total = len(records)
    selected = [row[key] for row in records if row.get(key)]
    labeled = [cand for cand in selected if cand.get("label_available")]

    return {
        "examples": total,
        "labeled": len(labeled),
        "exec_rate": sum(1 for cand in selected if cand.get("exec_ok")) / total if total else 0.0,
        "accuracy": (
            sum(1 for cand in labeled if cand.get("exec_correct")) / len(labeled)
            if labeled
            else 0.0
        ),
        "correct": sum(1 for cand in labeled if cand.get("exec_correct")),
        "by_source": dict(Counter(cand.get("source") for cand in selected)),
        "by_variant": dict(Counter(cand.get("variant") for cand in selected)),
    }


def write_summary(path, summaries, stats, args):
    oracle_acc = summaries["oracle"]["accuracy"]

    lines = [
        "# LLM Pairwise Correction Selector Summary",
        "",
        f"- input: `{args.in_file}`",
        f"- model: `{args.model}`",
        f"- api mode: `{args.api_mode}`",
        f"- base url: `{args.base_url}`",
        f"- cache: `{args.cache}`",
        f"- force refresh cache: `{args.force_refresh_cache}`",
        f"- min confidence: {args.min_confidence}",
        f"- score margin: {args.score_margin}",
        f"- top k alternatives: {args.top_k_alternatives}",
        f"- max cases: {args.max_cases}",
        "",
        "## Main Result",
        "",
        "| Selector | Examples | Labeled | Exec. Rate | Exec. Acc. | Correct | Oracle Gap |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for name in ["practical_baseline", "llm_pairwise_correction", "oracle"]:
        summary = summaries[name]
        lines.append(
            f"| {name} | {summary['examples']} | {summary['labeled']} | "
            f"{summary['exec_rate']:.3f} | {summary['accuracy']:.3f} | "
            f"{summary['correct']} | {oracle_acc - summary['accuracy']:.3f} |"
        )

    lines.extend([
        "",
        "## Correction Stats",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ])

    for key in [
        "candidate_cases",
        "oracle_gap_cases",
        "candidate_cases_cover_oracle_gap",
        "candidate_cases_baseline_correct",
        "candidate_cases_baseline_wrong",
        "llm_cases",
        "api_calls",
        "cache_hits_or_reuses",
        "new_cache_entries",
        "llm_failures",
        "switches",
        "switches_correct",
        "switches_wrong",
    ]:
        lines.append(f"| {key} | {stats.get(key, 0)} |")

    for name in ["practical_baseline", "llm_pairwise_correction", "oracle"]:
        lines.extend([
            "",
            f"## Selected By Source: {name}",
            "",
            "| Source | Count |",
            "|---|---:|",
        ])

        for source, count in sorted(summaries[name]["by_source"].items()):
            lines.append(f"| {source} | {count} |")

        lines.extend([
            "",
            f"## Selected By Variant: {name}",
            "",
            "| Variant | Count |",
            "|---|---:|",
        ])

        for variant, count in sorted(summaries[name]["by_variant"].items()):
            lines.append(f"| {variant} | {count} |")

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Conservative LLM pairwise correction layer over the strong-repair practical selector."
        )
    )

    parser.add_argument("--in_file", default="runs/outputs/a2v/repaired_strong_spider1034_full.jsonl")
    parser.add_argument("--tables", default="data/spider/tables.json")

    parser.add_argument(
        "--out",
        default="runs/outputs/a2v/semantic_selector/selected_llm_pairwise_correction_strong_repair.jsonl",
    )

    parser.add_argument(
        "--summary_out",
        default="runs/outputs/a2v/semantic_selector/summary_llm_pairwise_correction_strong_repair.md",
    )

    parser.add_argument(
        "--cache",
        default="runs/outputs/a2v/semantic_selector/cache_llm_pairwise_correction_v2.jsonl",
    )

    parser.add_argument("--base_url", default="https://yunwu.ai/v1")
    parser.add_argument("--api_key_env", default="YUNWU_API_KEY")
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--api_mode", choices=["chat", "responses"], default="responses")
    parser.add_argument("--temperature", type=float, default=0.0)

    parser.add_argument("--top_k_alternatives", type=int, default=3)
    parser.add_argument("--min_alternatives", type=int, default=1)
    parser.add_argument("--min_confidence", type=float, default=0.72)
    parser.add_argument("--score_margin", type=float, default=1.0)

    parser.add_argument("--max_schema_chars", type=int, default=4200)
    parser.add_argument("--max_candidate_chars", type=int, default=2600)
    parser.add_argument("--max_cases", type=int, default=None)

    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--max_retries", type=int, default=3)
    parser.add_argument("--retry_sleep", type=float, default=2.0)

    parser.add_argument(
        "--force_refresh_cache",
        action="store_true",
        help="Ignore existing cache and call the LLM again.",
    )

    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Prepare candidate cases and summaries without calling the LLM.",
    )

    args = parser.parse_args()

    rows = read_jsonl(args.in_file)
    schema_by_db = load_schema_info_by_db(args.tables)
    cache = load_cache(args.cache)

    client = None
    if not args.dry_run:
        api_key = os.environ.get(args.api_key_env)
        if not api_key:
            raise RuntimeError(f"{args.api_key_env} is not set.")

        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=args.base_url)

    output_rows = []
    records = []
    stats = Counter()

    for item in rows:
        schema_info = schema_by_db.get(item.get("db_id"), {})
        pool = make_item_candidates(item, schema_by_db, max_schema_chars=args.max_schema_chars)

        baseline = select_consensus_practical(pool)
        oracle = select_oracle(pool)
        alternatives = executable_alternatives(pool, baseline, args.top_k_alternatives)

        should_call = should_send_case_to_llm(
            pool=pool,
            baseline=baseline,
            alternatives=alternatives,
            min_alternatives=args.min_alternatives,
        )

        baseline_correct = bool(
            baseline
            and baseline.get("label_available")
            and baseline.get("exec_correct")
        )

        oracle_correct = bool(
            oracle
            and oracle.get("label_available")
            and oracle.get("exec_correct")
        )

        selected = baseline
        judgments = []

        if oracle_correct and not baseline_correct:
            stats["oracle_gap_cases"] += 1

        if should_call:
            stats["candidate_cases"] += 1

            if baseline_correct:
                stats["candidate_cases_baseline_correct"] += 1
            else:
                stats["candidate_cases_baseline_wrong"] += 1

            if oracle_correct and not baseline_correct:
                stats["candidate_cases_cover_oracle_gap"] += 1

        if should_call and not args.dry_run:
            if args.max_cases is None or stats["llm_cases"] < args.max_cases:
                before_cache_size = len(cache)

                selected, judgments, api_calls, failures = judge_case(
                    item=item,
                    schema_info=schema_info,
                    pool=pool,
                    baseline=baseline,
                    alternatives=alternatives,
                    client=client,
                    cache=cache,
                    args=args,
                )

                stats["llm_cases"] += 1
                stats["api_calls"] += api_calls
                stats["cache_hits_or_reuses"] += max(0, len(judgments) - api_calls)
                stats["new_cache_entries"] += max(0, len(cache) - before_cache_size)
                stats["llm_failures"] += failures

        if selected is not baseline:
            stats["switches"] += 1

            if selected and baseline and selected.get("label_available") and baseline.get("label_available"):
                if selected.get("exec_correct") and not baseline.get("exec_correct"):
                    stats["switches_correct"] += 1
                elif not selected.get("exec_correct") and baseline.get("exec_correct"):
                    stats["switches_wrong"] += 1

        output_item = dict(item)
        output_item["selected_practical_baseline"] = compact_selected(baseline)
        output_item["selected_llm_pairwise_correction"] = compact_selected(selected)
        output_item["selected_oracle"] = compact_selected(oracle)

        output_item["llm_pairwise_attempted"] = bool(judgments)
        output_item["llm_pairwise_case_candidate"] = should_call
        output_item["llm_pairwise_judgments"] = judgments
        output_item["llm_pairwise_alternatives"] = [
            compact_selected(candidate)
            for candidate in alternatives
        ]

        output_rows.append(output_item)

        records.append({
            "practical_baseline": baseline,
            "llm_pairwise_correction": selected,
            "oracle": oracle,
        })

    summaries = {
        "practical_baseline": summarize_records(records, "practical_baseline"),
        "llm_pairwise_correction": summarize_records(records, "llm_pairwise_correction"),
        "oracle": summarize_records(records, "oracle"),
    }

    write_jsonl(args.out, output_rows)
    write_summary(args.summary_out, summaries, stats, args)

    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    print(json.dumps(dict(stats), ensure_ascii=False, indent=2))
    print(f"[OK] output: {args.out}")
    print(f"[OK] summary: {args.summary_out}")

    if args.dry_run:
        print("[DRY RUN] No LLM calls were made.")


if __name__ == "__main__":
    main()