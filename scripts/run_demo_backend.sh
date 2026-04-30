#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../demo_backend"
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
