#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
import argparse
import json
import os
import time
import urllib.request

from src.spider.load_spider import iter_spider_samples
from src.rag.retrieve import retrieve_schema_context

# DeepSeek JSON Output 要求：prompt 里必须明确要求 JSON，并给示例（最稳）
PROMPT_TEMPLATE = """You are a Text-to-SQL expert.

You MUST output valid JSON. Return ONLY a JSON object with exactly one key: "sql".
Example JSON format:
{{
  "sql": "SELECT 1;"
}}

Rules:
- Write a single SQLite SQL query for the question.
- Use ONLY tables/columns shown in the provided schema context.
- JOIN is allowed ONLY if supported by the foreign keys shown.
- Output ONLY JSON. No explanation. No markdown. No extra keys.

Schema context:
{schema_context}

Question:
{question}
"""


def _extract_sql_from_json_text(content: str) -> str:
    """Parse {"sql": "..."} from model output; fallback to raw text if parsing fails."""
    content = content.strip()
    try:
        obj = json.loads(content)
        if isinstance(obj, dict) and "sql" in obj:
            return str(obj["sql"]).strip()
    except Exception:
        pass
    # fallback: return raw (better than empty)
    return content


def call_chat_api(prompt: str, api_key: str, model: str, base_url: str,
                  use_json_output: bool = True,
                  thinking_enabled: bool = False,
                  timeout_sec: int = 60) -> str:
    """
    DeepSeek v3.2 is OpenAI-compatible via /chat/completions.
    - JSON Output: payload["response_format"] = {"type":"json_object"}
    - Thinking: payload["thinking"] = {"type":"enabled"|"disabled"}
    """
    payload = {
        "model": model,  # deepseek-chat | deepseek-reasoner
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.0,
    }

    # JSON Output (recommended for stable SQL-only output)
    if use_json_output:
        payload["response_format"] = {"type": "json_object"}

    # Thinking mode (mainly for deepseek-reasoner; harmless otherwise)
    payload["thinking"] = {"type": "enabled" if thinking_enabled else "disabled"}

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        base_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        out = json.loads(resp.read().decode("utf-8"))

    # OpenAI-compatible format
    content = out["choices"][0]["message"].get("content", "").strip()

    # If JSON Output enabled, parse {"sql": "..."}
    if use_json_output:
        return _extract_sql_from_json_text(content)

    return content


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev_json", default="data/spider/dev.json")
    ap.add_argument("--bm25_index", default="runs/cache/bm25_schema")
    ap.add_argument("--out", default="runs/outputs/pred_dev_deepseek.jsonl")
    ap.add_argument("--limit", type=int, default=20)

    # DeepSeek defaults (v3.2)
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--base_url", default="https://api.deepseek.com/chat/completions")
    ap.add_argument("--api_key", default="")

    # RAG params
    ap.add_argument("--topk_table", type=int, default=5)
    ap.add_argument("--topk_col", type=int, default=8)
    ap.add_argument("--topk_fk", type=int, default=8)
    ap.add_argument("--no_rag", action="store_true", help="Disable RAG schema retrieval (prompt-only baseline)")

    # API behavior
    ap.add_argument("--sleep", type=float, default=0.2)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--json_output", action="store_true", help="Enable JSON Output (recommended)")
    ap.add_argument("--no_json_output", action="store_true", help="Disable JSON Output")
    ap.add_argument("--thinking", action="store_true", help="Force thinking=enabled (useful for reasoner)")
    ap.add_argument("--retriever", choices=["bm25", "embed"], default="bm25")
    ap.add_argument("--embed_index", default="runs/cache/embed_schema")
    args = ap.parse_args()

    if not args.api_key:
        raise SystemExit("Missing --api_key")

    # default JSON Output ON unless explicitly disabled
    use_json_output = True
    if args.no_json_output:
        use_json_output = False
    if args.json_output:
        use_json_output = True

    # thinking: auto-enable for deepseek-reasoner, or if user forced it
    thinking_enabled = args.thinking or (args.model == "deepseek-reasoner")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    n = 0
    with open(args.out, "w", encoding="utf-8") as f:
        for ex in iter_spider_samples(args.dev_json):
            if n >= args.limit:
                break

            if args.no_rag:
                schema_ctx = "(NO RAG) You must infer the schema only from the question."
            elif args.retriever == "bm25":
                schema_ctx = retrieve_schema_context(
                    index_dir=args.bm25_index,
                    question=ex["question"],
                    db_id=ex["db_id"],
                    topk_table=args.topk_table,
                    topk_col=args.topk_col,
                    topk_fk=args.topk_fk,
                )
            else:
                from src.rag.retrieve_embed import retrieve_schema_context_embed
                schema_ctx = retrieve_schema_context_embed(
                    index_dir=args.embed_index,
                    question=ex["question"],
                    db_id=ex["db_id"],
                    topk_table=args.topk_table,
                    topk_col=args.topk_col,
                    topk_fk=args.topk_fk,
                )

            prompt = PROMPT_TEMPLATE.format(schema_context=schema_ctx, question=ex["question"])

            err = None
            pred_sql = ""
            try:
                pred_sql = call_chat_api(
                    prompt=prompt,
                    api_key=args.api_key,
                    model=args.model,
                    base_url=args.base_url,
                    use_json_output=use_json_output,
                    thinking_enabled=thinking_enabled,
                    timeout_sec=args.timeout,
                )
            except Exception as e:
                err = str(e)

            rec = {
                "db_id": ex["db_id"],
                "question": ex["question"],
                "gold": ex["query"],
                "pred": pred_sql,
                "error": err,
                "model": args.model,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            print(f"[{n}/{args.limit}] db={ex['db_id']} pred_len={len(pred_sql)} err={'YES' if err else 'NO'}")
            time.sleep(args.sleep)

    print(f"[OK] wrote {n} predictions to {args.out}")


if __name__ == "__main__":
    main()