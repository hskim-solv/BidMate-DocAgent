#!/usr/bin/env bash
# Claude Code PreToolUse hook for BidMate-DocAgent (issue #720).
#
# Registered in `.claude/settings.json` with matcher `Edit|MultiEdit|Write`.
# Fires only when the edit target is a `MEMORY.md` index file. Counts the
# *resulting* line count (existing file lines OR Write payload lines) and:
#
#   <  AWARE_THRESHOLD   exit 0 silently
#   >= AWARE_THRESHOLD   exit 0 + stderr awareness ("consider consolidate-memory")
#   >= BLOCK_THRESHOLD   exit 2 + stderr block ("run consolidate-memory before adding more")
#
# A line is appended to `.claude/.hook-fires.log` for every fire so the
# `_self_review.py` axis #5 collector can quantify memory hygiene
# automation ROI without scraping transcripts.
#
# Hook input (stdin, JSON):
#   { "tool_name": "...", "tool_input": { "file_path": "...", "content": "...", ... } }

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Thresholds read from scripts/_governance.py THRESHOLDS dict (issue #778
# single source of truth). Fail-soft to historic PR #720 defaults if the
# governance script is unreachable so the hook never blocks the user
# because of a refactor mistake.
AWARE_THRESHOLD=$(python3 "$REPO_ROOT/scripts/_governance.py" --threshold MEMORY_LINE_AWARE 2>/dev/null || echo 20)
BLOCK_THRESHOLD=$(python3 "$REPO_ROOT/scripts/_governance.py" --threshold MEMORY_LINE_BLOCK 2>/dev/null || echo 30)
readonly AWARE_THRESHOLD BLOCK_THRESHOLD

input=$(cat)

# Extract file_path + content from tool_input.
read -r file_path content_lines < <(printf '%s' "$input" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
except Exception:
    print("", 0)
    sys.exit(0)
ti = d.get("tool_input") or {}
fp = ti.get("file_path") or ""
content = ti.get("content")
n = content.count("\n") + (1 if content and not content.endswith("\n") else 0) if isinstance(content, str) else 0
print(fp, n)
' 2>/dev/null)

# Match only MEMORY.md (basename) — handles project + global paths.
case "$file_path" in
  */MEMORY.md|MEMORY.md) ;;
  *) exit 0 ;;
esac

# Prefer Write payload line count (new-file case where the file does not
# exist yet); fall back to existing file lines. Use `awk` to avoid the
# `wc -l` trailing-newline off-by-one.
if [[ -n "${content_lines:-}" && "$content_lines" =~ ^[0-9]+$ && "$content_lines" -gt 0 ]]; then
  lines="$content_lines"
elif [[ -f "$file_path" ]]; then
  lines=$(awk 'END{print NR}' "$file_path" 2>/dev/null || echo 0)
else
  exit 0
fi

action="ok"
if [[ "$lines" -ge "$BLOCK_THRESHOLD" ]]; then
  action="blocked"
elif [[ "$lines" -ge "$AWARE_THRESHOLD" ]]; then
  action="aware"
fi

# Log fire in the 4-field format the existing `_self_review.py`
# `collect_governance_hooks` parser already understands:
#   <ts>|<action>|<reason>|<path>
# The exact line count is in stderr for the human; the ROI collector
# only needs the action/reason counters.
printf '%s|%s|memory-lines|%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$action" "$file_path" \
  >> "$REPO_ROOT/.claude/.hook-fires.log" 2>/dev/null || true

if [[ "$action" = "blocked" ]]; then
  cat >&2 <<EOF
✋ MEMORY.md index has $lines lines (≥ $BLOCK_THRESHOLD).

    Run \`anthropic-skills:consolidate-memory\` to merge duplicates and
    prune stale entries before adding more. See axis #5 memory hygiene
    in docs/agent-utilization.md.
EOF
  exit 2
elif [[ "$action" = "aware" ]]; then
  cat >&2 <<EOF
⚠️  MEMORY.md index has $lines lines (≥ $AWARE_THRESHOLD).

    Consider running \`anthropic-skills:consolidate-memory\` soon.
EOF
fi

exit 0
