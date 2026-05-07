# Semantic Preference Selector Training

This experiment upgrades the old rule-based Selector into an evidence-aware semantic ranker.

The training target is pairwise:

```text
score(question, schema, SQL_positive, evidence) >
score(question, schema, SQL_negative, evidence)
```

Positive candidates are candidates whose execution result matches the gold SQL result. The gold signal is used only as the training label, never as an input feature.

Negative candidates include ordinary execution failures and, most importantly, hard negatives:

```text
hard_supported_executable_wrong:
  executable and wrong, with the same result supported by multiple candidates.

hard_same_shape_executable_wrong:
  executable and wrong, with row/column shape similar to a correct candidate.

hard_non_empty_executable_wrong:
  executable and wrong, with a non-empty result.

hard_empty_executable_wrong:
  executable and wrong, but returns an empty result.

easy_execution_error:
  syntax/runtime failure.
```

This makes the selector focus on semantic confusion cases instead of learning only to reject invalid SQL.

## 1. Build Pairwise Data

Multi-LLM candidate pool:

```bash
cd /Users/kankan/Downloads/杂项/lunwen/spider_thesis

python src/a2v/18_build_semantic_selector_data.py \
  --in_file runs/outputs/a2v/multillm/scored_multillm_spider1034.jsonl \
  --tables data/spider/tables.json \
  --out_dir runs/outputs/a2v/semantic_selector/multillm \
  --folds 5 \
  --max_pairs_per_item 80 \
  --also_write_fit_all
```

Strong-repair candidate pool:

```bash
python src/a2v/18_build_semantic_selector_data.py \
  --in_file runs/outputs/a2v/repaired_strong_spider1034_full.jsonl \
  --tables data/spider/tables.json \
  --out_dir runs/outputs/a2v/semantic_selector/strong_repair \
  --folds 5 \
  --max_pairs_per_item 80 \
  --also_write_fit_all
```

The script writes `fold_0/train_pairs.jsonl`, `fold_0/dev_pairs.jsonl`, etc. Folds are split by `db_id`, so the validation fold uses unseen databases.

Each candidate input contains only inference-time evidence:

```text
question
schema text
SQL
execution status/error
result row/column shape
small result sample
result-consistency support inside the candidate pool
SQL structure summary
schema-link summary
repair trace
```

It does not contain:

```text
gold SQL
gold execution result
exec_correct label
```

## 2. Train One Fold

Use CodeBERT as a safe default because the input mixes natural language, SQL, and schema text.

```bash
python src/a2v/19_train_semantic_selector.py \
  --train_jsonl runs/outputs/a2v/semantic_selector/multillm/fold_0/train_pairs.jsonl \
  --dev_jsonl runs/outputs/a2v/semantic_selector/multillm/fold_0/dev_pairs.jsonl \
  --out_dir runs/outputs/a2v/semantic_selector/models/multillm_fold0_codebert \
  --model_name microsoft/codebert-base \
  --max_length 512 \
  --epochs 3 \
  --batch_size 8 \
  --gradient_accumulation_steps 2 \
  --lr 2e-5
```

If GPU memory is enough, increase `batch_size` to 16. If using Apple Silicon MPS and mixed precision causes trouble, do not pass `--fp16` or `--bf16`.

## 3. Run Selector Inference

```bash
python src/a2v/20_select_semantic_selector.py \
  --in_file runs/outputs/a2v/multillm/scored_multillm_spider1034.jsonl \
  --tables data/spider/tables.json \
  --model_dir runs/outputs/a2v/semantic_selector/models/multillm_fold0_codebert \
  --out runs/outputs/a2v/semantic_selector/selected_multillm_fold0.jsonl \
  --summary_out runs/outputs/a2v/semantic_selector/summary_multillm_fold0.md
```

For a paper table, repeat training for folds `0..4`, run inference with the corresponding fold model on that fold's examples, then merge the selected rows. The current inference script scores a full file, which is convenient for quick diagnosis; for strict DB-level cross-validation, pass the fold metadata and evaluate only the dev examples of the matching fold.

Strict fold-0 inference:

```bash
python src/a2v/20_select_semantic_selector.py \
  --in_file runs/outputs/a2v/multillm/scored_multillm_spider1034.jsonl \
  --tables data/spider/tables.json \
  --model_dir runs/outputs/a2v/semantic_selector/models/multillm_fold0_codebert \
  --fold_metadata runs/outputs/a2v/semantic_selector/multillm/metadata.json \
  --eval_fold 0 \
  --out runs/outputs/a2v/semantic_selector/selected_multillm_fold0_strict.jsonl \
  --summary_out runs/outputs/a2v/semantic_selector/summary_multillm_fold0_strict.md
```

## 4. Suggested Ablations

Report these selectors:

```text
rule_priority
consensus_practical
semantic_selector
oracle
```

