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
TRACE_BACKEND="${BIDMATE_TRACE_BACKEND:-none}"

echo "[entrypoint] Trace backend: $TRACE_BACKEND"
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

# BIDMATE_DEMO_MODE=api (default) | streamlit | both
# - api: FastAPI on $PORT (default 8000)
# - streamlit: Streamlit UI on $STREAMLIT_PORT (default 8501)
# - both: API in background + Streamlit in foreground
MODE="${BIDMATE_DEMO_MODE:-api}"
STREAMLIT_PORT="${BIDMATE_STREAMLIT_PORT:-8501}"

case "$MODE" in
  api)
    echo "[entrypoint] Starting uvicorn on $HOST:$PORT"
    exec uvicorn api.main:app --host "$HOST" --port "$PORT"
    ;;
  streamlit)
    echo "[entrypoint] Starting Streamlit on $HOST:$STREAMLIT_PORT"
    exec streamlit run demo/streamlit_app.py \
      --server.address="$HOST" --server.port="$STREAMLIT_PORT" \
      --server.headless=true --browser.gatherUsageStats=false
    ;;
  both)
    echo "[entrypoint] Starting FastAPI on $HOST:$PORT and Streamlit on $HOST:$STREAMLIT_PORT"
    uvicorn api.main:app --host "$HOST" --port "$PORT" &
    exec streamlit run demo/streamlit_app.py \
      --server.address="$HOST" --server.port="$STREAMLIT_PORT" \
      --server.headless=true --browser.gatherUsageStats=false
    ;;
  *)
    echo "[entrypoint] Unknown BIDMATE_DEMO_MODE=$MODE (expected api|streamlit|both)" >&2
    exit 2
    ;;
esac
