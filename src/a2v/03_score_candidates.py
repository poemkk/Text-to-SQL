import argparse
import json
import sqlite3
import time
from pathlib import Path


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
        default="runs/outputs/a2v/validated_spider100.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/scored_spider100.jsonl",
    )
    parser.add_argument(
        "--db_root",
        type=str,
        default="data/spider/database",
    )
    args = parser.parse_args()

    rows = read_jsonl(args.in_file)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_candidates = 0
    correct_candidates = 0

    with out_path.open("w", encoding="utf-8") as out:
        for item in rows:
            db_id = item["db_id"]
            db_path = Path(args.db_root) / db_id / f"{db_id}.sqlite"

            gold_sql = item.get("gold")
            gold_exec = execute_sql(db_path, gold_sql)

            item["gold_exec_ok"] = gold_exec["exec_ok"]
            item["gold_exec_error"] = gold_exec["exec_error"]
            item["gold_result"] = gold_exec["result"]
            item["gold_result_columns"] = gold_exec.get("result_columns")

            norm_gold = normalize_result(gold_exec["result"])

            for cand in item["candidates"]:
                total_candidates += 1

                if cand.get("exec_ok") and gold_exec["exec_ok"]:
                    norm_pred = normalize_result(cand.get("result"))
                    exec_correct = norm_pred == norm_gold
                else:
                    exec_correct = False

                cand["exec_correct"] = exec_correct

                if exec_correct:
                    correct_candidates += 1

            out.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"[OK] scored examples: {len(rows)}")
    print(f"[OK] total candidates: {total_candidates}")
    print(f"[OK] correct candidates: {correct_candidates}")
    print(f"[OK] candidate-level execution accuracy: {correct_candidates / total_candidates:.3f}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
