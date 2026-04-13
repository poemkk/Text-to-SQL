#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
from typing import Any, List, Tuple, Optional


def run_sqlite_query(sqlite_path: str, sql: str, timeout: float = 5.0) -> Tuple[bool, Optional[List[Tuple[Any, ...]]], Optional[str]]:
    """
    Returns (ok, rows, error).
    - ok=True if executed successfully
    - rows is a list of tuples (fetched all)
    """
    try:
        conn = sqlite3.connect(sqlite_path, timeout=timeout)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()
        return True, rows, None
    except Exception as e:
        return False, None, str(e)