#!/usr/bin/env bash
set -euo pipefail

SPIDER_DIR="data/spider"
DB_DIR="$SPIDER_DIR/database"
TABLES_JSON="$SPIDER_DIR/tables.json"
DEV_JSON="$SPIDER_DIR/dev.json"
TRAIN_JSON="$SPIDER_DIR/train_spider.json"

echo "== Spider dataset check =="
echo "[1] Check files exist..."
for f in "$TABLES_JSON" "$DEV_JSON"; do
  if [[ ! -f "$f" ]]; then
    echo "Missing: $f"
    exit 1
  fi
done
echo "OK: tables.json and dev.json exist."

echo "[2] Check database directory..."
if [[ ! -d "$DB_DIR" ]]; then
  echo "Missing dir: $DB_DIR"
  exit 1
fi
DB_COUNT=$(ls -1 "$DB_DIR" | wc -l | tr -d ' ')
echo "Database folders: $DB_COUNT"

echo "[3] Check sqlite3 availability..."
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 not found. On macOS it is usually available by default."
  exit 1
fi
echo "OK: sqlite3 found."

echo "[4] Pick a random db and test open..."
DB_ID=$(ls -1 "$DB_DIR" | head -n 1)
SQLITE_PATH="$DB_DIR/$DB_ID/$DB_ID.sqlite"
if [[ ! -f "$SQLITE_PATH" ]]; then
  echo "Missing sqlite: $SQLITE_PATH"
  exit 1
fi
echo "Sample db_id: $DB_ID"
echo "SQLite: $SQLITE_PATH"

echo "[5] List tables (first 20):"
sqlite3 "$SQLITE_PATH" ".tables" | tr ' ' '\n' | head -n 20

echo "== DONE =="
