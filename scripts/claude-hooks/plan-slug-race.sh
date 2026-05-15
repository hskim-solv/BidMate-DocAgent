#!/usr/bin/env bash
# Claude Code PreToolUse hook — plan-slug race detector (issue #779).
#
# Registered (user-globally) in `~/.claude/settings.json` with matcher
# `Write`. Fires before Claude writes any file. Refuses to overwrite a
# `~/.claude/plans/<slug>.md` that was last touched within the past 5
# minutes by a *different* worktree, blocking the silent overwrite
# pattern observed on 2026-05-15 (multiple worktree sessions racing on
# the same random slug).
#
# Behavior:
#   - exit 0 : safe / not applicable / fail-open
#   - exit 2 : refuse the Write, print rationale + remediation to stderr
#
# Fail-open philosophy: a buggy hook silently letting one bad write
# through is recoverable (the user notices the wrong content); a buggy
# hook silently blocking every plan write is not.
#
# Hook input (stdin, JSON):
#   { "tool_name": "Write",
#     "tool_input": { "file_path": "...", "content": "..." }, ... }

set -u

THRESHOLD_SECONDS=${PLAN_SLUG_RACE_THRESHOLD:-300}
SNIFF_BYTES=${PLAN_SLUG_RACE_SNIFF_BYTES:-200}

# Read tool input from stdin and extract tool name + target path. We
# bail (exit 0) on any parsing problem — the hook must never become a
# noisy blocker.
input=$(cat)

read_field() {
  printf '%s' "$input" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    v = d.get('$1', '') if '$1' in ('tool_name',) else d.get('tool_input', {}).get('$1', '')
    print(v)
except Exception:
    pass
" 2>/dev/null
}

tool_name=$(read_field tool_name)
target=$(read_field file_path)

if [[ "$tool_name" != "Write" ]]; then
  exit 0
fi
if [[ -z "$target" ]]; then
  exit 0
fi

# Resolve `~` and relative paths so the matcher works regardless of cwd.
case "$target" in
  "~"|"~/"*)
    target="${HOME}${target:1}"
    ;;
esac
if [[ "$target" != /* ]]; then
  target="$(pwd)/$target"
fi

# Only fire for plans dir.  Use a glob so different home dirs work.
plans_dir="${HOME}/.claude/plans"
case "$target" in
  "${plans_dir}/"*.md) ;;
  *) exit 0 ;;
esac

# No existing file → no race.
if [[ ! -f "$target" ]]; then
  exit 0
fi

# Recent mtime check (portable: BSD `stat -f %m` on macOS, GNU `stat -c %Y` on Linux).
if mtime=$(stat -f %m "$target" 2>/dev/null); then
  :
elif mtime=$(stat -c %Y "$target" 2>/dev/null); then
  :
else
  exit 0
fi
now=$(date +%s)
age=$(( now - mtime ))
if (( age >= THRESHOLD_SECONDS )); then
  exit 0
fi

# Sniff the first chunk for a worktree marker. The convention (see
# `project_code_polish_backlog.md` 2026-05-15 entry) is to declare
# the writing worktree in the first 200 chars, e.g.:
#
#   본 plan은 worktree `gifted-turing-c2761d` 의 deliverable.
#
# A fingerprint that's `worktree` followed (within ~30 chars) by a
# backtick-quoted slug is enough — we tolerate language/punctuation.
head_chunk=$(head -c "$SNIFF_BYTES" "$target" 2>/dev/null)
marker_slug=$(printf '%s' "$head_chunk" | python3 -c "
import re, sys
text = sys.stdin.read()
m = re.search(r'worktree[^a-zA-Z0-9_\\-]{0,30}\`([A-Za-z0-9_\\-]+)\`', text)
if m:
    print(m.group(1))
" 2>/dev/null)

if [[ -z "$marker_slug" ]]; then
  # No marker — we can't prove a cross-worktree race. Stay quiet to keep
  # the false-positive rate low; same-session re-writes are common.
  exit 0
fi

# Resolve the current worktree slug from CWD. Pattern:
#   .../<project>/.claude/worktrees/<slug>/...
cwd_slug=$(pwd | python3 -c "
import re, sys
m = re.search(r'/\\.claude/worktrees/([A-Za-z0-9_\\-]+)(?:/|$)', sys.stdin.read().strip())
print(m.group(1) if m else '')
" 2>/dev/null)

if [[ -z "$cwd_slug" ]]; then
  # Caller is the main checkout (not a worktree) or an unrecognized path.
  # Don't block — let main-checkout edits proceed silently.
  exit 0
fi

if [[ "$cwd_slug" == "$marker_slug" ]]; then
  # Same worktree → same author → not a race.
  exit 0
fi

# Different worktree wrote it < THRESHOLD_SECONDS ago — block.
{
  echo "❌ plan-slug race: '$target' was written ${age}s ago by"
  echo "   worktree '${marker_slug}' (declared in its first ${SNIFF_BYTES} chars)."
  echo "   Current worktree '${cwd_slug}' is about to overwrite it."
  echo ""
  echo "   Convention (issue #779): write to a suffixed path like"
  echo "     ${target%.md}-${cwd_slug}.md"
  echo "   or pick a different filename entirely."
  echo ""
  echo "   Override (only when you genuinely intend to replace the other"
  echo "   worktree's plan): set PLAN_SLUG_RACE_THRESHOLD=0 in the hook"
  echo "   environment for this invocation."
} >&2
exit 2
