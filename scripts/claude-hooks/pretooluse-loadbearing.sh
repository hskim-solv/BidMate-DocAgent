#!/usr/bin/env bash
# Claude Code PreToolUse hook for BidMate-DocAgent.
#
# Enforcement: awareness (stderr message only, never refuses tool call).
# Classification rationale: NEVER blocks (line below); pure reminder layer.
# See scripts/claude-hooks/README.md for the full enforcement taxonomy.
#
# Registered in `.claude/settings.json` with matcher `Edit|MultiEdit|Write`.
# Fires before Claude modifies a file; prints a stderr awareness warning
# when the target is a load-bearing path (per CLAUDE.md), reminding Claude
# to consider ADR impact and to attach real-data evidence where it helps.
#
# Behavior: NEVER blocks. Always exits 0. Pure awareness layer.
#
# Hook input (stdin, JSON):
#   { "tool_name": "...", "tool_input": { "file_path": "...", ... }, ... }

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

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

# Load-bearing list lives in scripts/_governance.py (single source of
# truth, also consumed by .githooks/pre-push reminders).
if python3 "$REPO_ROOT/scripts/_governance.py" --is-load-bearing "$file_path" 2>/dev/null; then
  # Fire log for /self-review-quarterly governance ROI axis (issue #495).
  # v2-5field format per ADR 0060 (issue #1039). Gitignored via `.claude/*`.
  python3 "$REPO_ROOT/scripts/_governance.py" --emit-fire \
    --outcome aware --hook loadbearing --category file-edit \
    --path "$file_path" \
    --fire-log "$REPO_ROOT/.claude/.hook-fires.log" 2>/dev/null || true
  cat >&2 <<EOF
⚠️  Load-bearing file: $file_path

    ADRs to consider (CLAUDE.md):
      - ADR 0001 (preserve naive baseline)
      - ADR 0003 (answer contract — bump schema_version if breaking)
      - ADR 0005 (eval split — public fixture smoke / private internal)

    Consider attaching real-data evidence (`make real-eval-delta`) when this
    change ships — recommended, no longer gated (ADR 0084 deprecated §5b).
EOF
fi

exit 0
