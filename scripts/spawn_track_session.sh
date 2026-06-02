#!/usr/bin/env bash
set -euo pipefail

# Spawn an isolated cmux track session for a side task (issue #1767).
#
# Two-layer design (memory project_skill_authoring: 기계적=도구재사용 /
# 스킬=판단레이어). This is the THIN MECHANICAL layer: it captures the
# escaping / PATH / platform traps of nesting
#   cmux workspace create --command "claude '<prompt>'"
# The *judgment* layer (which track-surface rules to synthesize into the
# prompt: real100_v2-only / chroma baseline / BGE-M3 OOM …) is a separate
# skill, intentionally deferred until the pattern repeats — over-engineering
# guard: 빈도≠가치 (one session, 3 tracks on 2026-06-02 is not yet a pattern).
#
# What it does:
#   1. Assemble an ADR-0007 branch name, then VALIDATE it via the SSoT
#      (scripts/check_branch_and_issue.py) — never copies the regex.
#   2. `git worktree add` an origin/main-based isolated worktree. This never
#      touches the caller's HEAD (memory project_omc_teleport_adr0007).
#   3. If inside cmux, `cmux workspace create` a cold-start `claude` session
#      in that worktree, focus kept on the caller. Outside cmux, print a
#      manual resume command and exit 0 (fallback is a normal path).
#
# Issue creation is OUT of scope (decided 2026-06-02). `make ship-start`
# does `git switch -c` on the *current* tree + refuses a dirty tree, which is
# incompatible with worktree isolation — so it cannot be reused here. Create
# the issue first (make ship-start / gh issue create) and pass ISSUE=N.
#
# Run from the repository root.
#
# Usage:
#   ISSUE=1764 PROMPT='measure retrieval recall on real100 v2' \
#     bash scripts/spawn_track_session.sh
#   make spawn-track ISSUE=1764 TYPE=eval SLUG=retrieval-remeasure PROMPT='...'
#   DRY_RUN=1 ...   # echo the git/cmux commands instead of running them
#
# Env:
#   ISSUE      (required) existing issue number the track will close
#   PROMPT     (required) cold-start prompt; see the escaping guard below
#   TYPE       branch type (default chore); ADR-0007 whitelist enforced
#   SLUG       optional kebab slug appended to the branch + worktree dir name
#   BASE       base ref for the new branch (default origin/main)
#   WT_PARENT  parent dir for the new worktree (default .. = sibling)
#   CMUX_BIN   cmux CLI path (default the macOS app-bundle absolute path)
#   DRY_RUN    1 = print the git/cmux commands without executing (default 0)

ISSUE="${ISSUE:?ISSUE=N (existing issue number) required}"
PROMPT="${PROMPT:?PROMPT='cold-start prompt' required}"
TYPE="${TYPE:-chore}"
SLUG="${SLUG:-}"
BASE="${BASE:-origin/main}"
WT_PARENT="${WT_PARENT:-..}"
DRY_RUN="${DRY_RUN:-0}"
# Absolute path: a bare `cmux` is not on PATH in eval/subprocess contexts
# (issue #1767 실측). Tests override this with a stub.
CMUX_BIN="${CMUX_BIN:-/Applications/cmux.app/Contents/Resources/bin/cmux}"

# --- Escaping guard (issue #1767 실측) -------------------------------------
# The cold-start command is the NESTED form  --command "claude '<prompt>'".
# Inside that single-quoted inner string a backtick / $ / ! / " / ' breaks
# the quoting and corrupts the spawned command. We REJECT (never sanitize) so
# the prompt's meaning is not silently altered. `#` is safe inside single
# quotes and is allowed (ADR numbers, issue refs like #1767).
bad=""
case "$PROMPT" in
  *'`'*)  bad='backtick (`)' ;;
  *'$'*)  bad='dollar ($)' ;;
  *'!'*)  bad='bang (!)' ;;
  *'"'*)  bad='double-quote (")' ;;
  *"'"*)  bad="apostrophe (')" ;;
esac
if [ -n "$bad" ]; then
  echo "spawn: PROMPT contains a forbidden char: $bad" >&2
  echo "spawn: nested cmux --command \"claude '...'\" cannot escape it." >&2
  echo "spawn: rewrite the prompt without it ('#' is allowed)." >&2
  exit 1
fi

# --- Branch name: assemble, then validate via SSoT (no regex copy) ---------
BRANCH="${TYPE}/issue-${ISSUE}${SLUG:+-${SLUG}}"
if ! python3 scripts/check_branch_and_issue.py --branch "$BRANCH"; then
  echo "spawn: assembled branch '$BRANCH' fails the ADR-0007 convention." >&2
  echo "spawn: fix TYPE (whitelist) or SLUG (kebab a-z0-9-) and retry." >&2
  exit 1
fi

WT="${WT_PARENT}/issue-${ISSUE}-${SLUG:-track}"

# DRY_RUN echoes a command with %q-quoted args instead of running it. Simple
# sequential commands only — `declare -a` arrays lose PATH in eval contexts
# (issue #1767 실측: `command not found: git`).
run() {
  if [ "$DRY_RUN" = 1 ]; then
    printf 'DRY_RUN:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

# --- Isolated worktree (memory project_omc_teleport_adr0007) ---------------
# Fetch first so origin/main is fresh (stale-ref false-negative gotcha), then
# add the worktree off origin/main for isolation. worktree add never moves the
# caller's HEAD, so spawning from any worktree is safe.
run git fetch origin main
run git worktree add "$WT" -b "$BRANCH" "$BASE"

# --- cmux detect → spawn / fallback ---------------------------------------
if "$CMUX_BIN" identify --json >/dev/null 2>&1; then
  # Permission is fixed: `claude '<prompt>'` with NO permission flags
  # (--dangerously-skip-permissions etc. are never injected — measurement /
  # guard work keeps destructive ops human-gated). --focus false keeps the
  # caller's focus.
  run "$CMUX_BIN" workspace create --cwd "$WT" --command "claude '${PROMPT}'" --focus false
  echo "spawn: track session created in $WT (focus kept on caller)." >&2
else
  echo "spawn: not inside cmux — worktree is ready, resume manually:" >&2
  echo "  cd \"$WT\" && claude '${PROMPT}'"
fi
