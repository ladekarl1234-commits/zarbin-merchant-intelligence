#!/usr/bin/env bash
# Zarbin launcher (macOS/Linux). Usage: ./scripts/run.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed. Install it from https://docs.astral.sh/uv/ then re-run." >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "Node/npm is required on this development branch to build the latest dashboard UI." >&2
  exit 1
fi

DATA="${ZARIN_DATA_PATH:-data/other_challenge_data.csv.gz}"
if [ ! -f "$DATA" ]; then
  echo "Dataset not found at: $DATA" >&2
  echo "Place other_challenge_data.csv.gz under data/ (or set ZARIN_DATA_PATH)." >&2
  exit 1
fi

echo "Building the latest Merchant + Control Center UI..."
npm --prefix frontend ci
npm --prefix frontend run build

echo "Starting Zarbin... first run builds data marts (~30s)."
echo "Open: http://localhost:8630"
uv run zarin
