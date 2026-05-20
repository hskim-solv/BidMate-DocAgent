#!/usr/bin/env bash
# Pre-push SOFT-WARN: orphan worktrees whose branch is already merged.
#
# Sourced by `.githooks/pre-push`, also runnable standalone:
#
#     bash .githooks/_pre-push-worktree-hygiene.sh
#
# Detects worktrees whose checked-out branch is already merged into main
# but were never removed. Stale worktrees accumulate and are the root
# cause of the recurring "동시 worktree → ADR 번호 충돌" failure mode
# CLAUDE.md keeps citing. Prints the exact `git worktree remove` command
# for each orphan — never auto-removes (a worktree may hold un-pushed
# work the merge check can't see). Soft-warn only: `exit 0` always.
#
# bash 3.2 compatible (macOS default): no associative arrays — merged
# branch membership is tested with `grep -qxF` against a newline list.
#
# By design no `set -e`: a fresh clone without a local `main` should skip
# the check, never block the push.

set -u

# Merged-branch set: local branches already merged into main (origin/main
# fallback for checkouts without a local main ref). The `^[*+ ]` strip
# removes the `* ` current marker and the `+ ` worktree marker.
merged=$(git branch --merged main 2>/dev/null | sed 's/^[*+ ]*//' || true)
if [[ -z "$merged" ]]; then
  merged=$(git branch --merged origin/main 2>/dev/null | sed 's/^[*+ ]*//' || true)
fi
[[ -z "$merged" ]] && exit 0

# Current worktree root — never warn about the one we're pushing from.
self_top=$(git rev-parse --show-toplevel 2>/dev/null || true)

_is_merged() {
  printf '%s\n' "$merged" | grep -qxF "$1"
}

orphans=""
cur_path=""
cur_branch=""

_flush() {
  # detached (no branch line) → skip; main → skip (it's never an orphan);
  # current worktree → skip.
  if [[ -n "$cur_branch" && "$cur_branch" != "main" && "$cur_path" != "$self_top" ]]; then
    if _is_merged "$cur_branch"; then
      orphans="${orphans}  git worktree remove \"${cur_path}\"   # branch '${cur_branch}' merged into main"$'\n'
    fi
  fi
  cur_path=""
  cur_branch=""
}

while IFS= read -r line; do
  case "$line" in
    "worktree "*) cur_path="${line#worktree }" ;;
    "branch refs/heads/"*) cur_branch="${line#branch refs/heads/}" ;;
    "") _flush ;;
  esac
done < <(git worktree list --porcelain 2>/dev/null)
# Flush the final block (porcelain may not end with a trailing blank line).
_flush

[[ -z "$orphans" ]] && exit 0

cat >&2 <<EOF

⚠️  Orphan worktrees detected — branch already merged into main, but the
    worktree was never removed (not auto-removing):

$(printf '%s' "$orphans")
    After removing, prune stale admin files:  git worktree prune

    Why this matters: stale worktrees are the root cause of the recurring
    "동시 worktree → ADR 번호 충돌" (CLAUDE.md). Push proceeds.

EOF

exit 0
