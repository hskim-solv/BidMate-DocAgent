#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

# Minimal end-to-end smoke test for Agentic-VLM.
# Run from the repository root:
#   bash scripts/smoke.sh
# Optional overrides:
#   INPUT_DIR=data/raw INDEX_DIR=data/index OUTPUT_DIR=outputs REPORT_DIR=reports QUERY="..." bash scripts/smoke.sh
#   EMBEDDING_BACKEND=auto bash scripts/smoke.sh

INPUT_DIR="${INPUT_DIR:-data/raw}"
INDEX_DIR="${INDEX_DIR:-data/index}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs}"
REPORT_DIR="${REPORT_DIR:-reports}"
QUERY="${QUERY:-기관 A와 기관 B의 AI 요구사항 차이 알려줘}"
EVAL_CONFIG="${EVAL_CONFIG:-eval/config.yaml}"
README_PATH="${README_PATH:-README.md}"
EMBEDDING_BACKEND="${EMBEDDING_BACKEND:-hashing}"

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
require_file "scripts/update_readme_metrics.py"
require_file "scripts/run_benchmark.py"
require_file "scripts/summarize_benchmark.py"
require_file "benchmarks/suites/public_synthetic_rfp.yaml"
require_file "benchmarks/ablations/rag_quality_axes.yaml"
require_file "benchmarks/registry.schema.json"
require_file "benchmarks/registry.json"
require_file "docs/benchmarking.md"
require_file "docs/ablation-results.md"
require_file "$EVAL_CONFIG"
require_file "$README_PATH"
require_dir "$INPUT_DIR"

mkdir -p "$INDEX_DIR" "$OUTPUT_DIR" "$REPORT_DIR"

log "Building index"
python3 scripts/build_index.py \
  --input_dir "$INPUT_DIR" \
  --output_dir "$INDEX_DIR" \
  --embedding_backend "$EMBEDDING_BACKEND"

log "Running sample query"
python3 app.py --input_dir "$INDEX_DIR" --output_dir "$OUTPUT_DIR" --query "$QUERY"

log "Running evaluation"
python3 eval/run_eval.py --index_dir "$INDEX_DIR" --output_dir "$REPORT_DIR" --config "$EVAL_CONFIG"

REPORT_JSON="$REPORT_DIR/eval_summary.json"
require_file "$REPORT_JSON"

log "Checking README metrics consistency"
if [[ "$REPORT_DIR" == "reports" ]]; then
  python3 scripts/update_readme_metrics.py --report "$REPORT_JSON" --readme "$README_PATH"
  python3 scripts/update_readme_metrics.py --report "$REPORT_JSON" --readme "$README_PATH" --check
else
  echo "Skipping README metrics check for non-default REPORT_DIR=$REPORT_DIR"
fi

log "Smoke test completed successfully"
echo "Generated artifacts:"
echo "- Index dir:   $INDEX_DIR"
echo "- Outputs dir: $OUTPUT_DIR"
echo "- Report file: $REPORT_JSON"
