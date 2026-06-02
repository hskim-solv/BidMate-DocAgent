#!/usr/bin/env bash
# Claude Code SessionStart hook — next-session worktree hygiene (ADR 0096).
#
# Enforcement: pipeline (session-lifecycle external-command orchestration; not a tool-call gate).
# Classification rationale: fires when a session begins and invokes
# `make worktree-cleanup` to remove the PREVIOUS session's merged clean orphan
# worktrees. It never refuses tool use; soft `exit 0` always.
# See scripts/claude-hooks/README.md for the full enforcement taxonomy.
#
# Registered in `.claude/settings.json` as a SessionStart hook. Why a
# next-session (SessionStart) cleanup rather than SessionEnd: a session ending
# does not mean the worktree's work is done (it may be briefly closed and
# reopened), and the current cwd-occupied worktree cannot safely delete itself
# mid-session. The `make ship-arm` auto path self-cleans because it runs as an
# external process AFTER the session ends; the synchronous in-session `ship-pr`
# path cannot. So the only safe moment to clean a merged self-worktree is the
# NEXT session start.
#
# Safety: delegates entirely to `make worktree-cleanup`
# (= `_pre-push-worktree-hygiene.sh --clean --prune --delete-branches`), whose
# three guards protect every shape of "unfinished work":
#   - self-skip   : the current cwd worktree is never a candidate
#   - clean-only  : dirty/untracked worktrees are skipped (no uncommitted loss)
#   - 4-signal    : only merge-confirmed branches (ancestor / patch-equiv /
#                   gone-upstream / opt-in gh) are deleted (no unmerged loss)
# No extra safety logic is needed here — the SSoT for the flag combination is
# the Makefile target.
#
# Performance: `make worktree-cleanup` early-exits when there are no orphans.
# To bound SessionStart latency when many worktrees have accumulated, the
# `git cherry` patch-id budget (the hygiene script's own OOM guard) defaults to
# a lower value here; override with BIDMATE_WORKTREE_HYGIENE_CHERRY_BUDGET.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT" || exit 0

# Lower the patch-id walk budget for session start (latency cap); honour an
# explicit override if the user set one.
export BIDMATE_WORKTREE_HYGIENE_CHERRY_BUDGET="${BIDMATE_WORKTREE_HYGIENE_CHERRY_BUDGET:-5}"

# Soft: capture output, never let a cleanup failure block the session start.
output=$(make worktree-cleanup 2>&1 || true)

removed=$(printf '%s\n' "$output" | grep -c 'worktree cleanup: removed' || true)
if [[ "${removed:-0}" -gt 0 ]]; then
  printf 'SessionStart worktree hygiene: removed %s merged worktree(s) left by a previous session.\n' "$removed"
fi

exit 0
