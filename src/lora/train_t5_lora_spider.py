#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
from dataclasses import dataclass

import torch
from datasets import load_dataset
from transformers import (
    AutoTokenizer,
    AutoModelForSeq2SeqLM,
    DataCollatorForSeq2Seq,
    Seq2SeqTrainingArguments,
    Seq2SeqTrainer,
)
from peft import LoraConfig, get_peft_model


def pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main():
    ap = argparse.ArgumentParser()

    # ---- Cache inputs (recommended) ----
    ap.add_argument("--train_cache_jsonl", default="runs/cache/lora_train_all_allowed.jsonl",
                    help="JSONL cache with fields: input_text, target_text, db_id")
    ap.add_argument("--dev_cache_jsonl", default="runs/cache/lora_dev_500_allowed.jsonl",
                    help="JSONL cache with fields: input_text, target_text, db_id")

    # Limits (for fast experiments)
    ap.add_argument("--train_limit", type=int, default=8659)
    ap.add_argument("--dev_limit", type=int, default=200)

    # Model / output
    ap.add_argument("--model_name", default="google/flan-t5-base")
    ap.add_argument("--out_dir", default="runs/outputs/lora_flan_t5_base_spider_all8659_allowed")

    # Tokenization
    ap.add_argument("--max_src_len", type=int, default=512)
    ap.add_argument("--max_tgt_len", type=int, default=256)

    # Train hyperparams
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--grad_accum", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)

    # Speed/IO
    ap.add_argument("--logging_steps", type=int, default=10)
    ap.add_argument("--save_strategy", default="epoch", choices=["no", "steps", "epoch"])
    ap.add_argument("--eval_strategy", default="epoch", choices=["no", "steps", "epoch"])
    ap.add_argument("--save_total_limit", type=int, default=2)

    # LoRA
    ap.add_argument("--lora_r", type=int, default=16)
    ap.add_argument("--lora_alpha", type=int, default=32)
    ap.add_argument("--lora_dropout", type=float, default=0.05)

    # Optional: resume
    ap.add_argument("--resume_from_checkpoint", default="",
                    help="path to checkpoint dir under out_dir (optional)")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    device = pick_device()
    print("[INFO] device:", device)

    # Reproducibility (best-effort)
    torch.manual_seed(args.seed)

    # Tokenizer / model
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)

    base = AutoModelForSeq2SeqLM.from_pretrained(args.model_name)

    # LoRA config for T5 attention projections
    lora_cfg = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="SEQ_2_SEQ_LM",
        target_modules=["q", "v"],
    )
    model = get_peft_model(base, lora_cfg)
    model.print_trainable_parameters()

    # ---- Load cached datasets (FAST) ----
    # JSONL format: one JSON per line with at least input_text/target_text
    data_files = {"train": args.train_cache_jsonl, "eval": args.dev_cache_jsonl}
    ds = load_dataset("json", data_files=data_files)

    if args.train_limit and args.train_limit < len(ds["train"]):
        ds["train"] = ds["train"].select(range(args.train_limit))
    if args.dev_limit and args.dev_limit < len(ds["eval"]):
        ds["eval"] = ds["eval"].select(range(args.dev_limit))

    # ---- Tokenize + label masking (-100 on PAD) ----
    pad_id = tokenizer.pad_token_id

    def tok(batch):
        x = tokenizer(
            batch["input_text"],
            max_length=args.max_src_len,
            truncation=True,
        )
        y = tokenizer(
            batch["target_text"],
            max_length=args.max_tgt_len,
            truncation=True,
        )
        labels = y["input_ids"]
        # mask pad tokens for loss
        labels = [[(t if t != pad_id else -100) for t in seq] for seq in labels]
        x["labels"] = labels
        return x

    # Remove original text fields to reduce RAM
    remove_cols_train = ds["train"].column_names
    remove_cols_eval = ds["eval"].column_names

    train_tok = ds["train"].map(tok, batched=True, remove_columns=remove_cols_train)
    eval_tok = ds["eval"].map(tok, batched=True, remove_columns=remove_cols_eval)

    data_collator = DataCollatorForSeq2Seq(tokenizer, model=model)

    # ---- TrainingArguments (transformers version compatible) ----
    targs = Seq2SeqTrainingArguments(
        output_dir=args.out_dir,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        logging_steps=args.logging_steps,
        save_strategy=args.save_strategy,
        eval_strategy=args.eval_strategy,
        save_total_limit=args.save_total_limit,
        predict_with_generate=False,
        fp16=False,     # on MPS: keep fp16 off
        bf16=False,     # keep conservative; enable only if you know it works
        report_to=[],
        seed=args.seed,
    )

    trainer = Seq2SeqTrainer(
        model=model,
        args=targs,
        train_dataset=train_tok,
        eval_dataset=eval_tok,
        tokenizer=tokenizer,
        data_collator=data_collator,
    )

    ckpt = args.resume_from_checkpoint.strip() or None
    trainer.train(resume_from_checkpoint=ckpt)

    model.save_pretrained(args.out_dir)
    tokenizer.save_pretrained(args.out_dir)
    print("[OK] saved to:", args.out_dir)


if __name__ == "__main__":
    main()