#!/usr/bin/env bash
# Pre-push SOFT-WARN reminders. NEVER blocks the push (explicit `exit 0`).
#
# Sourced by `.githooks/pre-push`, but also runnable standalone:
#
#     bash .githooks/_pre-push-real-eval-reminder.sh
#
# Two reminders, both soft-warn only:
#
# 1. README metrics freshness reminder — if `reports/eval_summary.json` exists
#    locally and the committed README's metrics block diverges from what
#    `update_readme_metrics.py` would render, remind the developer to refresh
#    it. `eval_summary.json` is gitignored, so this is the only feasible
#    enforcement point — CI cannot compare against it.
#
# 2. naive_baseline golden freshness reminder — see block 2 below.
#
# (The §5b real-data-delta pre-push reminder was deprecated in ADR 0084. The
# `make real-eval-delta` measurement tool is retained, but it is no longer
# nagged on push.)
#
# By design no `set -e`: a missing optional dep (gh, python3 module) should
# emit a warning at worst, never block the push.

set -u

# ---------------------------------------------------------------------------
# Resolve the diff base. `$changed` is consumed by the naive_baseline golden
# reminder below.
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

# ---------------------------------------------------------------------------
# 1. README metrics freshness reminder.
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

# ---------------------------------------------------------------------------
# 2. naive_baseline golden freshness reminder.
# ---------------------------------------------------------------------------
#
# tests/data/naive_baseline_top_k.json drifts when the eval/fixtures/smoke_rfp/raw/ corpus changes
# (PR #648 HWP fixtures, PR #914 H/I/J/K corpus). Content drift is hard-gated
# by tests/test_naive_baseline_ranking_invariance.py, but that signal only
# fires at test time; this surfaces it earlier — and ONLY when the corpus
# changed without a co-committed golden update AND a rebuild confirms real
# drift (so a no-op corpus edit never nags). Uses `$changed` resolved above.

if [[ -n "$changed" ]] && command -v python3 >/dev/null 2>&1; then
  raw_changed=$(printf '%s\n' "$changed" | grep -E '^eval/fixtures/smoke_rfp/raw/.+\.json$' || true)
  golden_changed=$(printf '%s\n' "$changed" | grep -Fx 'tests/data/naive_baseline_top_k.json' || true)
  if [[ -n "$raw_changed" && -z "$golden_changed" ]]; then
    if ! python3 scripts/regen_naive_baseline_golden.py --check >/dev/null 2>&1; then
      cat >&2 <<EOF

⚠️  eval/fixtures/smoke_rfp/raw/ corpus changed but the naive_baseline golden was not updated,
    and a rebuild shows the ranking drifted.

    Refresh the committed snapshot before reviewers see a red invariance test:

        make regen-golden
        git add tests/data/naive_baseline_top_k.json

    ADR 0001: this only refreshes the snapshot — the naive_baseline pipeline
    is untouched. Push proceeds; skip with --no-verify if the drift is
    intentional and handled in this PR.

EOF
    fi
  fi
fi

exit 0
