#!/usr/bin/env bash
# Branch name + issue convention check (ADR 0007). HARD-FAILS the push.
#
# Sourced by `.githooks/pre-push`, but also runnable standalone for manual
# debugging:
#
#     bash .githooks/_pre-push-branch-check.sh
#
# Behavior: exits non-zero if the current branch does not match
# <type>/issue-<N>[-<slug>]. If `gh` is installed and authed, also verifies
# issue #N exists. Mirror of the CI check `.github/workflows/branch-and-issue-check.yml`.
#
# Skip the parent `pre-push` (including this check) with `git push --no-verify`
# only if you have a documented reason (e.g. doc-only follow-up of a measured PR).

set -euo pipefail

current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [[ -z "$current_branch" || "$current_branch" == "HEAD" ]]; then
  # Detached HEAD or unresolvable — nothing to validate.
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  # No python3 available; conservatively skip rather than block.
  exit 0
fi

# `scripts/check_branch_and_issue.py` is the single-source regex for the
# ADR 0007 branch convention (also consumed by the CI workflow).
if ! python3 scripts/check_branch_and_issue.py \
       --branch "$current_branch" --check-issue; then
  cat >&2 <<EOF

   Bypass (only with a documented reason):
       git push --no-verify

EOF
  exit 1
fi

exit 0
