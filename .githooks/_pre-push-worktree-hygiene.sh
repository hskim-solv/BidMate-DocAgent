#!/usr/bin/env bash
# Pre-push SOFT-WARN: orphan worktrees whose branch is already merged.
#
# Sourced by `.githooks/pre-push`, also runnable standalone:
#
#     bash .githooks/_pre-push-worktree-hygiene.sh
#     bash .githooks/_pre-push-worktree-hygiene.sh --clean --dry-run
#     bash .githooks/_pre-push-worktree-hygiene.sh --clean --prune
#
# Detects worktrees whose checked-out branch is already merged into main
# but were never removed. Stale worktrees accumulate and are the root
# cause of the recurring "동시 worktree → ADR 번호 충돌" failure mode
# CLAUDE.md keeps citing. Prints the exact `git worktree remove` command
# for each orphan. Default pre-push mode never auto-removes. Standalone
# `--clean` mode removes only clean orphan worktrees; dirty/untracked
# worktrees are skipped. Soft-warn only: `exit 0` always.
#
# "Merged" is decided per branch by three OFFLINE signals (no network — every
# push stays fast, like the other pre-push sub-hooks) plus one OPT-IN online
# signal:
#
#   (a) ancestor      branch tip is an ancestor of main — classic
#                     fast-forward / merge-commit merge.
#   (b) patch-equiv   `git cherry main <branch>` shows no '+' line: every
#                     commit since the fork point is already applied on main
#                     by patch-id. THIS catches the squash-merge
#                     (`gh pr merge --squash`, this repo's documented default):
#                     a squash lands a brand-new SHA, so the original tip is
#                     NOT an ancestor and signal (a) — the old
#                     `git branch --merged` test — silently missed it.
#   (c) gone upstream the branch's remote-tracking ref is '[gone]', i.e. the
#                     remote branch was deleted (`gh pr merge --delete-branch`).
#                     Targets the documented incident where --delete-branch
#                     fails locally ("'main' already used by worktree") and
#                     leaves the stale worktree behind.
#   (d) gh PR MERGED  OPT-IN via BIDMATE_WORKTREE_HYGIENE_GH=1 (requires gh).
#                     Authoritative for a multi-commit branch squash-merged
#                     while its upstream is still present — the only case
#                     (a)-(c) miss. Off by default so pushes stay offline.
#
# bash 3.2 compatible (macOS default): no associative arrays.
#
# By design no `set -e`: a fresh clone without a local `main` should skip
# the check, never block the push.

set -u

clean_mode=0
dry_run=0
prune_after=0

for arg in "$@"; do
  case "$arg" in
    --clean) clean_mode=1 ;;
    --dry-run) clean_mode=1; dry_run=1 ;;
    --prune) prune_after=1 ;;
    -h|--help)
      cat <<'EOF'
Usage:
  bash .githooks/_pre-push-worktree-hygiene.sh
  bash .githooks/_pre-push-worktree-hygiene.sh --clean --dry-run
  bash .githooks/_pre-push-worktree-hygiene.sh --clean --prune

Default mode prints orphan worktree warnings only. --clean removes only clean
orphan worktrees; dirty/untracked worktrees are skipped. No branches or remote
refs are deleted.
EOF
      exit 0
      ;;
    *)
      printf 'worktree hygiene: unknown option: %s\n' "$arg" >&2
      exit 0
      ;;
  esac
done

# Base ref, resolved once: prefer `origin/main` so a stale local `main` does not
# hide recently merged PRs. Fall back to local `main` for isolated test repos or
# checkouts without a remote-tracking main. No base → fresh clone → skip.
if git rev-parse --verify -q refs/remotes/origin/main >/dev/null 2>&1; then
  base_ref="origin/main"
elif git rev-parse --verify -q refs/heads/main >/dev/null 2>&1; then
  base_ref="main"
else
  exit 0
fi

