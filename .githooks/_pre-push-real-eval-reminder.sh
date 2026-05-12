#!/usr/bin/env bash
# Pre-push SOFT-WARN reminders. NEVER blocks the push (explicit `exit 0`).
#
# Sourced by `.githooks/pre-push`, but also runnable standalone:
#
#     bash .githooks/_pre-push-real-eval-reminder.sh
#
# Two reminders, both soft-warn only:
#
# 1. Real-data eval delta reminder — if the push touches retrieval / verifier /
#    eval / api paths (per `scripts/_governance.py` SSoT, also consumed by the
#    Claude PreToolUse hook and the §5b CI gate), echo a reminder to attach
#    `make real-eval-delta` output to the PR body per CLAUDE.md item 5b.
#
# 2. README metrics freshness reminder — if `reports/eval_summary.json` exists
#    locally and the committed README's metrics block diverges from what
#    `update_readme_metrics.py` would render, remind the developer to refresh
#    it. `eval_summary.json` is gitignored, so this is the only feasible
#    enforcement point — CI cannot compare against it.
#
# By design no `set -e`: a missing optional dep (gh, python3 module) should
# emit a warning at worst, never block the push.

set -u

# ---------------------------------------------------------------------------
# 1. Real-data eval delta reminder.
# ---------------------------------------------------------------------------

# Resolve upstream / base ref. Prefer @{upstream}; fall back to origin/main.
if upstream=$(git rev-parse --abbrev-ref --symbolic-full-name @{upstream} 2>/dev/null); then
  base="$upstream"
else
  base="origin/main"
fi

# Files changed between the upstream and HEAD.
if ! changed=$(git diff --name-only "$base"...HEAD 2>/dev/null); then
  # No upstream / new branch — fall back to diff vs origin/main if it exists.
  if git rev-parse --verify origin/main >/dev/null 2>&1; then
    changed=$(git diff --name-only origin/main...HEAD 2>/dev/null || true)
  else
    changed=""
  fi
fi

if [[ -n "$changed" ]]; then
  # Match against the load-bearing SSoT (scripts/_governance.py).
  hit=""
  if command -v python3 >/dev/null 2>&1; then
    hit=$(printf '%s\n' "$changed" | python3 scripts/_governance.py --any-match 2>/dev/null | head -n1)
  fi

  if [[ -n "$hit" ]]; then
    cat >&2 <<EOF

⚠️  Retrieval / verifier / eval path changed in this push.
    (first match: $hit)

    Per CLAUDE.md pre-PR checklist item 5b, attach the aggregate
    real-data eval delta to the PR body before requesting review:

        make real-eval
        make real-eval-delta

    The delta script is aggregate-only (ADR 0005 commit boundary) so
    its output is safe to paste into the PR.

    Push proceeds. Skip this reminder with --no-verify only if you
    have a documented reason.

EOF
  fi
fi

# ---------------------------------------------------------------------------
# 2. README metrics freshness reminder.
# ---------------------------------------------------------------------------

if [[ -f "reports/eval_summary.json" ]] && command -v python3 >/dev/null 2>&1; then
  if ! python3 scripts/update_readme_metrics.py \
         --report reports/eval_summary.json --readme README.md --check \
         >/dev/null 2>&1; then
    cat >&2 <<EOF

⚠️  README metrics block looks stale vs reports/eval_summary.json.

    Refresh before reviewers see outdated numbers:

        make check     # confirm staleness
        python3 scripts/update_readme_metrics.py \\
            --report reports/eval_summary.json --readme README.md
        git add README.md && git commit --amend --no-edit  # or new commit

    Push proceeds. Skip this reminder with --no-verify if README
    intentionally lags eval_summary in this PR.

EOF
  fi
fi

exit 0
