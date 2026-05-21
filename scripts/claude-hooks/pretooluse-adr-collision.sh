#!/usr/bin/env bash
# Claude Code PreToolUse hook for BidMate-DocAgent — cross-worktree ADR
# number collision guard.
#
# Enforcement: block — exit 2 refuses the Write when <NNNN> collides with a
#   named open PR; exit 0 (fail-open) on every uncertainty (gh absent, network
#   fail, empty list, parse/import failure).
# Classification rationale: same family as pretooluse-adr-template (block) — it
#   refuses a specific Write rather than merely warning.
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

# Gate 2a: must live directly under docs/adr/ (mirrors where _governance
# scans). Cheap string check — the common non-ADR Write path stays
# subprocess-free.
adr_dir=$(dirname "$file_path")
[[ "$adr_dir" == "docs/adr" || "$adr_dir" == */docs/adr ]] || exit 0

# Gate 3: file already exists → edit/rewrite of an existing ADR, grandfathered.
# Checked before the (heavier) Gate 2b so edits never pay the import.
[[ -e "$file_path" ]] && exit 0

# Gate 2b: basename must match the ADR-filename SSoT — scripts/_governance.py
# ADR_FILENAME_RE. Reuse over a local copy (CLAUDE.md 새로 만들기보다 재사용):
# a narrower lowercase-only regex silently skipped mixed-case realN ADRs
# (e.g. 0048-realN-metrics-extension.md, issue #818). _template.md is excluded
# by the regex's required 4-digit prefix. Import failure → exit 0 (fail-open;
# pre-commit is the backstop). Only runs on the rare new-ADR Write path.
adr_basename=$(basename "$file_path")
BIDMATE_REPO_ROOT="$REPO_ROOT" ADR_BASENAME="$adr_basename" python3 -c '
import os, sys
sys.path.insert(0, os.path.join(os.environ.get("BIDMATE_REPO_ROOT", ""), "scripts"))
try:
    from _governance import ADR_FILENAME_RE
except Exception:
    sys.exit(1)  # cannot reach the SSoT → fail-open (pre-commit backstop)
sys.exit(0 if ADR_FILENAME_RE.match(os.environ["ADR_BASENAME"]) else 1)
' || exit 0

# 4-digit number prefix (Gate 2b's regex guarantees a leading NNNN-).
adr_num=${adr_basename:0:4}

# Gate 4 (fail-open): gh absent → soft skip. pre-commit is the backstop.
command -v gh >/dev/null 2>&1 || {
  printf 'ℹ️  gh CLI absent — skipping cross-worktree ADR collision check for %s.\n' \
    "$(basename "$file_path")" >&2
  exit 0
}

# List open PRs and re-filter locally on BOTH title and headRefName. We do
# NOT prefilter with `--search "ADR in:title"`: that drops PRs whose *title*
# lacks "ADR" even when the head BRANCH reserves the number (e.g.
# docs/issue-200-adr-0060-foo) — which is exactly the cross-worktree
# branch-only reservation this hook exists to catch (issue #1155). `--limit`
# raises gh's default 30-PR cap so a reservation past the 30th open PR is
# still seen. `timeout` guards a hung network call when available (GNU
# coreutils); stock macOS lacks it, so we fall back to a bare call rather
# than silently fail-open.
if command -v timeout >/dev/null 2>&1; then
  prs=$(timeout 8 gh pr list --state open --limit 200 \
          --json number,title,headRefName 2>/dev/null || true)
else
  prs=$(gh pr list --state open --limit 200 \
          --json number,title,headRefName 2>/dev/null || true)
fi

# Gate 5 (fail-open): empty / "[]" / network error / no token → pass.
[[ -z "$prs" || "$prs" == "[]" ]] && exit 0

# Parse each PR's reserved ADR number from title + headRefName, zero-pad
# insensitive. Body is intentionally ignored: bodies cite *other* ADRs
# constantly ("supersedes 0012") → false positives. Re-filter by exact
# integer so a loose substring match cannot over-block.
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

# v2-5field telemetry (ADR 0060) via the canonical --emit-fire path: routes
# through the KNOWN_HOOKS / KNOWN_OUTCOMES typo guard and lands the basename
# in the <path> slot + open_pr in <extra> — not the wrong-field raw printf.
python3 "$REPO_ROOT/scripts/_governance.py" --emit-fire \
  --outcome blocked --hook adr-collision --category cross-worktree-collision \
  --path "$adr_basename" --extra "open_pr=$pr_number" \
  --fire-log "$REPO_ROOT/.claude/.hook-fires.log" 2>/dev/null || true

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
       gh pr list --search "ADR" --state open
   and re-run Write with the renumbered filename + body heading.

   Policy: CLAUDE.md \`ADR 번호 사전 예약\` (issue #1069).
   Fail-open: if gh is unavailable this check is skipped and pre-commit
   still catches local collisions at commit time.
EOF
exit 2
