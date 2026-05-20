#!/usr/bin/env bash
# Pre-push SOFT-WARN: behavior-code change pushed without a test change.
#
# Sourced by `.githooks/pre-push`, also runnable standalone:
#
#     bash .githooks/_pre-push-test-coverage.sh
#
# CLAUDE.md rule "동작 변경 ↔ 테스트 변경. 테스트 없는 동작 변경은 실수."
# (a behavior change must travel with a test change) previously had no
# enforcing hook. PR #69 is the cost precedent — a synthetic-only CI
# delta missed an intended-abstention regression because no test pinned
# the behavior.
#
# Warns (never blocks) when the pushed diff touches a load-bearing
# behavior path (scripts/_governance.py SSoT — the same list the §5b CI
# gate and the Claude awareness hook read) but changes zero files under
# tests/. Soft-warn only: `exit 0` always.
#
# By design no `set -e`: a missing python3 should skip the check, never
# block the push.

set -u

# Resolve upstream / base ref. Prefer @{upstream}; fall back to origin/main.
# (Mirrors _pre-push-real-eval-reminder.sh so both reminders agree on base.)
if upstream=$(git rev-parse --abbrev-ref --symbolic-full-name @{upstream} 2>/dev/null); then
  base="$upstream"
else
  base="origin/main"
fi

if ! changed=$(git diff --name-only "$base"...HEAD 2>/dev/null); then
  # No upstream / new branch — fall back to diff vs origin/main if it exists.
  if git rev-parse --verify origin/main >/dev/null 2>&1; then
    changed=$(git diff --name-only origin/main...HEAD 2>/dev/null || true)
  else
    changed=""
  fi
fi

[[ -z "$changed" ]] && exit 0

# No python3 → conservatively skip (the load-bearing SSoT is a python module).
command -v python3 >/dev/null 2>&1 || exit 0

# Behavior-code change = any changed path matching the load-bearing SSoT.
behavior_hit=$(printf '%s\n' "$changed" | python3 scripts/_governance.py --any-match 2>/dev/null | head -n1)
[[ -z "$behavior_hit" ]] && exit 0

# Accompanying test change? (Any path under tests/.)
test_changes=$(printf '%s\n' "$changed" | grep -c '^tests/' || true)
[[ "$test_changes" -gt 0 ]] && exit 0

cat >&2 <<EOF

⚠️  Behavior-code change pushed without an accompanying test change.
    (first load-bearing match: $behavior_hit)

    CLAUDE.md: "동작 변경 ↔ 테스트 변경. 테스트 없는 동작 변경은 실수."
    Add or update a regression test under tests/ — convention is
    tests/test_*_regression.py (e.g. tests/test_retrieval_loop_regression.py).

    Push proceeds. Skip this reminder with --no-verify only if you have
    a documented reason (e.g. a pure refactor with no behavior change).

EOF

exit 0
