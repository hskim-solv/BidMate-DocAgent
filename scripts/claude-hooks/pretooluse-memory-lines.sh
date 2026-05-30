#!/usr/bin/env bash
# Claude Code PreToolUse hook for BidMate-DocAgent (issue #720, #1683).
#
# Enforcement: graduated (awareness >=AWARE_THRESHOLD, block >=BLOCK_THRESHOLD).
# Classification rationale: dual-mode — stderr warning then exit 2 refuse.
# See scripts/claude-hooks/README.md for the full enforcement taxonomy.
#
# Registered in `.claude/settings.json` with matcher `Edit|MultiEdit|Write`.
# Fires only when the edit target is a `MEMORY.md` index file. It counts the
# *resulting* line count — i.e. what the file WOULD have after the tool runs —
# for all three tools:
#
#   Write     -> line count of the new `content` (whole-file payload)
#   Edit      -> existing file with `old_string`->`new_string` applied
#   MultiEdit -> existing file with every edit applied in sequence
#
# and then:
#
#   <  AWARE_THRESHOLD                          exit 0 silently
#   >= AWARE_THRESHOLD                          exit 0 + stderr awareness
#   >= BLOCK_THRESHOLD AND not a shrink         exit 2 + stderr block
#
# The "not a shrink" guard (issue #1683) is what unblocks consolidation: an
# edit whose result is under the cap, OR a pure shrink (result < current) even
# while still over the cap, is always allowed. Previously the hook only read
# the Write `content` field; for Edit/MultiEdit (which carry old_string/
# new_string, not content) it fell back to counting the EXISTING file, so it
# blocked shrinking edits too — making the consolidate-memory remedy it asks
# for impossible to apply via Edit.
#
# A line is appended to `.claude/.hook-fires.log` for every fire so the
# `_self_review.py` axis #5 collector can quantify memory hygiene
# automation ROI without scraping transcripts.
#
# Hook input (stdin, JSON):
#   { "tool_name": "...", "tool_input": { "file_path": "...", "content": "...",
#     "old_string": "...", "new_string": "...", "edits": [...] } }

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

# Compute the resulting + current line count for MEMORY.md targets. Output is
# `<resulting> <current> <file_path>` so `read -r a b rest` captures a path
# containing spaces in the final variable. Non-MEMORY.md targets short-circuit
# to `0 0 <path>` (bash exits 0 below). Any parse/read failure is fail-soft.
read -r resulting current file_path < <(printf '%s' "$input" | python3 -c '
import json, os, sys


def count_lines(s):
    if not s:
        return 0
    return s.count("\n") + (0 if s.endswith("\n") else 1)


try:
    d = json.loads(sys.stdin.read())
except Exception:
    print("0 0 ")
    sys.exit(0)

ti = d.get("tool_input") or {}
fp = ti.get("file_path") or ""

# Only compute for MEMORY.md index files (project + global paths).
if os.path.basename(fp) != "MEMORY.md":
    print("0 0 " + fp)
    sys.exit(0)

# Current on-disk line count (0 if the file is new or unreadable).
existing = ""
try:
    with open(fp, "r", encoding="utf-8") as fh:
        existing = fh.read()
except Exception:
    existing = ""
current = count_lines(existing)

# Resulting line count after the tool applies. Default to current so any
# unexpected shape fails safe (treated as no shrink).
resulting = current
content = ti.get("content")
try:
    if isinstance(content, str):
        # Write: content is the whole new file.
        resulting = count_lines(content)
    elif isinstance(ti.get("edits"), list):
        # MultiEdit: apply each edit in sequence.
        text = existing
        for e in ti["edits"]:
            old = e.get("old_string", "")
            new = e.get("new_string", "")
            if old == "":
                continue
            if e.get("replace_all"):
                text = text.replace(old, new)
            else:
                text = text.replace(old, new, 1)
        resulting = count_lines(text)
    elif "old_string" in ti:
        # Edit: single replacement (only if the anchor is actually present).
        old = ti.get("old_string", "")
        new = ti.get("new_string", "")
        if old != "" and old in existing:
            if ti.get("replace_all"):
                resulting = count_lines(existing.replace(old, new))
            else:
                resulting = count_lines(existing.replace(old, new, 1))
except Exception:
    resulting = current

print("{} {} {}".format(resulting, current, fp))
' 2>/dev/null)

# Match only MEMORY.md (basename) — handles project + global paths.
case "$file_path" in
  */MEMORY.md|MEMORY.md) ;;
  *) exit 0 ;;
esac

# Numeric guards — fail-soft to a permissive default on any non-integer.
[[ "${resulting:-}" =~ ^[0-9]+$ ]] || exit 0
[[ "${current:-}" =~ ^[0-9]+$ ]] || current=0

action="ok"
# Block only when the RESULT is still over the cap AND the edit is not a
# shrink (issue #1683). A result under the cap, or any shrink toward it, is
# allowed so that consolidate-memory edits can actually land.
if [[ "$resulting" -ge "$BLOCK_THRESHOLD" && "$resulting" -ge "$current" ]]; then
  action="blocked"
elif [[ "$resulting" -ge "$AWARE_THRESHOLD" ]]; then
  action="aware"
fi

# Log fire in the 5-field telemetry format (ADR 0060). action in {ok, aware,
# blocked}. The exact line counts are in stderr for the human; the ROI
# collector only needs the action/category counters.
python3 "$REPO_ROOT/scripts/_governance.py" --emit-fire \
  --outcome "$action" --hook memory-lines --category line-count \
  --path "$file_path" \
  --fire-log "$REPO_ROOT/.claude/.hook-fires.log" 2>/dev/null || true

if [[ "$action" = "blocked" ]]; then
  cat >&2 <<EOF
✋ MEMORY.md index would have $resulting lines (>= $BLOCK_THRESHOLD) and is not shrinking.

    Run \`anthropic-skills:consolidate-memory\` to merge duplicates and
    prune stale entries. An edit that brings the index back under
    $BLOCK_THRESHOLD lines (or otherwise shrinks it) is allowed. See axis #5
    memory hygiene in docs/agent-utilization.md.
EOF
  exit 2
elif [[ "$action" = "aware" ]]; then
  cat >&2 <<EOF
⚠️  MEMORY.md index would have $resulting lines (>= $AWARE_THRESHOLD).

    Consider running \`anthropic-skills:consolidate-memory\` soon.
EOF
fi

exit 0
