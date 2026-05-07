import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

try:
    from semantic_selector_common import (
        compact_selected,
        has_hard_semantic_choice,
        load_schema_info_by_db,
        make_item_candidates,
        read_jsonl,
        select_consensus_practical,
        select_oracle,
        select_rule_priority,
        source_rank,
        write_jsonl,
    )
except ImportError:
    from .semantic_selector_common import (
        compact_selected,
        has_hard_semantic_choice,
        load_schema_info_by_db,
        make_item_candidates,
        read_jsonl,
        select_consensus_practical,
        select_oracle,
        select_rule_priority,
        source_rank,
        write_jsonl,
    )


def choose_device(requested):
    if requested != "auto":
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


@torch.no_grad()
def score_texts(model, tokenizer, texts, device, batch_size, max_length):
    scores = []
    model.eval()

    for start in range(0, len(texts), batch_size):
        batch_texts = texts[start:start + batch_size]
        encoded = tokenizer(
            batch_texts,
            truncation=True,
            max_length=max_length,
            padding=True,
            return_tensors="pt",
        )
        encoded = {key: value.to(device) for key, value in encoded.items()}
        batch_scores = model(**encoded).logits.view(-1).detach().cpu().tolist()
        scores.extend(float(score) for score in batch_scores)

    return scores


def select_by_semantic_score(pool):
    if not pool:
        return None
    executable = [cand for cand in pool if cand.get("exec_ok")]
    candidates = executable if executable else pool
    return sorted(
        candidates,
        key=lambda cand: (
            -float(cand.get("semantic_selector_score", -1e9)),
            source_rank(cand.get("source")),
            0 if cand.get("variant") == "original" else 1,
            cand.get("order", 999999),
        ),
    )[0]


def select_hybrid_semantic(pool, margin):
    """
    Conservative hybrid selector.

    Use the practical consensus selector as the default and switch only when
    the semantic ranker gives another executable candidate a clear margin.
    This keeps the learned model from damaging strong rule/consensus baselines.
    """
    base = select_consensus_practical(pool)
    learned = select_by_semantic_score(pool)

    if base is None:
        return learned
    if learned is None:
        return base
    if learned is base:
        return base

    base_score = float(base.get("semantic_selector_score", -1e9))
    learned_score = float(learned.get("semantic_selector_score", -1e9))

    if learned_score >= base_score + margin:
        return learned
    return base


def summarize_method(records, method):
    total = len(records)
    label_rows = [row for row in records if row[method] and row[method].get("label_available")]
    hard_rows = [row for row in records if row.get("hard_semantic_choice")]
    hard_labeled = [row for row in hard_rows if row[method] and row[method].get("label_available")]
    by_source = Counter(row[method].get("source") for row in records if row[method])
    by_variant = Counter(row[method].get("variant") for row in records if row[method])

    return {
        "examples": total,
        "labeled_examples": len(label_rows),
        "exec_rate": (
            sum(1 for row in records if row[method] and row[method].get("exec_ok")) / total
            if total
            else 0.0
        ),
        "execution_accuracy": (
            sum(1 for row in label_rows if row[method].get("exec_correct")) / len(label_rows)
            if label_rows
            else 0.0
        ),
        "correct": sum(1 for row in label_rows if row[method].get("exec_correct")),
        "hard_examples": len(hard_rows),
        "hard_accuracy": (
            sum(1 for row in hard_labeled if row[method].get("exec_correct")) / len(hard_labeled)
            if hard_labeled
            else 0.0
        ),
        "hard_correct": sum(1 for row in hard_labeled if row[method].get("exec_correct")),
        "by_source": dict(by_source),
        "by_variant": dict(by_variant),
    }