# Current worktree root — never warn about the one we're pushing from.
self_top=$(git rev-parse --show-toplevel 2>/dev/null || true)

# Opt-in online signal: only when explicitly enabled AND gh is installed.
gh_enabled=""
if [[ -n "${BIDMATE_WORKTREE_HYGIENE_GH:-}" ]] && command -v gh >/dev/null 2>&1; then
  gh_enabled="1"
fi

# Cap on how far a branch may diverge from base before we SKIP the (b)
# patch-equivalence walk. `git cherry` computes a patch-id for every commit
# since the fork point, so its time AND memory scale with commits-ahead. A
# branch hundreds of commits ahead of base always has unmerged '+' commits and
# so can never be flagged by (b) anyway — the walk is pure waste. With many
# stale worktrees that waste spikes memory enough to get the hook OOM-killed
# mid-push (SIGKILL → broken pipe → push aborts with exit 141), forcing
# `git push --no-verify` and defeating the hook (issue #1270). A cheap
# graph-only pre-check (rev-list --count) gates the walk to small,
# realistically-mergeable branches. Overridable for debugging.
cherry_max="${BIDMATE_WORKTREE_HYGIENE_CHERRY_MAX:-100}"

# Aggregate cap on how many (b) patch-id walks run in a SINGLE push, across all
# worktrees. `cherry_max` bounds the cost of ONE walk, but with many stale
# worktrees the per-walk cost still SUMS: N small walks, layered on git's own
# pack memory during the push, was enough to get the hook OOM-killed (SIGKILL →
# broken pipe → push aborts 141) at 37 accumulated worktrees (issue #1251) even
# though every individual walk was within cherry_max. Once the budget is spent
# the remaining branches fall back to the cheap signals (a)/(c)/(d) only — they
# still get flagged by ancestor / gone-upstream / opt-in gh, just not by the
# patch-id walk. Soft-warn semantics are unchanged. Overridable for debugging.
cherry_budget="${BIDMATE_WORKTREE_HYGIENE_CHERRY_BUDGET:-20}"
cherry_walks=0

_is_merged() {
  # Returns 0 (merged/stale) if any signal fires; 1 otherwise. Cheap local
  # signals first; the opt-in network call only for branches still unflagged.
  local branch="$1"

  # (a) ancestor of base — fast-forward / merge-commit merge.
  git merge-base --is-ancestor "$branch" "$base_ref" 2>/dev/null && return 0

  # (b) patch-equivalent — no '+' line ⇒ every commit since the fork point is
  # already applied on base by patch-id (catches single-commit squash-merge).
  # Cheap graph-only pre-check first: `git cherry` is O(commits-ahead) in time
  # AND memory, so skip the patch-id walk for branches diverged past
  # $cherry_max (they always carry unmerged '+' commits and can never be
  # flagged here anyway — see #1270). Guarded on cherry succeeding so a bad
  # ref never flags a branch.
  local ahead
  ahead=$(git rev-list --count "$base_ref..$branch" 2>/dev/null || echo 0)
  if [[ "$ahead" =~ ^[0-9]+$ && "$ahead" -le "$cherry_max" && "$cherry_walks" -lt "$cherry_budget" ]]; then
    cherry_walks=$((cherry_walks + 1))
    local cherry
    if cherry=$(git cherry "$base_ref" "$branch" 2>/dev/null); then
      printf '%s\n' "$cherry" | grep -q '^+' || return 0
    fi
  fi

  # (c) remote-tracking branch deleted on the remote (--delete-branch merge).
  local track
  track=$(git for-each-ref --format='%(upstream:track)' "refs/heads/$branch" 2>/dev/null || true)
  [[ "$track" == *"[gone]"* ]] && return 0

  # (d) opt-in authoritative: the branch's PR is merged per gh.
  if [[ -n "$gh_enabled" ]]; then
    [[ "$(gh pr view "$branch" --json state -q .state 2>/dev/null || true)" == "MERGED" ]] && return 0
  fi

  return 1
}

