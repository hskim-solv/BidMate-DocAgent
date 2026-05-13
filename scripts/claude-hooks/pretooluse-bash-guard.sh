#!/usr/bin/env bash
# Claude Code PreToolUse hook for BidMate-DocAgent — Bash matcher.
#
# Registered in `.claude/settings.json` with matcher `Bash`. Fires before
# Claude runs any Bash command. Refuses `gh pr merge --delete-branch`
# when the target branch has open stacked dependents (i.e. open PRs
# whose `base` is this branch). Auto-enforces the policy stated in
# CLAUDE.md `## Prohibited` after the PR #423 → #431 and PR #470
# stacked-PR auto-close incidents.
#
# Behavior:
#   - exit 0  : safe / not applicable / fail-open
#   - exit 2  : refuse the command, print rationale to stderr
#
# Fail-open philosophy: a buggy hook silently letting one bad merge
# through is recoverable (re-open the dependent PR — see #423→#431).
# A buggy hook silently blocking every Bash command is not.
#
# Hook input (stdin, JSON):
#   { "tool_name": "Bash",
#     "tool_input": { "command": "..." }, ... }

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

input=$(cat)

cmd=$(printf '%s' "$input" | python3 -c 'import json,sys
try:
    d = json.loads(sys.stdin.read())
    print(d.get("tool_input", {}).get("command", ""))
except Exception:
    pass' 2>/dev/null)

# Fast path: not a destructive gh merge.
if [[ -z "$cmd" ]]; then
  exit 0
fi
is_merge_cmd=$(printf '%s' "$cmd" | python3 -c '
import sys, shlex, re
for part in re.split(r"[;&|\n]", sys.stdin.read()):
    part = part.strip().lstrip("(")
    try:
        tokens = shlex.split(part)
    except ValueError:
        continue
    if len(tokens) >= 3 and tokens[0] == "gh" and tokens[1] == "pr" and tokens[2] == "merge":
        print("yes"); break
' 2>/dev/null)
if [[ "$is_merge_cmd" != "yes" ]]; then
  exit 0
fi
if ! grep -qE -- '--delete-branch' <<<"$cmd"; then
  exit 0
fi

# Resolve the head branch whose PR is being merged.
#   `gh pr merge <N>` → look up PR N's head branch
#   `gh pr merge`     → current branch is the implicit target
head_branch=""
pr_number=$(grep -oE 'gh[[:space:]]+pr[[:space:]]+merge[[:space:]]+([0-9]+)' <<<"$cmd" \
            | grep -oE '[0-9]+$' || true)

if [[ -n "$pr_number" ]]; then
  head_branch=$(gh pr view "$pr_number" --json headRefName --jq .headRefName 2>/dev/null || true)
else
  head_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
fi

if [[ -z "$head_branch" ]]; then
  # Could not resolve — fail-open with a soft warning.
  cat >&2 <<EOF
⚠️  Bash guard: could not resolve head branch for \`gh pr merge --delete-branch\`.
    Skipping stacked-dependent audit. Verify manually:
        gh pr list --base <branch> --state open
EOF
  exit 0
fi

# Query open PRs targeting head_branch as base.
dependents=$(gh pr list --base "$head_branch" --state open \
               --json number,title,headRefName 2>/dev/null || true)

if [[ -z "$dependents" || "$dependents" == "[]" ]]; then
  # No open dependents — `--delete-branch` is safe.
  exit 0
fi

# Render the dependent list and refuse.
listing=$(printf '%s' "$dependents" \
            | python3 -c 'import json,sys
try:
    for p in json.loads(sys.stdin.read()):
        print(f"      PR #{p[\"number\"]} — {p[\"title\"]} (head: {p[\"headRefName\"]})")
except Exception:
    pass' 2>/dev/null)

printf '%s|blocked|gh-merge-delete-branch|%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$head_branch" \
  >> "$REPO_ROOT/.claude/.hook-fires.log" 2>/dev/null || true

cat >&2 <<EOF
⛔ Refusing \`gh pr merge --delete-branch\`: stacked dependents exist on \`$head_branch\`.

$listing

    Two recovery options:
      (a) Drop \`--delete-branch\` from the merge command (dependents survive,
          the base branch lingers — fine for a short-lived stack).
      (b) Rebase each dependent onto main first, then re-run:
              gh pr edit <M> --base main
              gh pr edit <K> --base main

    Policy: CLAUDE.md \`## Prohibited\` — verify
            \`gh pr list --base $head_branch --state open\` is empty
            before \`--delete-branch\`.
    Precedent: PR #423 → #431 recovery after the stacked dependent was
               auto-closed by this exact pattern.
EOF
exit 2
