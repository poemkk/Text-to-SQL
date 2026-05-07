#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "[demo] Error: python/python3 not found."
  echo "[demo] Please install Python or create .venv first."
  exit 1
fi

cleanup() {
  kill 0 >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

cd "$ROOT_DIR"

echo "[demo] Starting backend: http://127.0.0.1:8000"
"$PYTHON_BIN" -m uvicorn --app-dir "$ROOT_DIR/demo_backend" main:app --reload --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

echo "[demo] Starting frontend: http://127.0.0.1:5173"
cd "$ROOT_DIR/demo_frontend"
npm run dev -- --host 127.0.0.1 --port 5173 &
FRONTEND_PID=$!

echo "[demo] Ready:"
echo "  Frontend: http://127.0.0.1:5173"
echo "  Backend : http://127.0.0.1:8000"
echo "[demo] Press Ctrl+C to stop both."

while kill -0 "$BACKEND_PID" >/dev/null 2>&1 && kill -0 "$FRONTEND_PID" >/dev/null 2>&1; do
  sleep 1
done
