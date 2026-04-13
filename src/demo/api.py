#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from src.rag.retrieve import retrieve_schema_context
from src.rag.retrieve_embed import retrieve_schema_context_embed
from src.spider.load_spider import iter_spider_samples
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from peft import PeftModel
import torch
import json
import urllib.request
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Text-to-SQL Demo API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:9000",
        "http://127.0.0.1:9000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====== paths / settings ======
BM25_INDEX = "runs/cache/bm25_schema"
EMBED_INDEX = "runs/cache/embed_schema"
DB_ROOT = "data/spider/database"

LORA_ADAPTER_DIR = "runs/outputs/lora_flan_t5_base_spider_all8659_allowed_cache"
LORA_BASE_MODEL = "google/flan-t5-base"

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1/chat/completions"


# ====== request / response ======
class AskRequest(BaseModel):
    question: str
    db_id: str
    method: str  # prompt-only / bm25-rag / embed-rag / lora-only / lora-rag


class AskResponse(BaseModel):
    method: str
    db_id: str
    question: str
    retrieved_schema: List[str]
    sql: str
    rows: List[List[Any]]
    columns: List[str]
    error: Optional[str]
    notes: str


# ====== helpers ======
def pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


DEVICE = pick_device()

_lora_tok = None
_lora_model = None
_loraonly_tok = None
_loraonly_model = None


def get_lora_model():
    global _lora_tok, _lora_model
    if _lora_tok is None or _lora_model is None:
        tok = AutoTokenizer.from_pretrained(LORA_ADAPTER_DIR)
        base = AutoModelForSeq2SeqLM.from_pretrained(LORA_BASE_MODEL)
        model = PeftModel.from_pretrained(base, LORA_ADAPTER_DIR)
        model.to(DEVICE)
        model.eval()
        _lora_tok = tok
        _lora_model = model
    return _lora_tok, _lora_model


def extract_sql(text: str) -> str:
    t = (text or "").strip()
    m = re.search(r"\b(SELECT|WITH)\b", t, flags=re.IGNORECASE)
    if m:
        t = t[m.start():].strip()
    if ";" in t:
        t = t.split(";", 1)[0].strip() + ";"
    elif t and not t.endswith(";"):
        t += ";"
    return t


def parse_allowed(schema_text: str):
    tables, cols = [], []
    for line in schema_text.splitlines():
        s = line.strip()
        if s.startswith("Table: "):
            tables.append(s.replace("Table: ", "").strip())
        elif s.startswith("Column: "):
            cols.append(s.replace("Column: ", "").strip())
    return sorted(set(tables)), sorted(set(cols))


def db_path(db_id: str) -> str:
    return os.path.join(DB_ROOT, db_id, f"{db_id}.sqlite")


def execute_sql(db_id: str, sql: str, max_rows: int = 100):
    path = db_path(db_id)
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchmany(max_rows)
        columns = [d[0] for d in cur.description] if cur.description else []
        return columns, [list(r) for r in rows], None
    except Exception as e:
        return [], [], str(e)
    finally:
        conn.close()


def call_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        DEEPSEEK_BASE_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    return out["choices"][0]["message"]["content"].strip()


def deepseek_prompt_only(question: str) -> str:
    prompt = f"""You are a Text-to-SQL expert.
Write a single SQLite SQL query for the question.

Rules:
- Output SQL ONLY. No explanation. One statement.

Question:
{question}

SQL:
"""
    return extract_sql(call_deepseek(prompt, model="deepseek-chat"))


def deepseek_rag(question: str, schema_ctx: str) -> str:
    prompt = f"""You are a Text-to-SQL expert.
Write a single SQLite SQL query for the question.

Rules:
- Use ONLY tables/columns shown in the provided schema context.
- JOIN is allowed ONLY if supported by the foreign keys shown.
- Output SQL ONLY. No explanation. One statement.

Schema context:
{schema_ctx}

Question:
{question}

SQL:
"""
    return extract_sql(call_deepseek(prompt, model="deepseek-chat"))


