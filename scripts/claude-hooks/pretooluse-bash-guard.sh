#!/usr/bin/env bash
# Claude Code PreToolUse hook for BidMate-DocAgent — Bash matcher.
#
# Enforcement: block (exit 2 refuses gh pr merge/create with stacked-dependency violation).
# Classification rationale: refuses tool calls. See scripts/claude-hooks/README.md.
#
# Registered in `.claude/settings.json` with matcher `Bash`. Fires before
# Claude runs any Bash command. Three responsibilities:
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
#   (3) Refuses `git push origin --delete <branch>` when the branch has
#       open stacked dependents — the worktree-safe post-merge flow
#       (issue #1283) deletes the remote head branch this way instead of
#       `gh pr merge --delete-branch`, and the same auto-close failure
#       mode applies. Extends (1)'s protection to the push form.
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
# Parsing extracted to scripts/claude-hooks/_bash_guard_parse.py (issue #1045)
# so tests/test_bash_guard_adversarial.py can pin the false-negative surface.
#
# Finding F1: `--detect-gh` always exits 0 on a successful parse, so a
# *non-zero* exit means the parser invocation itself failed (missing
# python3, ImportError, syntax error, or a transient sandbox hiccup). The
# old code piped through `tr` and only tested for empty output, so a parser
# failure was indistinguishable from "not a gh command" — silently
# fail-open, letting a dangerous `gh pr merge --delete-branch` through on
# any parser breakage. Capture stdout and exit status separately (no pipe —
# a pipe masks python's exit code behind `tr`'s).
gh_subcommand=$(python3 "$REPO_ROOT/scripts/claude-hooks/_bash_guard_parse.py" \
                  --detect-gh "$cmd" 2>/dev/null)
parse_rc=$?
gh_subcommand=$(printf '%s' "$gh_subcommand" | tr -d '\n')

if [[ "$parse_rc" -ne 0 ]]; then
  # Parser failed. *Anchored* fail-closed: refuse only when the command
  # itself STARTS with `gh pr merge|create` (optionally after one leading
  # separator/subshell-open), i.e. a direct, high-confidence invocation we
  # would normally guard. This deliberately narrow scope is the compromise
  # with the fail-open philosophy at the top of this file: a transient
  # parser failure was observed to over-block benign commands that merely
  # *contained* the literal `gh pr create` inside quotes (e.g. an echo or a
  # nested invocation). Anchoring avoids that false block; the residual cost
  # is that a directly-typed `gh pr merge|create` is refused during a
  # transient failure and must be re-run (the hiccup clears). A chained
  # `foo && gh pr merge` falls open here — acceptable per the philosophy
  # (one slipped merge is recoverable; blocking arbitrary commands is not).
  if grep -qiE '^[[:space:]]*[(;&|]*[[:space:]]*gh[[:space:]]+pr[[:space:]]+(merge|create)([[:space:]]|$)' <<<"$cmd"; then
    python3 "$REPO_ROOT/scripts/_governance.py" --emit-fire \
      --outcome blocked --hook bash-guard --category parser-failure \
      --path "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)" \
      --fire-log "$REPO_ROOT/.claude/.hook-fires.log" 2>/dev/null || true
    cat >&2 <<'EOF'
⛔ Refusing gh pr command: bash-guard parser failed to run.

    scripts/claude-hooks/_bash_guard_parse.py exited non-zero (missing
    python3? import/syntax error? transient sandbox hiccup?), so the
    stacked-PR safety check could not run. Refusing out of caution rather
    than silently allowing a potentially stack-collapsing `gh pr
    merge|create`.

    If this was a transient failure, just re-run the command. If it
    persists, fix the parser. To proceed manually, first verify:
        gh pr list --base <branch> --state open
EOF
    exit 2
  fi
  # Parser failed but the command does not directly start with a guarded gh
  # pr invocation — fall open (blocking arbitrary commands violates the
  # fail-open philosophy, and a transient failure must not wedge unrelated
  # work).
  exit 0
fi

