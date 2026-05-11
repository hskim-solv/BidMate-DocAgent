#!/usr/bin/env bash
# Claude Code PreToolUse hook for BidMate-DocAgent.
#
# Registered in `.claude/settings.json` with matcher `Edit|MultiEdit|Write`.
# Fires before Claude modifies a file; prints a stderr awareness warning
# when the target is a load-bearing path (per CLAUDE.md), reminding Claude
# to consider ADR impact and the PR template's real-data delta requirement.
#
# Behavior: NEVER blocks. Always exits 0. Pure awareness layer.
#
# Hook input (stdin, JSON):
#   { "tool_name": "...", "tool_input": { "file_path": "...", ... }, ... }

set -u

# Read JSON from stdin.
input=$(cat)

# Extract tool_input.file_path. Use python3 — guaranteed in this repo.
file_path=$(printf '%s' "$input" | python3 -c 'import json,sys
try:
    d = json.loads(sys.stdin.read())
    print(d.get("tool_input", {}).get("file_path", ""))
except Exception:
    pass' 2>/dev/null)

if [[ -z "$file_path" ]]; then
  exit 0
fi

# Load-bearing patterns (extended regex). Mirror CLAUDE.md "Load-bearing
# files" section. Anchored to "/" to avoid matching inside arbitrary
# substrings.
LOAD_BEARING_PATTERNS=(
  '/rag_core\.py$'
  '/ingestion\.py$'
  '/visual_ingestion\.py$'
  '/eval/'
  '/api/'
  '/docs/adr/'
)

for pat in "${LOAD_BEARING_PATTERNS[@]}"; do
  if [[ "$file_path" =~ $pat ]]; then
    cat >&2 <<EOF
⚠️  Load-bearing file: $file_path

    ADRs to consider (CLAUDE.md):
      - ADR 0001 (preserve naive baseline)
      - ADR 0003 (answer contract — bump schema_version if breaking)
      - ADR 0005 (eval split — public synthetic / private local)

    PR template item 5b (real-eval-delta aggregate table) will be required
    when this change ships.
EOF
    break
  fi
done

exit 0
