#!/usr/bin/env bash
# Entrypoint for the BidMate-DocAgent demo container.
#
# If no index.json is present under BIDMATE_INDEX_DIR, build one from
# data/raw using the hashing embedding backend (no network needed),
# then launch uvicorn. This keeps the reviewer flow to a single
# ``docker run`` command without burying the index inside the image.
set -euo pipefail

INDEX_DIR="${BIDMATE_INDEX_DIR:-/app/data/index}"
INPUT_DIR="${BIDMATE_RAW_DIR:-/app/data/raw}"
EMBEDDING_BACKEND="${EMBEDDING_BACKEND:-hashing}"
HOST="${BIDMATE_API_HOST:-0.0.0.0}"
PORT="${BIDMATE_API_PORT:-8000}"

mkdir -p "$INDEX_DIR"
if [[ ! -f "$INDEX_DIR/index.json" ]]; then
  echo "[entrypoint] No index.json under $INDEX_DIR; building from $INPUT_DIR (backend=$EMBEDDING_BACKEND)"
  python scripts/build_index.py \
    --input_dir "$INPUT_DIR" \
    --output_dir "$INDEX_DIR" \
    --embedding_backend "$EMBEDDING_BACKEND"
else
  echo "[entrypoint] Reusing existing index at $INDEX_DIR/index.json"
fi

echo "[entrypoint] Starting uvicorn on $HOST:$PORT"
exec uvicorn api.main:app --host "$HOST" --port "$PORT"