orphans=""
clean_orphans=""
dirty_orphans=""
cur_path=""
cur_branch=""

_is_clean_worktree() {
  local path="$1"
  [[ -d "$path" ]] || return 1
  git -C "$path" diff --quiet --ignore-submodules -- 2>/dev/null || return 1
  git -C "$path" diff --cached --quiet --ignore-submodules -- 2>/dev/null || return 1
  local untracked
  untracked=$(git -C "$path" ls-files --others --exclude-standard 2>/dev/null || true)
  [[ -z "$untracked" ]]
}

_prune_if_requested() {
  if [[ "$prune_after" == "1" ]]; then
    if [[ "$dry_run" == "1" ]]; then
      printf 'worktree cleanup: would run git worktree prune\n' >&2
    else
      git worktree prune >/dev/null 2>&1 || true
      printf 'worktree cleanup: pruned stale worktree admin files.\n' >&2
    fi
  fi
}

_flush() {
  # detached (no branch line) → skip; main → skip (it's never an orphan);
  # current worktree → skip.
  if [[ -n "$cur_branch" && "$cur_branch" != "main" && "$cur_path" != "$self_top" ]]; then
    if _is_merged "$cur_branch"; then
      orphans="${orphans}  git worktree remove \"${cur_path}\"   # branch '${cur_branch}' merged into main"$'\n'
      if [[ "$clean_mode" == "1" ]]; then
        if _is_clean_worktree "$cur_path"; then
          clean_orphans="${clean_orphans}${cur_path}"$'\t'"${cur_branch}"$'\n'
        else
          dirty_orphans="${dirty_orphans}  skip dirty/untracked \"${cur_path}\"   # branch '${cur_branch}'"$'\n'
        fi
      fi
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

if [[ -z "$orphans" ]]; then
  if [[ "$clean_mode" == "1" ]]; then
    _prune_if_requested
  fi
  exit 0
fi

if [[ "$clean_mode" == "1" ]]; then
  cat >&2 <<EOF

⚠️  Orphan worktrees detected — branch already merged into main:

$(printf '%s' "$orphans")
EOF
else
  cat >&2 <<EOF

⚠️  Orphan worktrees detected — branch already merged into main, but the
    worktree was never removed (not auto-removing):

$(printf '%s' "$orphans")
    After removing, prune stale admin files:  git worktree prune

    Why this matters: stale worktrees are the root cause of the recurring
    "동시 worktree → ADR 번호 충돌" (CLAUDE.md). Push proceeds.

EOF
fi

if [[ "$clean_mode" != "1" ]]; then
  exit 0
fi

if [[ -n "$dirty_orphans" ]]; then
  cat >&2 <<EOF
Skipped worktrees with local changes:

$(printf '%s' "$dirty_orphans")
EOF
fi

if [[ -z "$clean_orphans" ]]; then
  printf 'worktree cleanup: no clean orphan worktrees to remove.\n' >&2
  _prune_if_requested
  exit 0
fi

while IFS=$'\t' read -r orphan_path orphan_branch; do
  [[ -n "$orphan_path" ]] || continue
  if [[ "$dry_run" == "1" ]]; then
    printf 'worktree cleanup: would remove "%s"   # branch '\''%s'\''\n' \
      "$orphan_path" "$orphan_branch" >&2
  else
    if git worktree remove "$orphan_path" >/dev/null 2>&1; then
      printf 'worktree cleanup: removed "%s"   # branch '\''%s'\''\n' \
        "$orphan_path" "$orphan_branch" >&2
    else
      printf 'worktree cleanup: failed to remove "%s"   # branch '\''%s'\''\n' \
        "$orphan_path" "$orphan_branch" >&2
    fi
  fi
done <<< "$clean_orphans"

_prune_if_requested

exit 0