def write_summary(path, summaries, args):
    oracle_acc = summaries.get("oracle", {}).get("execution_accuracy", 0.0)
    lines = [
        "# Semantic Selector Summary",
        "",
        f"- input: `{args.in_file}`",
        f"- model: `{args.model_dir}`",
        f"- max_length: {args.max_length}",
        f"- hybrid margin: {args.hybrid_margin}",
    ]
    if args.fold_metadata and args.eval_fold is not None:
        lines.append(f"- eval fold: {args.eval_fold}")
        lines.append(f"- fold metadata: `{args.fold_metadata}`")
    lines.extend([
        "",
        "| Selector | Examples | Labeled | Exec. Rate | Exec. Acc. | Correct | Oracle Gap | Hard Acc. | Hard Correct |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])

    order = [
        "rule_priority",
        "consensus_practical",
        "semantic_selector",
        "hybrid_semantic",
        "oracle",
    ]
    for name in order:
        summary = summaries[name]
        gap = oracle_acc - summary["execution_accuracy"]
        lines.append(
            f"| {name} | {summary['examples']} | {summary['labeled_examples']} | "
            f"{summary['exec_rate']:.3f} | {summary['execution_accuracy']:.3f} | "
            f"{summary['correct']} | {gap:.3f} | {summary['hard_accuracy']:.3f} | "
            f"{summary['hard_correct']} |"
        )

    for name in order:
        lines.append("")
        lines.append(f"## Selected By Source: {name}")
        lines.append("")
        lines.append("| Source | Count |")
        lines.append("|---|---:|")
        for source, count in sorted(summaries[name]["by_source"].items()):
            lines.append(f"| {source} | {count} |")

        lines.append("")
        lines.append(f"## Selected By Variant: {name}")
        lines.append("")
        lines.append("| Variant | Count |")
        lines.append("|---|---:|")
        for variant, count in sorted(summaries[name]["by_variant"].items()):
            lines.append(f"| {variant} | {count} |")

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Apply a trained semantic SQL selector to a candidate pool."
    )
    parser.add_argument(
        "--in_file",
        default="runs/outputs/a2v/multillm/scored_multillm_spider1034.jsonl",
    )
    parser.add_argument("--tables", default="data/spider/tables.json")
    parser.add_argument("--model_dir", required=True)
    parser.add_argument(
        "--out",
        default="runs/outputs/a2v/semantic_selector/selected_semantic_selector.jsonl",
    )
    parser.add_argument(
        "--summary_out",
        default="runs/outputs/a2v/semantic_selector/semantic_selector_summary.md",
    )
    parser.add_argument("--max_schema_chars", type=int, default=4500)
    parser.add_argument("--max_length", type=int, default=512)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--hybrid_margin",
        type=float,
        default=0.25,
        help="Switch from consensus to semantic top only if score gain is at least this margin.",
    )
    parser.add_argument(
        "--fold_metadata",
        default=None,
        help="Optional metadata.json from 18_build_semantic_selector_data.py for strict DB-fold inference.",
    )
    parser.add_argument(
        "--eval_fold",
        type=int,
        default=None,
        help="When fold_metadata is given, evaluate only rows whose db_id belongs to this fold.",
    )
    args = parser.parse_args()

    rows = read_jsonl(args.in_file)
    if args.fold_metadata and args.eval_fold is not None:
        metadata = json.loads(Path(args.fold_metadata).read_text(encoding="utf-8"))
        db_to_fold = metadata.get("db_to_fold", {})
        rows = [
            row for row in rows
            if db_to_fold.get(row.get("db_id")) == args.eval_fold
        ]
        print(f"[OK] fold-filtered rows: {len(rows)} for fold {args.eval_fold}")

    schema_by_db = load_schema_info_by_db(args.tables)
    device = choose_device(args.device)

    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, use_fast=True)
    model = AutoModelForSequenceClassification.from_pretrained(args.model_dir)
    model.to(device)

    output_rows = []
    summary_records = []

    for item in rows:
        pool = make_item_candidates(
            item,
            schema_by_db=schema_by_db,
            max_schema_chars=args.max_schema_chars,
        )
        texts = [candidate["selector_text"] for candidate in pool]
        scores = score_texts(
            model=model,
            tokenizer=tokenizer,
            texts=texts,
            device=device,
            batch_size=args.batch_size,
            max_length=args.max_length,
        )
        for candidate, score in zip(pool, scores):
            candidate["semantic_selector_score"] = score

        selected_semantic = select_by_semantic_score(pool)
        selected_rule = select_rule_priority(pool)
        selected_consensus = select_consensus_practical(pool)
        selected_hybrid = select_hybrid_semantic(pool, args.hybrid_margin)
        selected_oracle = select_oracle(pool)

        output_item = dict(item)
        output_item["semantic_selector_scores"] = [
            {
                "candidate_index": cand.get("candidate_index"),
                "source": cand.get("source"),
                "variant": cand.get("variant"),
                "score": cand.get("semantic_selector_score"),
                "exec_ok": cand.get("exec_ok"),
                "exec_correct": cand.get("exec_correct"),
                "result_support": cand.get("result_support"),
                "non_empty_result": cand.get("non_empty_result"),
            }
            for cand in sorted(
                pool,
                key=lambda cand: -float(cand.get("semantic_selector_score", -1e9)),
            )
        ]
        output_item["selected_semantic_selector"] = compact_selected(selected_semantic)
        output_item["selected_hybrid_semantic"] = compact_selected(selected_hybrid)
        output_item["selected_rule_priority"] = compact_selected(selected_rule)
        output_item["selected_consensus_practical"] = compact_selected(selected_consensus)
        output_item["selected_oracle"] = compact_selected(selected_oracle)
        output_rows.append(output_item)

        summary_records.append({
            "hard_semantic_choice": has_hard_semantic_choice(pool),
            "semantic_selector": selected_semantic,
            "hybrid_semantic": selected_hybrid,
            "rule_priority": selected_rule,
            "consensus_practical": selected_consensus,
            "oracle": selected_oracle,
        })

    write_jsonl(args.out, output_rows)

    summaries = {
        name: summarize_method(summary_records, name)
        for name in [
            "rule_priority",
            "consensus_practical",
            "semantic_selector",
            "hybrid_semantic",
            "oracle",
        ]
    }
    write_summary(args.summary_out, summaries, args)

    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    print(f"[OK] output: {args.out}")
    print(f"[OK] summary: {args.summary_out}")


if __name__ == "__main__":
    main()