The most important columns are:

```text
Execution Accuracy
Oracle Gap
Hard Acc.
```

`Hard Acc.` measures examples where at least one candidate is correct and at least one other candidate is executable but semantically wrong. This directly supports the thesis claim that the new Selector targets executable semantic errors rather than only syntax/runtime errors.

## 5. Optional LLM Pairwise Teacher Rubric

If you add an LLM teacher before training the small ranker, do not ask only "which SQL is better". Use a structured rubric and request concise evidence, not an open-ended chain-of-thought.

```text
You are judging which candidate SQL better matches the user's natural-language question.

Question:
{question}

Schema:
{schema}

Candidate A:
SQL: {sql_a}
Execution evidence: {exec_a}
Result summary: {result_a}
SQL structure: {structure_a}

Candidate B:
SQL: {sql_b}
Execution evidence: {exec_b}
Result summary: {result_b}
SQL structure: {structure_b}

Score each candidate from 0 to 2 on each criterion:
1. selected output matches the question
2. WHERE/filter conditions match all constraints
3. aggregation/grouping matches the question
4. join path and schema grounding are reasonable
5. ordering/limit/distinct semantics match the question
6. execution result is plausible but not used as sole evidence

Return strict JSON:
{
  "schema_grounding": {"A": 0-2, "B": 0-2, "evidence": "..."},
  "filters": {"A": 0-2, "B": 0-2, "evidence": "..."},
  "aggregation": {"A": 0-2, "B": 0-2, "evidence": "..."},
  "joins": {"A": 0-2, "B": 0-2, "evidence": "..."},
  "ordering_limit": {"A": 0-2, "B": 0-2, "evidence": "..."},
  "result_plausibility": {"A": 0-2, "B": 0-2, "evidence": "..."},
  "winner": "A" | "B" | "Tie",
  "confidence": 0.0-1.0
}
```

Use the teacher output either as an additional training signal or as a diagnostic baseline. For the main result, keep the reported held-out split by `db_id`.

## 6. Thesis Wording

Suggested method description:

```text
We formulate candidate selection as an evidence-aware semantic preference ranking problem. For each candidate SQL, the Selector receives the natural language question, database schema, SQL text, execution evidence, result summary, result-consistency evidence, and repair trace. A transformer cross-encoder is trained with pairwise ranking loss to assign higher scores to semantically correct candidates than to executable but wrong hard negatives.
```

Suggested loss:

```text
L = -log sigma(f(q, S, c+) - f(q, S, c-))
```

where `c+` is an execution-correct candidate and `c-` is an incorrect candidate from the same candidate pool.

## 7. LLM Pairwise Correction For The 78.1% A2V Result

The most conservative way to improve the strong-repair practical result is not to replace the selector. Instead:

```text
current practical selector
-> detect disagreement cases with multiple executable result groups
-> ask an LLM pairwise semantic judge
-> switch only when confidence and rubric-score margin are high
```

Dry run without API calls:

```bash
python src/a2v/21_llm_pairwise_correction_selector.py \
  --in_file runs/outputs/a2v/repaired_strong_spider1034_full.jsonl \
  --tables data/spider/tables.json \
  --dry_run \
  --out runs/outputs/a2v/semantic_selector/selected_llm_pairwise_correction_dryrun.jsonl \
  --summary_out runs/outputs/a2v/semantic_selector/summary_llm_pairwise_correction_dryrun.md
```

Small API pilot:

```bash
export DEEPSEEK_API_KEY="your_key_here"

python src/a2v/21_llm_pairwise_correction_selector.py \
  --in_file runs/outputs/a2v/repaired_strong_spider1034_full.jsonl \
  --tables data/spider/tables.json \
  --model deepseek-reasoner \
  --max_cases 50 \
  --min_confidence 0.72 \
  --score_margin 1.0 \
  --out runs/outputs/a2v/semantic_selector/selected_llm_pairwise_correction_pilot50.jsonl \
  --summary_out runs/outputs/a2v/semantic_selector/summary_llm_pairwise_correction_pilot50.md
```

Full run:

```bash
python src/a2v/21_llm_pairwise_correction_selector.py \
  --in_file runs/outputs/a2v/repaired_strong_spider1034_full.jsonl \
  --tables data/spider/tables.json \
  --model deepseek-reasoner \
  --min_confidence 0.72 \
  --score_margin 1.0 \
  --out runs/outputs/a2v/semantic_selector/selected_llm_pairwise_correction_full.jsonl \
  --summary_out runs/outputs/a2v/semantic_selector/summary_llm_pairwise_correction_full.md
```

The script caches pairwise judgments in:

```text
runs/outputs/a2v/semantic_selector/cache_llm_pairwise_correction.jsonl
```

If a run is interrupted, rerun the same command and it will reuse cached judgments.
