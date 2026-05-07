import argparse
import json
import random
from collections import Counter
from pathlib import Path

try:
    from semantic_selector_common import (
        assign_db_folds,
        build_pairwise_records,
        build_pool,
        has_hard_semantic_choice,
        load_schema_info_by_db,
        make_item_candidates,
        read_jsonl,
        write_jsonl,
    )
except ImportError:
    from .semantic_selector_common import (
        assign_db_folds,
        build_pairwise_records,
        build_pool,
        has_hard_semantic_choice,
        load_schema_info_by_db,
        make_item_candidates,
        read_jsonl,
        write_jsonl,
    )


def summarize_rows(rows, schema_by_db, max_schema_chars):
    summary = Counter()
    for row in rows:
        pool = make_item_candidates(row, schema_by_db, max_schema_chars=max_schema_chars)
        summary["examples"] += 1
        summary["candidates"] += len(pool)
        if any(c.get("label_available") for c in pool):
            summary["examples_with_labels"] += 1
        if any(c.get("label_available") and c.get("exec_correct") for c in pool):
            summary["oracle_reachable"] += 1
        if any(c.get("label_available") and c.get("exec_ok") and not c.get("exec_correct") for c in pool):
            summary["examples_with_executable_wrong"] += 1
        if has_hard_semantic_choice(pool):
            summary["hard_semantic_choice_examples"] += 1
        if any(c.get("variant") == "strong_repair" for c in pool):
            summary["examples_with_repair_variant"] += 1
    return dict(summary)


def build_pairs_for_rows(rows, schema_by_db, max_pairs_per_item, seed, max_schema_chars):
    all_pairs = []
    pair_counts = Counter()

    for row in rows:
        row_seed = seed + int(row.get("idx", 0) or 0)
        row_rng = random.Random(row_seed)
        pairs = build_pairwise_records(
            row,
            schema_by_db=schema_by_db,
            max_pairs_per_item=max_pairs_per_item,
            rng=row_rng,
            max_schema_chars=max_schema_chars,
        )
        all_pairs.extend(pairs)
        pair_counts["examples_seen"] += 1
        if pairs:
            pair_counts["examples_with_pairs"] += 1
        pair_counts["pairs"] += len(pairs)
        pair_counts.update(pair["negative_type"] for pair in pairs)

    return all_pairs, pair_counts


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Build DB-level cross-validation pairwise data for the semantic SQL selector. "
            "Positive candidates are exec_correct=true; negatives include executable semantic errors."
        )
    )
    parser.add_argument(
        "--in_file",
        default="runs/outputs/a2v/multillm/scored_multillm_spider1034.jsonl",
        help="Scored candidate JSONL with candidates[*].exec_correct labels.",
    )
    parser.add_argument("--tables", default="data/spider/tables.json")
    parser.add_argument(
        "--out_dir",
        default="runs/outputs/a2v/semantic_selector/multillm",
    )
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--max_pairs_per_item", type=int, default=80)
    parser.add_argument("--max_schema_chars", type=int, default=4500)
    parser.add_argument(
        "--also_write_fit_all",
        action="store_true",
        help="Also write all_pairs.jsonl for a diagnostic fit-all run.",
    )
    args = parser.parse_args()

    rows = read_jsonl(args.in_file)
    schema_by_db = load_schema_info_by_db(args.tables)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    row_folds, db_to_fold, fold_sizes = assign_db_folds(rows, args.folds)
    row_summary = summarize_rows(rows, schema_by_db, args.max_schema_chars)

    fold_summaries = []
    all_pairs_cache = None
    if args.also_write_fit_all:
        all_pairs_cache, all_counts = build_pairs_for_rows(
            rows,
            schema_by_db=schema_by_db,
            max_pairs_per_item=args.max_pairs_per_item,
            seed=args.seed,
            max_schema_chars=args.max_schema_chars,
        )
        write_jsonl(out_dir / "all_pairs.jsonl", all_pairs_cache)
        fold_summaries.append({"split": "all_pairs", **dict(all_counts)})

    for fold in range(args.folds):
        train_rows = [row for row, row_fold in zip(rows, row_folds) if row_fold != fold]
        dev_rows = [row for row, row_fold in zip(rows, row_folds) if row_fold == fold]

        train_pairs, train_counts = build_pairs_for_rows(
            train_rows,
            schema_by_db=schema_by_db,
            max_pairs_per_item=args.max_pairs_per_item,
            seed=args.seed + 1000 * fold,
            max_schema_chars=args.max_schema_chars,
        )
        dev_pairs, dev_counts = build_pairs_for_rows(
            dev_rows,
            schema_by_db=schema_by_db,
            max_pairs_per_item=args.max_pairs_per_item,
            seed=args.seed + 2000 * fold,
            max_schema_chars=args.max_schema_chars,
        )

        fold_dir = out_dir / f"fold_{fold}"
        write_jsonl(fold_dir / "train_pairs.jsonl", train_pairs)
        write_jsonl(fold_dir / "dev_pairs.jsonl", dev_pairs)

        fold_summaries.append({
            "fold": fold,
            "train_examples": len(train_rows),
            "dev_examples": len(dev_rows),
            "dev_db_count": sum(1 for db_fold in db_to_fold.values() if db_fold == fold),
            "dev_fold_size": fold_sizes[fold],
            "train_pairs": dict(train_counts),
            "dev_pairs": dict(dev_counts),
        })

    metadata = {
        "in_file": args.in_file,
        "tables": args.tables,
        "folds": args.folds,
        "seed": args.seed,
        "max_pairs_per_item": args.max_pairs_per_item,
        "max_schema_chars": args.max_schema_chars,
        "row_summary": row_summary,
        "db_to_fold": db_to_fold,
        "fold_summaries": fold_summaries,
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[OK] examples: {len(rows)}")
    print(f"[OK] oracle reachable: {row_summary.get('oracle_reachable', 0)}")
    print(f"[OK] hard semantic choice examples: {row_summary.get('hard_semantic_choice_examples', 0)}")
    print(f"[OK] output dir: {out_dir}")


if __name__ == "__main__":
    main()
