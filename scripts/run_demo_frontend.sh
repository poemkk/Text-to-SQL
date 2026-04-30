#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../demo_frontend"
npm install
npm run dev
