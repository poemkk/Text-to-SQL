#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Build retrievable schema documents (chunks) for Spider RAG from tables.json.

Outputs JSONL with records:
{
  "doc_id": "...",
  "db_id": "...",
  "type": "table" | "column" | "fk",
  "text": "...",
  "meta": {...}
}
"""

import argparse
import json
import os
from typing import Any, Dict, List


def load_tables_json(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_schema_docs(tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []

    for db in tables:
        db_id = db["db_id"]
        table_names = db["table_names_original"]  # list[str]
        column_names = db["column_names_original"]  # list[[table_id, col_name]]
        column_types = db.get("column_types", [])   # list[str]
        primary_keys = set(db.get("primary_keys", []))  # indices into columns
        foreign_keys = db.get("foreign_keys", [])       # list[[col_idx1, col_idx2]]

        # Build per-table column list
        cols_by_table: Dict[int, List[int]] = {i: [] for i in range(len(table_names))}
        for col_idx, (t_id, col_name) in enumerate(column_names):
            if t_id == -1:
                continue  # '*' pseudo column
            cols_by_table[t_id].append(col_idx)

        # Table chunks
        for t_id, t_name in enumerate(table_names):
            col_parts = []
            for col_idx in cols_by_table[t_id]:
                _, c_name = column_names[col_idx]
                c_type = column_types[col_idx] if col_idx < len(column_types) else "unknown"
                flags = []
                if col_idx in primary_keys:
                    flags.append("PK")
                flag_str = f" [{' '.join(flags)}]" if flags else ""
                col_parts.append(f"{c_name}:{c_type}{flag_str}")

            text = (
                f"Database: {db_id}\n"
                f"Table: {t_name}\n"
                f"Columns: " + ", ".join(col_parts)
            )
            docs.append({
                "doc_id": f"{db_id}::table::{t_name}",
                "db_id": db_id,
                "type": "table",
                "text": text,
                "meta": {"table": t_name, "table_id": t_id}
            })

        # Column chunks (fine-grained schema linking)
        for col_idx, (t_id, c_name) in enumerate(column_names):
            if t_id == -1:
                continue
            t_name = table_names[t_id]
            c_type = column_types[col_idx] if col_idx < len(column_types) else "unknown"
            flags = []
            if col_idx in primary_keys:
                flags.append("PK")
            flag_str = f" [{' '.join(flags)}]" if flags else ""
            text = (
                f"Database: {db_id}\n"
                f"Column: {t_name}.{c_name}\n"
                f"Type: {c_type}{flag_str}"
            )
            docs.append({
                "doc_id": f"{db_id}::col::{t_name}.{c_name}",
                "db_id": db_id,
                "type": "column",
                "text": text,
                "meta": {"table": t_name, "column": c_name, "col_idx": col_idx, "table_id": t_id}
            })

        # FK chunks (critical for JOIN path)
        for fk_idx, (c1, c2) in enumerate(foreign_keys):
            t1, n1 = column_names[c1]
            t2, n2 = column_names[c2]
            if t1 == -1 or t2 == -1:
                continue
            table1 = table_names[t1]
            table2 = table_names[t2]
            text = (
                f"Database: {db_id}\n"
                f"ForeignKey: {table1}.{n1} -> {table2}.{n2}\n"
                f"JoinHint: {table1} JOIN {table2} ON {table1}.{n1} = {table2}.{n2}"
            )
            docs.append({
                "doc_id": f"{db_id}::fk::{fk_idx}",
                "db_id": db_id,
                "type": "fk",
                "text": text,
                "meta": {"from": f"{table1}.{n1}", "to": f"{table2}.{n2}", "c1": c1, "c2": c2}
            })

    return docs


def write_jsonl(docs: List[Dict[str, Any]], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", required=True, help="Path to tables.json")
    ap.add_argument("--out", required=True, help="Output JSONL path")
    args = ap.parse_args()

    tables = load_tables_json(args.tables)
    docs = build_schema_docs(tables)
    write_jsonl(docs, args.out)

    # quick stats
    type_cnt = {}
    db_cnt = set()
    for d in docs:
        type_cnt[d["type"]] = type_cnt.get(d["type"], 0) + 1
        db_cnt.add(d["db_id"])

    print(f"[OK] wrote {len(docs)} docs to {args.out}")
    print(f"[OK] db count: {len(db_cnt)}; type counts: {type_cnt}")


if __name__ == "__main__":
    main()