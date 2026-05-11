#!/usr/bin/env bash
# Cross-machine reproducibility check (ADR 0001 baseline preservation + ADR 0005
# determinism). Runs the smoke eval and prints a SHA-256 hash of the
# environment-invariant subset of reports/eval_summary.json. The same hash on
# two machines is positive evidence that the public synthetic surface is
# deterministic across hosts; a mismatch surfaces a regression in pinning.
#
# Usage:
#   bash scripts/reproduce_eval.sh                # run + hash
#   BASELINE=<sha> bash scripts/reproduce_eval.sh # compare against expected
#
# The hash deliberately strips:
#   - generated_at, git_commit, git_dirty (provenance, not result)
#   - stage_latency, latency_*  (wall-clock, host-dependent)
#   - any *_ms or *_seconds fields nested anywhere
#
# Everything else (accuracy, groundedness, citation_precision,
# claim_citation_alignment, abstention_accuracy, answer_format_compliance,
# bootstrap CI bounds, judge aggregate) stays in the hash.

set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

REPORT_JSON="${REPORT_JSON:-reports/eval_summary.json}"
HASH_OUT="${HASH_OUT:-reports/eval_summary.reproducibility.sha256}"
EXPECTED="${BASELINE:-}"

log() { printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$1"; }
err() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || err "python3 not on PATH"
command -v shasum >/dev/null 2>&1 || command -v sha256sum >/dev/null 2>&1 \
  || err "neither shasum nor sha256sum available"

log "Running smoke eval (this produces $REPORT_JSON)"
bash scripts/smoke.sh

[[ -f "$REPORT_JSON" ]] || err "smoke did not produce $REPORT_JSON"

log "Computing environment-invariant hash"
HASH=$(python3 - "$REPORT_JSON" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

# Keys at any depth that we strip before hashing because they depend on
# wall-clock or host state, not on pipeline behavior.
EXCLUDE_KEYS = {
    "generated_at",
    "git_commit",
    "git_dirty",
    "duration_ms",
    "wall_time_ms",
    "elapsed_ms",
    "run_manifest",
}
# Suffix/substring patterns that also indicate wall-clock data. Any key
# matching these (or any of its descendant sub-tree) is dropped.
SUFFIX_PATTERNS = (re.compile(r".*_ms$"), re.compile(r".*_seconds$"))
SUBSTRING_PATTERNS = ("latency", "wallclock", "wall_clock")


def _is_clock_key(key: str) -> bool:
    if key in EXCLUDE_KEYS:
        return True
    if any(p.match(key) for p in SUFFIX_PATTERNS):
        return True
    lower = key.lower()
    return any(s in lower for s in SUBSTRING_PATTERNS)


def strip(value):
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if not _is_clock_key(k)}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value


report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
canonical = json.dumps(strip(report), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
print(hashlib.sha256(canonical.encode("utf-8")).hexdigest())
PY
)

mkdir -p "$(dirname "$HASH_OUT")"
printf '%s  %s\n' "$HASH" "$REPORT_JSON" > "$HASH_OUT"

log "Reproducibility hash"
printf '  %s\n' "$HASH"
printf '  (written to %s)\n' "$HASH_OUT"

if [[ -n "$EXPECTED" ]]; then
  if [[ "$HASH" == "$EXPECTED" ]]; then
    printf '\nMATCH: hash equals BASELINE=%s\n' "$EXPECTED"
  else
    printf '\nMISMATCH:\n  expected: %s\n  got:      %s\n' "$EXPECTED" "$HASH"
    exit 2
  fi
fi
