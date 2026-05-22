#!/usr/bin/env bash
set -euo pipefail

# Local-only smoke test for private real RFP data.
# Run from the repository root:
#   bash scripts/smoke_real.sh
# Optional overrides:
#   METADATA_CSV=data/data_list.csv FILES_DIR=data/files INDEX_DIR=data/index/real100 bash scripts/smoke_real.sh

METADATA_CSV="${METADATA_CSV:-data/data_list.csv}"
FILES_DIR="${FILES_DIR:-data/files}"
INDEX_DIR="${INDEX_DIR:-data/index/real100}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs/real100}"
REPORT_DIR="${REPORT_DIR:-reports/real100}"
QUERY="${QUERY:-한영대학교 특성화 맞춤형 교육환경 구축 사업의 사업기간과 사업예산 알려줘}"
EVAL_CONFIG="${EVAL_CONFIG:-eval/real_config.local.yaml}"
# EMBEDDING_BACKEND default `hashing` = feature-hashing BoW (rag_embedding.py::
# hashing_embeddings) — deterministic + offline + no model download, so it is
# the CI-safe SSoT baseline (ADR 0061). BUT it is *semantic-blind*: dense/hybrid
# retrieval recall measured on a hashing index is meaningless (issue #1295).
# For semantic retrieval measurement build with sentence-transformers + a real
# model, e.g. `make real-eval-semantic` (EMBEDDING_BACKEND=sentence-transformers
# MODEL=BAAI/bge-m3). The #1212 provenance banner WARNs at run start when an
# index is hashing-backed.
EMBEDDING_BACKEND="${EMBEDDING_BACKEND:-hashing}"
# MODEL empty → build_index.py uses its DEFAULT_EMBEDDING_MODEL; pass-through
# only when set so the default `make real-eval` invocation stays byte-identical.
MODEL="${MODEL:-}"
INGESTION_MODE="${INGESTION_MODE:-csv-text}"
HWP_LOADER="${HWP_LOADER:-kordoc}"
PDF_LOADER="${PDF_LOADER:-kordoc}"

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$1"
}

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "Missing required file: $path" >&2
    exit 1
  fi
}

require_dir() {
  local path="$1"
  if [[ ! -d "$path" ]]; then
    echo "Missing required directory: $path" >&2
    exit 1
  fi
}

require_file "scripts/build_index.py"
require_file "scripts/validate_data_list.py"
require_file "app.py"
require_file "eval/run_eval.py"
require_file "$METADATA_CSV"
require_dir "$FILES_DIR"

mkdir -p "$INDEX_DIR" "$OUTPUT_DIR" "$REPORT_DIR"

log "Validating data_list.csv schema"
if ! python3 scripts/validate_data_list.py \
  --metadata_csv "$METADATA_CSV" \
  --files_dir "$FILES_DIR" \
  --output_path "$REPORT_DIR/data_list_validation.json"; then
  echo "[WARN] data_list.csv has row-level issues; review $REPORT_DIR/data_list_validation.json before proceeding." >&2
fi

log "Building real-data index"
MODEL_ARGS=()
if [[ -n "$MODEL" ]]; then
  MODEL_ARGS=(--model "$MODEL")
fi
python3 scripts/build_index.py \
  --metadata_csv "$METADATA_CSV" \
  --files_dir "$FILES_DIR" \
  --ingestion_mode "$INGESTION_MODE" \
  --hwp_loader "$HWP_LOADER" \
  --pdf_loader "$PDF_LOADER" \
  --output_dir "$INDEX_DIR" \
  --embedding_backend "$EMBEDDING_BACKEND" \
  "${MODEL_ARGS[@]+"${MODEL_ARGS[@]}"}"

log "Running real-data sample query"
python3 app.py --input_dir "$INDEX_DIR" --output_dir "$OUTPUT_DIR" --query "$QUERY"

if [[ ! -f "$EVAL_CONFIG" ]]; then
  log "Skipping real-data eval"
  echo "Local eval config not found: $EVAL_CONFIG"
  echo "Create it from eval/real_config.example.yaml to run real-data gold evaluation."
  echo "Generated artifacts:"
  echo "- Index dir:   $INDEX_DIR"
  echo "- Outputs dir: $OUTPUT_DIR"
  exit 0
fi

log "Running real-data evaluation"
python3 eval/run_eval.py --index_dir "$INDEX_DIR" --output_dir "$REPORT_DIR" --config "$EVAL_CONFIG"

REPORT_JSON="$REPORT_DIR/eval_summary.json"
require_file "$REPORT_JSON"

log "Real-data smoke test completed successfully"
echo "Generated artifacts:"
echo "- Index dir:   $INDEX_DIR"
echo "- Outputs dir: $OUTPUT_DIR"
echo "- Report file: $REPORT_JSON"
