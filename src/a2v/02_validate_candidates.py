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
            "latency_ms": 0.0,
        }

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()

        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "exec_ok": True,
            "exec_error": None,
            "result": rows,
            "latency_ms": latency_ms,
        }

    except Exception as e:
        latency_ms = round((time.time() - start) * 1000, 3)

        return {
            "exec_ok": False,
            "exec_error": str(e),
            "result": None,
            "latency_ms": latency_ms,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--in_file",
        type=str,
        default="runs/outputs/a2v/candidates_spider100.jsonl",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="runs/outputs/a2v/validated_spider100.jsonl",
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
    ok_candidates = 0

    with out_path.open("w", encoding="utf-8") as out:
        for item in rows:
            db_id = item["db_id"]
            db_path = Path(args.db_root) / db_id / f"{db_id}.sqlite"

            for cand in item["candidates"]:
                sql = cand.get("sql")
                validation = execute_sql(db_path, sql)

                cand.update(validation)

                total_candidates += 1
                if validation["exec_ok"]:
                    ok_candidates += 1

            out.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"[OK] validated examples: {len(rows)}")
    print(f"[OK] total candidates: {total_candidates}")
    print(f"[OK] executable candidates: {ok_candidates}")
    print(f"[OK] output: {out_path}")


if __name__ == "__main__":
    main()
