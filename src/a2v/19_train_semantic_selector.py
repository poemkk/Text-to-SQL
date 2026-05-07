import argparse
import inspect
import json
from collections import Counter
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)

try:
    from semantic_selector_common import read_jsonl
except ImportError:
    from .semantic_selector_common import read_jsonl


class PairwiseSelectorDataset(Dataset):
    def __init__(self, rows):
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, idx):
        row = self.rows[idx]
        return {
            "positive_text": row["positive"]["text"],
            "negative_text": row["negative"]["text"],
            "negative_type": row.get("negative_type", "unknown"),
        }


class PairwiseCollator:
    def __init__(self, tokenizer, max_length):
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __call__(self, features):
        positive = self.tokenizer(
            [item["positive_text"] for item in features],
            truncation=True,
            max_length=self.max_length,
            padding=True,
            return_tensors="pt",
        )
        negative = self.tokenizer(
            [item["negative_text"] for item in features],
            truncation=True,
            max_length=self.max_length,
            padding=True,
            return_tensors="pt",
        )

        batch = {}
        for key, value in positive.items():
            batch[f"pos_{key}"] = value
        for key, value in negative.items():
            batch[f"neg_{key}"] = value
        batch["negative_type"] = [item["negative_type"] for item in features]
        return batch


class PairwiseRankerTrainer(Trainer):
    def _split_pairwise_inputs(self, inputs):
        # Drop non-tensor metadata such as negative_type before forwarding to the model.
        pos_inputs = {
            key.removeprefix("pos_"): value
            for key, value in inputs.items()
            if key.startswith("pos_") and torch.is_tensor(value)
        }
        neg_inputs = {
            key.removeprefix("neg_"): value
            for key, value in inputs.items()
            if key.startswith("neg_") and torch.is_tensor(value)
        }
        return pos_inputs, neg_inputs

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        pos_inputs, neg_inputs = self._split_pairwise_inputs(inputs)

        pos_scores = model(**pos_inputs).logits.view(-1)
        neg_scores = model(**neg_inputs).logits.view(-1)
        margin = pos_scores - neg_scores
        loss = F.softplus(-margin).mean()

        if return_outputs:
            return loss, {
                "pos_scores": pos_scores.detach(),
                "neg_scores": neg_scores.detach(),
                "margin": margin.detach(),
            }
        return loss

    def prediction_step(self, model, inputs, prediction_loss_only, ignore_keys=None):
        """Custom eval step for pairwise batches.

        HuggingFace Trainer's default prediction_step calls model(**inputs).
        That fails here because our collator produces pos_input_ids / neg_input_ids,
        while RobertaForSequenceClassification expects input_ids / attention_mask.
        """
        inputs = self._prepare_inputs(inputs)
        pos_inputs, neg_inputs = self._split_pairwise_inputs(inputs)

        with torch.no_grad():
            pos_scores = model(**pos_inputs).logits.view(-1)
            neg_scores = model(**neg_inputs).logits.view(-1)
            margin = pos_scores - neg_scores
            loss = F.softplus(-margin).mean()

        if prediction_loss_only:
            return loss.detach(), None, None

        # logits[:, 0] = positive candidate score; logits[:, 1] = negative candidate score.
        logits = torch.stack([pos_scores, neg_scores], dim=1).detach()
        labels = torch.zeros(logits.size(0), dtype=torch.long, device=logits.device)
        return loss.detach(), logits, labels


def build_training_args(args, has_dev):
    signature = inspect.signature(TrainingArguments.__init__)
    kwargs = {
        "output_dir": args.out_dir,
        "num_train_epochs": args.epochs,
        "per_device_train_batch_size": args.batch_size,
        "per_device_eval_batch_size": args.eval_batch_size,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "learning_rate": args.lr,
        "weight_decay": args.weight_decay,
        "warmup_ratio": args.warmup_ratio,
        "logging_steps": args.logging_steps,
        "save_steps": args.save_steps,
        "save_total_limit": 2,
        "remove_unused_columns": False,
        "report_to": "none",
        "fp16": args.fp16,
        "bf16": args.bf16,
    }

    strategy_key = "eval_strategy" if "eval_strategy" in signature.parameters else "evaluation_strategy"
    kwargs[strategy_key] = "steps" if has_dev else "no"
    kwargs["save_strategy"] = "steps" if has_dev else "epoch"
    if has_dev:
        kwargs["eval_steps"] = args.eval_steps

    return TrainingArguments(**kwargs)


