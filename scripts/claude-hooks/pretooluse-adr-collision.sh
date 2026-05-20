#!/usr/bin/env bash
# Claude Code PreToolUse hook for BidMate-DocAgent — cross-worktree ADR
# number collision guard.
#
# Registered in `.claude/settings.json` with matcher `Edit|MultiEdit|Write`.
# Fires before Claude writes a *new* `docs/adr/<NNNN>-*.md` and refuses the
# Write when <NNNN> is already reserved by an OPEN PR on another
# branch/worktree — the gap the filesystem-only pre-commit collision check
# (`scripts/_governance.py --check-adr-collision`) structurally cannot see.
#
# Why this exists (issue #1069):
#   - pre-commit `--check-adr-collision` only inspects locally-staged ADR
#     files; it is deliberately offline (no `gh`). Two worktrees each
#     reserving 0060 both pass pre-commit, then collide at merge
#     (precedent: 0022→0023, 0023→0025, 0029→0030).
#   - CLAUDE.md asks for a manual `gh pr list --search "ADR" --state open`
#     before drafting. That manual step is the one that keeps getting
#     skipped. This hook automates exactly it, at write time.
#
# Behavior:
#   - exit 0 : safe / not applicable / fail-open (gh absent, network fail,
#              no token, empty list, parse failure)
#   - exit 2 : refuse the Write — number collides with a named open PR
#
# Scope (intentional narrowness, mirrors pretooluse-adr-template.sh):
#   - Only new-ADR Writes (Write tool + docs/adr/<NNNN>-*.md + file absent).
#   - Edits to existing ADRs pass through (grandfathered).
#   - Local same-number collisions remain pre-commit's job; this hook owns
#     the cross-worktree (open-PR) case only.
#
# Hook input (stdin, JSON):
#   { "tool_name": "Write", "tool_input": { "file_path": "...", ... }, ... }

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

input=$(cat)

# Parse tool_name + file_path in one python pass (content not needed — we
# only care about the filename's NNNN). Malformed JSON → empty → fail-open.
parsed=$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
ti = d.get("tool_input", {}) or {}
print(ti.get("file_path", "") or "")
print(d.get("tool_name", "") or "")
' 2>/dev/null)

file_path=$(printf '%s' "$parsed" | sed -n '1p')
tool_name=$(printf '%s' "$parsed" | sed -n '2p')

# Gate 1: not a Write — Edit / MultiEdit on existing files are out of scope.
[[ "$tool_name" != "Write" ]] && exit 0

# Gate 2: not a new-ADR filename. The 4-digit prefix mirrors the established
# numbering (docs/adr/_template.md is excluded by the [0-9]{4} requirement).
[[ "$file_path" =~ docs/adr/[0-9]{4}-[a-z0-9-]+\.md$ ]] || exit 0

# Gate 3: file already exists → edit/rewrite of an existing ADR, grandfathered.
[[ -e "$file_path" ]] && exit 0

# Extract the 4-digit number from the basename.
adr_num=$(basename "$file_path" | grep -oE '^[0-9]{4}')
[[ -z "$adr_num" ]] && exit 0

# Gate 4 (fail-open): gh absent → soft skip. pre-commit is the backstop.
command -v gh >/dev/null 2>&1 || {
  printf 'ℹ️  gh CLI absent — skipping cross-worktree ADR collision check for %s.\n' \
    "$(basename "$file_path")" >&2
  exit 0
}

# Query open PRs whose title mentions an ADR. --search widens the net; we
# re-filter locally by exact number so a loose match can never over-block.
# `timeout` guards a hung network call when available (GNU coreutils); on
# systems without it (stock macOS) we fall back to a bare call so the check
# still runs rather than silently fail-open.
if command -v timeout >/dev/null 2>&1; then
  prs=$(timeout 8 gh pr list --search "ADR in:title" --state open \
          --json number,title,headRefName 2>/dev/null || true)
else
  prs=$(gh pr list --search "ADR in:title" --state open \
          --json number,title,headRefName 2>/dev/null || true)
fi

# Gate 5 (fail-open): empty / "[]" / network error / no token → pass.
[[ -z "$prs" || "$prs" == "[]" ]] && exit 0

# Parse each PR's reserved ADR number from title + headRefName, zero-pad
# insensitive. Body is intentionally ignored: bodies cite *other* ADRs
# constantly ("supersedes 0012") → false positives. Re-filter by exact
# integer so the loose --search cannot over-block.
hit=$(printf '%s' "$prs" | ADR_NUM="$adr_num" python3 -c '
import json, os, re, sys
target = int(os.environ["ADR_NUM"])
pat = re.compile(r"adr[\s#:_-]*0*(\d{1,4})", re.I)
try:
    prs = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
for p in prs:
    nums = set()
    for field in ("title", "headRefName"):
        for m in pat.findall(p.get(field, "") or ""):
            nums.add(int(m))
    if target in nums:
        print("{}\t{}\t{}".format(
            p.get("number", "?"), p.get("title", ""), p.get("headRefName", "")))
        break
' 2>/dev/null)

# No open PR reserves this number → safe.
[[ -z "$hit" ]] && exit 0

pr_number=$(printf '%s' "$hit" | cut -f1)
pr_title=$(printf '%s' "$hit" | cut -f2)
pr_branch=$(printf '%s' "$hit" | cut -f3)
adr_basename=$(basename "$file_path")

printf '%s|blocked|adr-collision|%s|open_pr=%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$adr_basename" "$pr_number" \
  >> "$REPO_ROOT/.claude/.hook-fires.log" 2>/dev/null || true

cat >&2 <<EOF
⛔ Refusing Write of new ADR \`$adr_basename\`: number $adr_num is already
   reserved by an open PR on another branch/worktree:

     PR #$pr_number — $pr_title
     (head: $pr_branch)

   This is the cross-worktree collision the filesystem-only pre-commit
   check cannot see (precedent: 0022→0023, 0023→0025, 0029→0030).

   Pick the next free number, then cross-check the open-PR list it
   cannot see:
       python scripts/_governance.py --next-adr-number
       gh pr list --search "ADR in:title" --state open
   and re-run Write with the renumbered filename + body heading.

   Policy: CLAUDE.md \`ADR 번호 사전 예약\` (issue #1069).
   Fail-open: if gh is unavailable this check is skipped and pre-commit
   still catches local collisions at commit time.
EOF
exit 2
