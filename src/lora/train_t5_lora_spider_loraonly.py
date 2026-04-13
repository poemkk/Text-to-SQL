#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
from typing import List, Dict

import torch
from datasets import load_dataset
from transformers import (
    AutoTokenizer,
    AutoModelForSeq2SeqLM,
    DataCollatorForSeq2Seq,
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
)

from peft import LoraConfig, get_peft_model


def pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def main():
    ap = argparse.ArgumentParser()

    # cached jsonl produced by build_loraonly_cache.py
    ap.add_argument("--train_cache_jsonl", default="runs/cache/loraonly_train_all8659.jsonl")
    ap.add_argument("--dev_cache_jsonl", default="runs/cache/loraonly_dev_1034.jsonl")

    ap.add_argument("--model_name", default="google/flan-t5-base")
    ap.add_argument("--out_dir", default="runs/outputs/loraonly_flan_t5_base_all8659")

    # tokenization / generation lengths
    ap.add_argument("--max_src_len", type=int, default=384)
    ap.add_argument("--max_tgt_len", type=int, default=256)

    # training hyperparams (safe defaults for M2 Pro 32GB)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--grad_accum", type=int, default=2)
    ap.add_argument("--warmup_ratio", type=float, default=0.03)
    ap.add_argument("--weight_decay", type=float, default=0.0)
    ap.add_argument("--logging_steps", type=int, default=25)
    ap.add_argument("--save_strategy", default="epoch")
    ap.add_argument("--eval_strategy", default="epoch")

    # lora params
    ap.add_argument("--lora_r", type=int, default=16)
    ap.add_argument("--lora_alpha", type=int, default=32)
    ap.add_argument("--lora_dropout", type=float, default=0.05)

    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    device = pick_device()
    print("[INFO] device:", device)
    print("[INFO] train_cache:", args.train_cache_jsonl)
    print("[INFO] dev_cache  :", args.dev_cache_jsonl)

    # Load cached jsonl as datasets.Dataset
    ds = load_dataset(
        "json",
        data_files={"train": args.train_cache_jsonl, "eval": args.dev_cache_jsonl},
    )

    tokenizer = AutoTokenizer.from_pretrained(args.model_name)

    base = AutoModelForSeq2SeqLM.from_pretrained(args.model_name)

    # LoRA targets for T5/Flan-T5 attention projections:
    # commonly "q" and "v" work well across T5 variants
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

    def tok(batch: Dict) -> Dict:
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
        x["labels"] = y["input_ids"]
        return x

    # tokenize
    train_tok = ds["train"].map(tok, batched=True, remove_columns=ds["train"].column_names)
    eval_tok = ds["eval"].map(tok, batched=True, remove_columns=ds["eval"].column_names)

    data_collator = DataCollatorForSeq2Seq(tokenizer, model=model)

    targs = Seq2SeqTrainingArguments(
        output_dir=args.out_dir,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        warmup_ratio=args.warmup_ratio,
        weight_decay=args.weight_decay,
        logging_steps=args.logging_steps,
        save_strategy=args.save_strategy,
        eval_strategy=args.eval_strategy,
        predict_with_generate=False,
        fp16=False,  # MPS usually fp16 is not helpful/stable
        report_to=[],
        dataloader_pin_memory=False,  # avoid MPS warning
    )

    trainer = Seq2SeqTrainer(
        model=model,
        args=targs,
        train_dataset=train_tok,
        eval_dataset=eval_tok,
        tokenizer=tokenizer,
        data_collator=data_collator,
    )

    trainer.train()

    model.save_pretrained(args.out_dir)
    tokenizer.save_pretrained(args.out_dir)

    # record training config for reproducibility
    meta = {
        "base_model": args.model_name,
        "train_cache_jsonl": args.train_cache_jsonl,
        "dev_cache_jsonl": args.dev_cache_jsonl,
        "lora": {
            "r": args.lora_r,
            "alpha": args.lora_alpha,
            "dropout": args.lora_dropout,
            "target_modules": ["q", "v"],
        },
        "train_args": {
            "epochs": args.epochs,
            "lr": args.lr,
            "batch": args.batch,
            "grad_accum": args.grad_accum,
            "max_src_len": args.max_src_len,
            "max_tgt_len": args.max_tgt_len,
        },
    }
    with open(os.path.join(args.out_dir, "train_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("[OK] saved to:", args.out_dir)


if __name__ == "__main__":
    main()