@torch.no_grad()
def evaluate_pairwise_accuracy(model, dataset, collator, batch_size, device):
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, collate_fn=collator)
    model.eval()

    total = 0
    correct = 0
    by_type = Counter()
    by_type_correct = Counter()
    margins = []

    for batch in loader:
        negative_types = batch.pop("negative_type")
        pos_inputs = {
            key.removeprefix("pos_"): value.to(device)
            for key, value in batch.items()
            if key.startswith("pos_")
        }
        neg_inputs = {
            key.removeprefix("neg_"): value.to(device)
            for key, value in batch.items()
            if key.startswith("neg_")
        }
        pos_scores = model(**pos_inputs).logits.view(-1)
        neg_scores = model(**neg_inputs).logits.view(-1)
        batch_margins = (pos_scores - neg_scores).detach().cpu().tolist()

        for margin, negative_type in zip(batch_margins, negative_types):
            total += 1
            by_type[negative_type] += 1
            margins.append(margin)
            if margin > 0:
                correct += 1
                by_type_correct[negative_type] += 1

    return {
        "pairs": total,
        "pairwise_accuracy": correct / total if total else 0.0,
        "mean_margin": sum(margins) / len(margins) if margins else 0.0,
        "by_negative_type": {
            key: {
                "pairs": by_type[key],
                "accuracy": by_type_correct[key] / by_type[key] if by_type[key] else 0.0,
            }
            for key in sorted(by_type)
        },
    }


def compute_pairwise_metrics(eval_pred):
    logits, labels = eval_pred
    preds = logits.argmax(axis=1)
    return {
        "pairwise_accuracy": float((preds == labels).mean()),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Train an evidence-aware semantic SQL selector with pairwise ranking loss."
    )
    parser.add_argument("--train_jsonl", required=True)
    parser.add_argument("--dev_jsonl", default=None)
    parser.add_argument("--out_dir", required=True)
    parser.add_argument(
        "--model_name",
        default="microsoft/codebert-base",
        help="Good alternatives: roberta-base, microsoft/deberta-v3-base, microsoft/MiniLM-L12-H384-uncased.",
    )
    parser.add_argument("--max_length", type=int, default=512)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--eval_batch_size", type=int, default=16)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=2)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--weight_decay", type=float, default=0.01)
    parser.add_argument("--warmup_ratio", type=float, default=0.06)
    parser.add_argument("--logging_steps", type=int, default=50)
    parser.add_argument("--eval_steps", type=int, default=200)
    parser.add_argument("--save_steps", type=int, default=200)
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--bf16", action="store_true")
    args = parser.parse_args()

    train_rows = read_jsonl(args.train_jsonl)
    dev_rows = read_jsonl(args.dev_jsonl) if args.dev_jsonl else []

    tokenizer = AutoTokenizer.from_pretrained(args.model_name, use_fast=True)
    model = AutoModelForSequenceClassification.from_pretrained(args.model_name, num_labels=1)

    train_dataset = PairwiseSelectorDataset(train_rows)
    dev_dataset = PairwiseSelectorDataset(dev_rows) if dev_rows else None
    collator = PairwiseCollator(tokenizer=tokenizer, max_length=args.max_length)
    training_args = build_training_args(args, has_dev=dev_dataset is not None)

    trainer = PairwiseRankerTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=dev_dataset,
        data_collator=collator,
        tokenizer=tokenizer,
        compute_metrics=compute_pairwise_metrics if dev_dataset is not None else None,
    )

    trainer.train()

    out_dir = Path(args.out_dir)
    trainer.save_model(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))

    metrics = {
        "train_pairs": len(train_dataset),
        "dev_pairs": len(dev_dataset) if dev_dataset else 0,
        "model_name": args.model_name,
        "max_length": args.max_length,
    }
    if dev_dataset:
        device = trainer.model.device
        metrics["dev_pairwise"] = evaluate_pairwise_accuracy(
            trainer.model,
            dev_dataset,
            collator,
            args.eval_batch_size,
            device,
        )

    (out_dir / "selector_train_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"[OK] model saved to: {out_dir}")


if __name__ == "__main__":
    main()
