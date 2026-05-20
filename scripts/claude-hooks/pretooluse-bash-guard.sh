#!/usr/bin/env bash
# Claude Code PreToolUse hook for BidMate-DocAgent — Bash matcher.
#
# Enforcement: block (exit 2 refuses gh pr merge/create with stacked-dependency violation).
# Classification rationale: refuses tool calls. See scripts/claude-hooks/README.md.
#
# Registered in `.claude/settings.json` with matcher `Bash`. Fires before
# Claude runs any Bash command. Two responsibilities:
#
#   (1) Refuses `gh pr merge --delete-branch` when the target branch has
#       open stacked dependents (i.e. open PRs whose `base` is this
#       branch). Auto-enforces the policy stated in CLAUDE.md
#       `## Prohibited` after the PR #423 → #431 and PR #470 stacked-PR
#       auto-close incidents.
#
#   (2) Refuses `gh pr create` (without `--base <branch>`) when the
#       current branch appears to be stacked on another open PR's
#       branch — i.e. when an `origin/<other-branch>` ref exists whose
#       merge-base with HEAD is *ahead of* `origin/main`. Issue #826
#       Hook B (split into #865): a 5-PR stack audit found multiple
#       cases where a stacked PR was opened against `main` instead of
#       its upstream branch, collapsing the stack base.
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

# Fast path: empty command.
if [[ -z "$cmd" ]]; then
  exit 0
fi

# Classify the gh subcommand once: "merge" | "create" | "".
# We split on shell separators so `foo && gh pr create …` is still caught,
# but anything inside quotes or comments is preserved by shlex.
gh_subcommand=$(printf '%s' "$cmd" | python3 -c '
import sys, shlex, re
for part in re.split(r"[;&|\n]", sys.stdin.read()):
    part = part.strip().lstrip("(")
    try:
        tokens = shlex.split(part)
    except ValueError:
        continue
    if len(tokens) >= 3 and tokens[0] == "gh" and tokens[1] == "pr":
        if tokens[2] in ("merge", "create"):
            print(tokens[2]); break
' 2>/dev/null)

if [[ -z "$gh_subcommand" ]]; then
  exit 0
fi

# --- Branch (2): gh pr create stacked guard (#826 Hook B / #865) ---
if [[ "$gh_subcommand" == "create" ]]; then
  # Bypass: explicit --base is intentional. Catches both `--base X` and
  # `--base=X` forms. `--base main` is the documented escape for
  # "I really do want to flatten this onto main."
  has_base=$(printf '%s' "$cmd" | python3 -c '
import sys, shlex, re
for part in re.split(r"[;&|\n]", sys.stdin.read()):
    part = part.strip().lstrip("(")
    try:
        tokens = shlex.split(part)
    except ValueError:
        continue
    if len(tokens) >= 3 and tokens[0] == "gh" and tokens[1] == "pr" and tokens[2] == "create":
        if any(t == "--base" or t.startswith("--base=") for t in tokens[3:]):
            print("yes"); break
' 2>/dev/null)
  if [[ "$has_base" == "yes" ]]; then
    exit 0
  fi

  mb_main=$(git merge-base HEAD origin/main 2>/dev/null || true)
  if [[ -z "$mb_main" ]]; then
    # No origin/main ref locally (fresh clone, weird worktree). Fail open
    # — the live `gh pr create` will likely fail too with a clearer error.
    exit 0
  fi

  current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
  stacked_on=""
  # Walk every local origin/* ref. We use refs that the user has already
  # fetched — this is what `gh pr create` would see anyway. Each refers
  # to an open or recently-closed PR branch.
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    case "$ref" in
      origin/HEAD|origin/main|origin/master) continue ;;
    esac
    if [[ -n "$current_branch" && "$ref" == "origin/$current_branch" ]]; then
      continue
    fi
    mb_other=$(git merge-base HEAD "$ref" 2>/dev/null || true)
    if [[ -z "$mb_other" || "$mb_other" == "$mb_main" ]]; then
      continue
    fi
    # mb_other ≠ mb_main, and mb_main is an ancestor of mb_other → mb_other
    # sits on the path from main toward HEAD, i.e. our branch forks off
    # `$ref` at a point that is ahead of `origin/main`. That's a stack.
    if git merge-base --is-ancestor "$mb_main" "$mb_other" 2>/dev/null; then
      stacked_on="${ref#origin/}"
      break
    fi
  done < <(git for-each-ref refs/remotes/origin --format='%(refname:short)' 2>/dev/null)

  if [[ -z "$stacked_on" ]]; then
    # Branch forks off main (or off a branch we don't have a remote ref
    # for, which gh pr create can't target anyway). Allow.
    exit 0
  fi

  printf '%s|blocked|gh-pr-create-stacked|%s|on=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$current_branch" "$stacked_on" \
    >> "$REPO_ROOT/.claude/.hook-fires.log" 2>/dev/null || true

  cat >&2 <<EOF
⛔ Refusing \`gh pr create\` without \`--base\`: current branch is stacked.

    Branch \`$current_branch\` was forked from \`$stacked_on\` (an open
    PR's head branch), not directly from \`main\`. Running \`gh pr create\`
    without \`--base\` opens this PR against \`main\`, which silently
    collapses the stack base and (on merge) auto-closes \`$stacked_on\`
    once \`$current_branch\` lands.

    Two recovery options:
      (a) Add \`--base $stacked_on\` so the PR targets its real upstream:
              gh pr create --base $stacked_on ...
      (b) If you actually want this PR off main (intentional flatten),
          pass \`--base main\` explicitly to silence this guard:
              gh pr create --base main ...

    Policy: stacked-PR discipline (project MEMORY.md feedback_pr_discipline).
    Precedent: PR #423 → #431, PR #470 — auto-close of stacked dependents
               when the base PR merged with --delete-branch.
EOF
  exit 2
fi

# --- Branch (1): gh pr merge --delete-branch stacked-dependent guard ---
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
