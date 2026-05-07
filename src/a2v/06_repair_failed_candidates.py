import argparse
import json
import os
import sqlite3
import time
from pathlib import Path

from openai import OpenAI


def read_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def execute_sql(db_path, sql):
    start = time.time()

    if not sql or not isinstance(sql, str):
        return {
            "exec_ok": False,
            "exec_error": "empty_or_invalid_sql",
            "result": None,
            "result_columns": None,
            "latency_ms": 0.0,
        }

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchall()
        conn.close()

        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "exec_ok": True,
            "exec_error": None,
            "result": rows,
            "result_columns": columns,
            "latency_ms": latency_ms,
        }

    except Exception as e:
        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "exec_ok": False,
            "exec_error": str(e),
            "result": None,
            "result_columns": None,
            "latency_ms": latency_ms,
        }


def call_deepseek_repair(client, model, question, db_id, wrong_sql, exec_error):
    prompt = f"""
You are a Text-to-SQL repair expert.

The following SQL query failed when executed on a SQLite database.

Database id:
{db_id}

Question:
{question}

Wrong SQL:
{wrong_sql}

Execution error:
{exec_error}

Task:
Repair the SQL query so that it can be executed on SQLite.

Rules:
- Return ONLY a valid JSON object.
- The JSON object must contain exactly one key: "sql".
- Do not explain.
- Do not use markdown.

Example:
{{"sql": "SELECT count(*) FROM singer;"}}
""".strip()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0,
    )

    content = response.choices[0].message.content.strip()

    try:
        data = json.loads(content)
        return data.get("sql"), content
    except Exception:
        return None, content


def normalize_result(result):
    if result is None:
        return None

    normalized = []
    for row in result:
        normalized.append(tuple(str(x) for x in row))

    return sorted(normalized)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--in_file",
        type=str,
        default="runs/outputs/a2v/scored_spider100.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/repaired_spider100.jsonl",
    )
    parser.add_argument(
        "--db_root",
        type=str,
        default="data/spider/database",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="deepseek-v4-chat",
    )
    parser.add_argument(
        "--max_repairs",
        type=int,
        default=50,
        help="Maximum number of failed candidates to repair for this test run.",
    )
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set.")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )

    rows = read_jsonl(args.in_file)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    repaired_count = 0
    repair_exec_ok_count = 0
    repair_correct_count = 0

    with out_path.open("w", encoding="utf-8") as out:
        for item in rows:
            db_id = item["db_id"]
            question = item["question"]
            db_path = Path(args.db_root) / db_id / f"{db_id}.sqlite"

            norm_gold = normalize_result(item.get("gold_result"))

            for cand in item["candidates"]:
                cand["repair_attempted"] = False
                cand["repair_sql"] = None
                cand["repair_raw_response"] = None
                cand["repair_exec_ok"] = False
                cand["repair_exec_error"] = None
                cand["repair_result"] = None
                cand["repair_result_columns"] = None
                cand["repair_exec_correct"] = False

                if cand.get("exec_ok"):
                    continue

                if repaired_count >= args.max_repairs:
                    continue

                wrong_sql = cand.get("sql")
                exec_error = cand.get("exec_error")

                repaired_sql, raw_response = call_deepseek_repair(
                    client=client,
                    model=args.model,
                    question=question,
                    db_id=db_id,
                    wrong_sql=wrong_sql,
                    exec_error=exec_error,
                )

                cand["repair_attempted"] = True
                cand["repair_sql"] = repaired_sql
                cand["repair_raw_response"] = raw_response

                repaired_count += 1

                print(

                    f"[PROGRESS] repaired {repaired_count}/{args.max_repairs} "

                    f"| idx={item.get('idx')} "

                    f"| db_id={db_id} "

                    f"| source={cand.get('source')}"

                )

                repair_validation = execute_sql(db_path, repaired_sql)

                cand["repair_exec_ok"] = repair_validation["exec_ok"]
                cand["repair_exec_error"] = repair_validation["exec_error"]
                cand["repair_result"] = repair_validation["result"]
                cand["repair_result_columns"] = repair_validation.get("result_columns")
                cand["repair_latency_ms"] = repair_validation["latency_ms"]

                if repair_validation["exec_ok"]:
                    repair_exec_ok_count += 1

                    norm_repair = normalize_result(repair_validation["result"])
                    if norm_repair == norm_gold:
                        cand["repair_exec_correct"] = True
                        repair_correct_count += 1

            out.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"[OK] repaired attempted: {repaired_count}")
    print(f"[OK] repair executable: {repair_exec_ok_count}/{repaired_count}")
    print(f"[OK] repair correct: {repair_correct_count}/{repaired_count}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
