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
#   OVERLAP    ack = acknowledge a stale-base overlap blocker and proceed (#1836)
#   NO_OVERLAP_CHECK  1 = skip the overlap-preflight start-of-task gate (#1836)
#   OVERLAP_PATHS     space-separated load-bearing paths for the path-scope scan

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

# --- Overlap-preflight gate (issue #1836) ----------------------------------
# Between the fetch and the worktree add, run overlap-preflight so the new
# track does not start on a stale base or silently collide on a load-bearing
# path. Policy: a base-staleness blocker (local HEAD lacks origin/main) BLOCKS
# unless OVERLAP=ack; path/open-PR overlap warns + continues; any failure to
# RUN the scan fails OPEN (read-only advisory, never hard-fail a fresh task on
# transient git/gh state — memory feedback_merge_admin_gate §7). Skip entirely
# with NO_OVERLAP_CHECK=1 (mirrors the --no-fetch escape on ship-start).
# overlap-preflight confines --out/--json-out under reports/agent_loop/, so the
# report goes there via mktemp (unique per run — no fixed /tmp, memory #1274).
OVERLAP="${OVERLAP:-}"
NO_OVERLAP_CHECK="${NO_OVERLAP_CHECK:-0}"
OVERLAP_PATHS="${OVERLAP_PATHS:-}"
overlap_gate() {
  [ "$NO_OVERLAP_CHECK" = 1 ] && return 0
  # Assemble the command once so DRY_RUN can echo the exact invocation.
  local report_dir="reports/agent_loop"
  if [ "$DRY_RUN" = 1 ]; then
    run python3 scripts/agent_loop.py overlap-preflight --issue "$ISSUE" --branch "$BRANCH" ${OVERLAP_PATHS:+--paths $OVERLAP_PATHS}
    return 0
  fi
  mkdir -p "$report_dir"
  local md json verdict
  md="$(mktemp "${report_dir}/overlap_XXXXXX.md")"
  json="$(mktemp "${report_dir}/overlap_XXXXXX.json")"
  # shellcheck disable=SC2086  # OVERLAP_PATHS is an intentional word-split list.
  python3 scripts/agent_loop.py overlap-preflight \
    --issue "$ISSUE" --branch "$BRANCH" --out "$md" --json-out "$json" \
    ${OVERLAP_PATHS:+--paths $OVERLAP_PATHS} >/dev/null 2>&1 || true
  # Parse the JSON in python: emit a verdict token on stdout + warnings on
  # stderr. Missing/garbled report => FAILOPEN (the scan could not run).
  verdict="$(
    OVERLAP_ACK="$OVERLAP" python3 - "$json" <<'PY'
import json, os, sys
try:
    rep = json.loads(open(sys.argv[1], encoding="utf-8").read())
except Exception:
    print("FAILOPEN")
    sys.exit(0)
blockers = [str(b) for b in rep.get("blockers", [])]
warnings = [str(w) for w in rep.get("warnings", [])]
for w in warnings:
    sys.stderr.write("spawn: overlap warning — %s\n" % w)
stale = any("does not contain origin/main" in b for b in blockers)
ack = os.environ.get("OVERLAP_ACK", "").strip().lower() == "ack"
if stale and not ack:
    for b in blockers:
        sys.stderr.write("spawn: overlap blocker — %s\n" % b)
    print("BLOCK_STALE")
elif stale and ack:
    sys.stderr.write("spawn: overlap — stale base acknowledged (OVERLAP=ack); continuing.\n")
    print("WARN")
else:
    print("WARN" if warnings else "CLEAR")
PY
  )"
  rm -f "$md" "$json"
  if [ "$verdict" = BLOCK_STALE ]; then
    echo "spawn: refuse — local HEAD does not contain origin/main (stale base)." >&2
    echo "spawn: refresh from latest main, or pass OVERLAP=ack to override." >&2
    exit 1
  fi
}

# --- Isolated worktree (memory project_omc_teleport_adr0007) ---------------
# Fetch first so origin/main is fresh (stale-ref false-negative gotcha), then
# add the worktree off origin/main for isolation. worktree add never moves the
# caller's HEAD, so spawning from any worktree is safe.
run git fetch origin main
overlap_gate
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