# --- Branch (3): `git push origin --delete <branch>` stacked guard (issue #1283) ---
# The worktree-safe post-merge flow deletes the remote head branch via
# `git push origin --delete` rather than `gh pr merge --delete-branch`
# (whose local checkout-to-default step aborts when `main` is checked out in
# another worktree, leaving the remote branch behind). The remote deletion
# still auto-closes any open PR that bases on the branch, so the same
# stacked-dependent protection Branch (1) applies to --delete-branch must
# cover this form too (precedent PR #423 → #431, #470). Runs independently of
# the gh subcommand classification above. Parser failure here falls open
# (no anchored fail-closed) — consistent with the fail-open philosophy: a
# slipped branch delete is recoverable, blocking arbitrary `git push` is not.
push_delete_targets=$(python3 "$REPO_ROOT/scripts/claude-hooks/_bash_guard_parse.py" \
                        --detect-push-delete "$cmd" 2>/dev/null)
pd_rc=$?
if [[ "$pd_rc" -eq 0 && -n "${push_delete_targets//[$'\n' ]/}" ]]; then
  while IFS= read -r del_branch; do
    [[ -z "$del_branch" ]] && continue
    pd_deps=$(gh pr list --base "$del_branch" --state open \
                --json number,title,headRefName 2>/dev/null || true)
    if [[ -n "$pd_deps" && "$pd_deps" != "[]" ]]; then
      python3 "$REPO_ROOT/scripts/_governance.py" --emit-fire \
        --outcome blocked --hook bash-guard --category git-push-delete-stacked \
        --path "$del_branch" \
        --fire-log "$REPO_ROOT/.claude/.hook-fires.log" 2>/dev/null || true
      cat >&2 <<EOF
⛔ Refusing \`git push origin --delete $del_branch\`: branch has open stacked dependents.

    Open PR(s) base on \`$del_branch\`. Deleting the remote branch now
    auto-closes them — the same stack-collapse failure mode that
    \`gh pr merge --delete-branch\` is guarded against (PR #423 → #431, #470):

$pd_deps

    Recovery:
      (a) Rebase each dependent onto main first, then re-run the delete:
              gh pr edit <M> --base main
      (b) Keep the base branch — skip the remote delete; remove it after
          the dependents land.

    Policy: stacked-PR discipline (CLAUDE.md ## Prohibited, MEMORY feedback_pr_discipline).
EOF
      exit 2
    fi
  done <<< "$push_delete_targets"
fi

if [[ -z "$gh_subcommand" ]]; then
  exit 0
fi

# --- Branch (2): gh pr create stacked guard (#826 Hook B / #865) ---
# (The §5b pre-create soft-warn that previously lived here was removed when the
# §5b real-data-delta gate was deprecated — ADR 0084.)
if [[ "$gh_subcommand" == "create" ]]; then
  # Bypass: explicit --base is intentional. Catches both `--base X` and
  # `--base=X` forms. `--base main` is the documented escape for
  # "I really do want to flatten this onto main."
  # Parsing extracted (issue #1045) — see _bash_guard_parse.py.
  if python3 "$REPO_ROOT/scripts/claude-hooks/_bash_guard_parse.py" \
       --has-base "$cmd" >/dev/null 2>&1; then
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

  # v2-5field telemetry (ADR 0060) — hook field added to canonical pattern.
  python3 "$REPO_ROOT/scripts/_governance.py" --emit-fire \
    --outcome blocked --hook bash-guard --category gh-pr-create-stacked \
    --path "$current_branch" --extra "on=$stacked_on" \
    --fire-log "$REPO_ROOT/.claude/.hook-fires.log" 2>/dev/null || true

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

# v2-5field telemetry (ADR 0060) — hook field added to canonical pattern.
python3 "$REPO_ROOT/scripts/_governance.py" --emit-fire \
  --outcome blocked --hook bash-guard --category gh-merge-delete-branch \
  --path "$head_branch" \
  --fire-log "$REPO_ROOT/.claude/.hook-fires.log" 2>/dev/null || true

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