def lora_only_sql(question: str) -> str:
    adapter_dir = "runs/outputs/loraonly_flan_t5_base_all8659_ep3"
    tok = AutoTokenizer.from_pretrained(adapter_dir)
    base = AutoModelForSeq2SeqLM.from_pretrained(LORA_BASE_MODEL)
    model = PeftModel.from_pretrained(base, adapter_dir)
    model.to(DEVICE)
    model.eval()

    prompt = f"""You are a Text-to-SQL system.
Write ONE valid SQLite SQL query.

Rules:
- Output SQL ONLY. One statement.
- The SQL must start with SELECT or WITH and end with a semicolon.
- Do NOT output explanations, code, or markdown.

Question:
{question}

SQL:
"""
    inp = tok(prompt, return_tensors="pt", truncation=True, max_length=256).to(DEVICE)
    with torch.no_grad():
        out_ids = model.generate(
            **inp,
            do_sample=False,
            num_beams=4,
            max_new_tokens=128,
            early_stopping=True,
        )
    raw = tok.decode(out_ids[0], skip_special_tokens=True)
    return extract_sql(raw)


def lora_rag_sql(question: str, schema_ctx: str) -> str:
    tok, model = get_lora_model()
    tables, cols = parse_allowed(schema_ctx)
    allowed_tables = "\n".join(tables[:50]) if tables else "(none)"
    allowed_cols = "\n".join(cols[:200]) if cols else "(none)"

    prompt = f"""You are a Text-to-SQL system.
Write ONE valid SQLite SQL query.

Rules:
- Output SQL ONLY. One statement.
- Use ONLY table/column names from the ALLOWED LIST.
- If a table/column is not in the allowed list, you MUST NOT use it.
- The SQL must start with SELECT or WITH and end with a semicolon.

Schema context:
{schema_ctx}

ALLOWED TABLES:
{allowed_tables}

ALLOWED COLUMNS:
{allowed_cols}

Question:
{question}

SQL:
"""

    inp = tok(prompt, return_tensors="pt", truncation=True, max_length=512).to(DEVICE)
    with torch.no_grad():
        out_ids = model.generate(
            **inp,
            do_sample=False,
            num_beams=8,
            max_new_tokens=160,
            early_stopping=True,
        )
    raw = tok.decode(out_ids[0], skip_special_tokens=True)
    return extract_sql(raw)


@app.get("/methods")
def methods():
    return {
        "methods": [
            "prompt-only",
            "bm25-rag",
            "embed-rag",
            "lora-only",
            "lora-rag",
        ]
    }


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    question = req.question.strip()
    db_id = req.db_id.strip()
    method = req.method.strip()

    retrieved_schema = []
    sql = ""
    notes = ""

    try:
        if method == "prompt-only":
            sql = deepseek_prompt_only(question)
            notes = "DeepSeek without schema grounding."
        elif method == "bm25-rag":
            schema_ctx = retrieve_schema_context(
                index_dir=BM25_INDEX,
                question=question,
                db_id=db_id,
                topk_table=5,
                topk_col=8,
                topk_fk=8,
            )
            retrieved_schema = schema_ctx.splitlines()[:20]
            sql = deepseek_rag(question, schema_ctx)
            notes = "BM25-based schema retrieval."
        elif method == "embed-rag":
            schema_ctx = retrieve_schema_context_embed(
                index_dir=EMBED_INDEX,
                question=question,
                db_id=db_id,
                topk_table=5,
                topk_col=8,
                topk_fk=8,
            )
            retrieved_schema = schema_ctx.splitlines()[:20]
            sql = deepseek_rag(question, schema_ctx)
            notes = "Embedding-based schema retrieval."
        elif method == "lora-only":
            sql = lora_only_sql(question)
            notes = "Fine-tuned LoRA model without schema grounding."
        elif method == "lora-rag":
            schema_ctx = retrieve_schema_context(
                index_dir=BM25_INDEX,
                question=question,
                db_id=db_id,
                topk_table=5,
                topk_col=8,
                topk_fk=8,
            )
            retrieved_schema = schema_ctx.splitlines()[:20]
            sql = lora_rag_sql(question, schema_ctx)
            notes = "LoRA + Schema-RAG."
        else:
            return AskResponse(
                method=method,
                db_id=db_id,
                question=question,
                retrieved_schema=[],
                sql="",
                rows=[],
                columns=[],
                error=f"Unknown method: {method}",
                notes="",
            )

        columns, rows, error = execute_sql(db_id, sql)

        return AskResponse(
            method=method,
            db_id=db_id,
            question=question,
            retrieved_schema=retrieved_schema,
            sql=sql,
            rows=rows,
            columns=columns,
            error=error,
            notes=notes,
        )
    except Exception as e:
        return AskResponse(
            method=method,
            db_id=db_id,
            question=question,
            retrieved_schema=retrieved_schema,
            sql=sql,
            rows=[],
            columns=[],
            error=str(e),
            notes=notes,
        )