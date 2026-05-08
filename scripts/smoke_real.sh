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
EMBEDDING_BACKEND="${EMBEDDING_BACKEND:-hashing}"
INGESTION_MODE="${INGESTION_MODE:-csv-text}"

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
require_file "app.py"
require_file "eval/run_eval.py"
require_file "$METADATA_CSV"
require_dir "$FILES_DIR"

mkdir -p "$INDEX_DIR" "$OUTPUT_DIR" "$REPORT_DIR"

log "Building real-data index"
python3 scripts/build_index.py \
  --metadata_csv "$METADATA_CSV" \
  --files_dir "$FILES_DIR" \
  --ingestion_mode "$INGESTION_MODE" \
  --output_dir "$INDEX_DIR" \
  --embedding_backend "$EMBEDDING_BACKEND"

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
AGGREGATE_JSON="$REPORT_DIR/eval_aggregate.json"
python3 -c 'import json, sys; src, dst = sys.argv[1:3]; data = json.load(open(src, encoding="utf-8")); keep = {key: data.get(key) for key in ("mode", "num_predictions", "accuracy", "groundedness", "citation_precision", "abstention", "answer_format_compliance", "retrieval", "latency", "retry", "retry_cost", "retry_reason_counts", "by_query_type")}; json.dump(keep, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)' "$REPORT_JSON" "$AGGREGATE_JSON"

log "Real-data smoke test completed successfully"
echo "Generated artifacts:"
echo "- Index dir:   $INDEX_DIR"
echo "- Outputs dir: $OUTPUT_DIR"
echo "- Report file: $REPORT_JSON"
echo "- Aggregate file: $AGGREGATE_JSON"
