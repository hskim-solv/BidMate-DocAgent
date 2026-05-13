#!/usr/bin/env bash
# Auto-ship Stop hook dispatcher for BidMate-DocAgent.
#
# Registered in `.claude/settings.json` as a Stop hook. Fires on every
# Claude reply termination. The dominant case is no-op (no arm-file
# present) — that path must complete in well under 100ms.
#
# When armed via `make ship-arm`, runs an 8-gate pre-check then a 5-stage
# pipeline (commit → push → PR → CI wait → squash-merge). Single-shot:
# every successful or failed cycle disarms automatically.
#
# Hook input (stdin, JSON): currently discarded.
#
# Documentation: docs/auto-ship.md, the plan at
# /Users/hskim/.claude/plans/prci-synchronous-newell.md, and CLAUDE.md.

set -u

ARMED_FILE=".claude/.ship-armed"
PID_FILE=".claude/.ship-running.pid"
HISTORY_LOG=".claude/.ship-history.log"
DRYRUN_LOG=".claude/.ship-dryrun.log"
TEST_SUMMARY_PATH="$(mktemp /tmp/ship-test-summary.XXXXXX)"

DRY_RUN=0
ARM_BRANCH=""
ARM_REAL_EVAL_MODE="auto"
ARM_DRAFT="false"
ARM_CROSS_OWNER=""
ARM_STACKED=""

log() { printf '[ship%s] %s\n' "${1:+:$1}" "${2:-$1}" >&2; }
die() { log "fatal" "$1"; exit "${2:-1}"; }

# ---------------------------------------------------------------------------
# Gate 0 — eight pre-checks (silent exit on any failure path)
# ---------------------------------------------------------------------------

gate_0_armed_file_exists() {
  [[ -f "$ARMED_FILE" ]] || exit 0
}

gate_0_parse_armed_file() {
  local parsed
  parsed=$(python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    for k in ("branch", "expires_at", "merge_mode", "real_eval_mode"):
        if k not in d:
            print(f"missing:{k}"); sys.exit(1)
    print(d["branch"])
    print(d["expires_at"])
    print(d.get("real_eval_mode", "auto"))
    print(d.get("draft", "false"))
    print(d.get("dry_run", 0))
    print(d.get("cross_owner", ""))
    print(d.get("stacked", ""))
except Exception as e:
    print(f"parse:{e}"); sys.exit(1)
' "$ARMED_FILE" 2>&1) || { log "gate" "ship-armed JSON malformed: $parsed"; exit 0; }
  ARM_BRANCH=$(printf '%s\n' "$parsed" | sed -n '1p')
  ARM_EXPIRES=$(printf '%s\n' "$parsed" | sed -n '2p')
  ARM_REAL_EVAL_MODE=$(printf '%s\n' "$parsed" | sed -n '3p')
  ARM_DRAFT=$(printf '%s\n' "$parsed" | sed -n '4p')
  DRY_RUN=$(printf '%s\n' "$parsed" | sed -n '5p')
  ARM_CROSS_OWNER=$(printf '%s\n' "$parsed" | sed -n '6p')
  ARM_STACKED=$(printf '%s\n' "$parsed" | sed -n '7p')
}

gate_0_not_expired() {
  local now expires
  now=$(date -u +%s)
  expires=$(date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$ARM_EXPIRES" "+%s" 2>/dev/null || \
            date -u -d "$ARM_EXPIRES" +%s 2>/dev/null || echo 0)
  if (( now >= expires )); then
    log "gate" "arm expired at $ARM_EXPIRES — disarming"
    rm -f "$ARMED_FILE"
    exit 0
  fi
}

gate_0_branch_matches() {
  local current
  current=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
  if [[ "$current" != "$ARM_BRANCH" ]]; then
    log "gate" "current branch '$current' != armed '$ARM_BRANCH' — disarming"
    rm -f "$ARMED_FILE"
    exit 0
  fi
}

gate_0_branch_firewall() {
  case "$ARM_BRANCH" in
    main|master|develop|HEAD) die "tier-3 firewall: cannot ship from '$ARM_BRANCH'" ;;
    release/*) die "tier-3 firewall: cannot ship from release branch '$ARM_BRANCH'" ;;
  esac
}

gate_0_has_work() {
  local porcelain ahead
  porcelain=$(git status --porcelain 2>/dev/null)
  ahead=$(git rev-list --count "@{upstream}..HEAD" 2>/dev/null || echo 0)
  if [[ -z "$porcelain" && "$ahead" == "0" ]]; then
    log "gate" "nothing to ship (clean tree, no unpushed commits)"
    exit 0
  fi
}

gate_0_no_git_in_progress() {
  local git_dir
  git_dir=$(git rev-parse --git-dir 2>/dev/null) || return 0
  for marker in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD rebase-merge rebase-apply; do
    if [[ -e "$git_dir/$marker" ]]; then
      log "gate" "git transitional state detected ($marker) — refusing"
      exit 0
    fi
  done
}

gate_0_no_live_pid() {
  if [[ -f "$PID_FILE" ]]; then
    local prev_pid
    prev_pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [[ -n "$prev_pid" ]] && kill -0 "$prev_pid" 2>/dev/null; then
      log "gate" "previous run pid=$prev_pid still alive — silent exit"
      exit 0
    fi
    rm -f "$PID_FILE"
  fi
}

# ---------------------------------------------------------------------------
# Lock + cleanup trap
# ---------------------------------------------------------------------------

acquire_lock() {
  echo "$$" > "$PID_FILE"
}

release_lock() {
  rm -f "$PID_FILE"
  rm -f "$TEST_SUMMARY_PATH"
}

abort_disarm() {
  local stage="$1" msg="$2"
  log "$stage" "ABORT: $msg"
  printf '%s\tABORT\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$stage" "$msg" >> "$HISTORY_LOG"
  rm -f "$ARMED_FILE"
  release_lock
  exit 1
}

trap 'release_lock' EXIT

# ---------------------------------------------------------------------------
# run / dry-run helpers
# ---------------------------------------------------------------------------

# Mutating commands go through `mut`; reads go through normal subshells.
mut() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run] %s\n' "$*" | tee -a "$DRYRUN_LOG" >&2
    return 0
  fi
  "$@"
}

# Capture mutating stdout (e.g. `gh pr create` returns the URL).
mut_capture() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run] %s\n' "$*" | tee -a "$DRYRUN_LOG" >&2
    printf 'https://github.com/EXAMPLE/EXAMPLE/pull/9999\n'
    return 0
  fi
  "$@"
}

# ---------------------------------------------------------------------------
# Stage 1 — stage + commit
# ---------------------------------------------------------------------------

stage_1_commit() {
  log "s1" "Stage 1: commit"
  local porcelain
  porcelain=$(git status --porcelain 2>/dev/null)
  if [[ -z "$porcelain" ]]; then
    log "s1" "no uncommitted changes — skipping commit"
    return 0
  fi

  # Filter staged candidate paths through pre-commit's BLOCKED_PATTERNS.
  # We rely on `.githooks/pre-commit` as the actual second-line gate,
  # but pre-filter so we don't propose to stage obviously private files.
  local files=()
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    local path="${line:3}"
    case "$path" in
      data/files/*|data/data_list.csv|data/data_list.xlsx) continue ;;
      eval/*.local.yaml) continue ;;
      reports/real*/*) continue ;;
    esac
    files+=("$path")
  done <<< "$porcelain"

  if [[ ${#files[@]} -eq 0 ]]; then
    abort_disarm "s1" "no eligible files to stage (all matched private paths)"
  fi

  # Multi-agent lock check.
  local lock_input
  lock_input=$(printf '%s\n' "${files[@]}")
  if ! printf '%s\n' "$lock_input" | \
       CROSS_OWNER="$ARM_CROSS_OWNER" \
       python3 scripts/claude-hooks/_ship_lock_check.py --branch "$ARM_BRANCH" --files-stdin; then
    abort_disarm "s1" "multi-agent lock check failed (see stderr above)"
  fi

  # Heterogeneous commit-prefix detection (tier 7).
  if [[ "$ARM_STACKED" != "ack" ]]; then
    local prefixes
    prefixes=$(git log "@{upstream}..HEAD" --format=%s 2>/dev/null | \
               sed -E 's/^([a-z]+)(\(.*\))?:.*/\1/' | sort -u | wc -l | tr -d ' ')
    if [[ "${prefixes:-0}" -gt 1 ]]; then
      abort_disarm "s1" "heterogeneous commit prefixes (one PR per concern); bypass with STACKED=ack"
    fi
  fi

  # Run tests once before committing; cache summary for PR body §4.
  log "s1" "running bash scripts/test.sh (cached for PR body §4)"
  if ! bash scripts/test.sh > "$TEST_SUMMARY_PATH" 2>&1; then
    log "s1" "tests failed — see $TEST_SUMMARY_PATH"
    tail -40 "$TEST_SUMMARY_PATH" >&2
    abort_disarm "s1" "local test suite failed; not committing"
  fi
  echo "Local tests passed (bash scripts/test.sh)." > "$TEST_SUMMARY_PATH"

  # Stage selectively.
  for f in "${files[@]}"; do
    mut git add -- "$f" || abort_disarm "s1" "git add $f failed"
  done

  # Generate commit message.
  local issue_n branch_type subject body
  issue_n=$(python3 -c "
import sys
sys.path.insert(0, 'scripts')
from check_branch_and_issue import parse_branch
print(parse_branch('$ARM_BRANCH'))
")
  branch_type="${ARM_BRANCH%%/*}"
  subject=$(gh issue view "$issue_n" --json title --jq ".title" 2>/dev/null || echo "")
  if [[ -z "$subject" ]]; then
    subject="implement issue #$issue_n"
  fi
  local commit_subject="${branch_type}: ${subject} (#${issue_n})"
  local commit_body
  commit_body=$(cat <<EOF
${commit_subject}

Closes #${issue_n}

🤖 Auto-shipped by scripts/claude-hooks/stop-ship.sh

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run] git commit with message:\n%s\n' "$commit_body" | \
      tee -a "$DRYRUN_LOG" >&2
  else
    if ! git commit -m "$commit_body"; then
      abort_disarm "s1" "git commit failed (likely pre-commit hook block)"
    fi
  fi

  printf '%s\tS1_OK\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ARM_BRANCH" >> "$HISTORY_LOG"
}

# ---------------------------------------------------------------------------
# Stage 2 — push
# ---------------------------------------------------------------------------

stage_2_push() {
  log "s2" "Stage 2: push"
  if ! python3 scripts/check_branch_and_issue.py --branch "$ARM_BRANCH" --check-issue; then
    abort_disarm "s2" "branch convention or issue existence check failed"
  fi
  local has_upstream=0
  git rev-parse "@{upstream}" >/dev/null 2>&1 && has_upstream=1
  if (( has_upstream )); then
    mut git push || abort_disarm "s2" "git push failed"
  else
    mut git push -u origin HEAD || abort_disarm "s2" "git push -u failed"
  fi
}

# ---------------------------------------------------------------------------
# Stage 3 — PR body + create
# ---------------------------------------------------------------------------

stage_3_pr() {
  log "s3" "Stage 3: PR create"
  PR_NUMBER=""
  PR_URL=""

  local existing
  existing=$(gh pr list --head "$ARM_BRANCH" --json number --jq '.[0].number' 2>/dev/null || echo "")
  if [[ -n "$existing" && "$existing" != "null" ]]; then
    PR_NUMBER="$existing"
    log "s3" "PR #$PR_NUMBER already exists for $ARM_BRANCH — reusing"
    return 0
  fi

  local body_file
  body_file=$(mktemp /tmp/ship-pr-body.XXXXXX)
  trap 'rm -f "$body_file"; release_lock' EXIT

  if ! python3 scripts/claude-hooks/_ship_pr_body.py \
        --branch "$ARM_BRANCH" \
        --base-ref origin/main \
        --real-eval-mode "$ARM_REAL_EVAL_MODE" > "$body_file"; then
    abort_disarm "s3" "PR body generator failed (likely §5b validation)"
  fi

  local commit_subject
  commit_subject=$(git log -1 --format=%s HEAD)

  local draft_flag=""
  [[ "$ARM_DRAFT" == "true" ]] && draft_flag="--draft"

  PR_URL=$(mut_capture gh pr create \
    --base main \
    --head "$ARM_BRANCH" \
    --title "$commit_subject" \
    --body-file "$body_file" \
    $draft_flag) || abort_disarm "s3" "gh pr create failed"

  if [[ "$DRY_RUN" != "1" ]]; then
    PR_NUMBER=$(printf '%s\n' "$PR_URL" | grep -oE '/pull/[0-9]+' | tr -d '/' | sed 's/pull//')
  else
    PR_NUMBER=9999
  fi
  log "s3" "created PR #$PR_NUMBER ($PR_URL)"
}

# ---------------------------------------------------------------------------
# Stage 4 — CI wait
# ---------------------------------------------------------------------------

stage_4_ci() {
  log "s4" "Stage 4: CI wait (timeout 30min)"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "s4" "[dry-run] gh pr checks $PR_NUMBER --watch --interval 30"
    return 0
  fi
  if ! timeout 1800 gh pr checks "$PR_NUMBER" --watch --interval 30; then
    local rc=$?
    if (( rc == 124 )); then
      gh pr comment "$PR_NUMBER" --body "Auto-ship: CI timeout after 30min; PR left open." || true
      abort_disarm "s4" "CI timeout (30min)"
    fi
    gh pr comment "$PR_NUMBER" --body "Auto-ship: required CI check failed (rc=$rc); pipeline disarmed." || true
    abort_disarm "s4" "required CI check failed"
  fi
  log "s4" "all required checks green"
}

# ---------------------------------------------------------------------------
# Stage 5 — squash-merge + cleanup
# ---------------------------------------------------------------------------

stage_5_merge() {
  log "s5" "Stage 5: squash-merge + cleanup"
  local commit_subject
  commit_subject=$(git log -1 --format=%s HEAD)
  local commit_body_file
  commit_body_file=$(mktemp /tmp/ship-merge-body.XXXXXX)
  git log -1 --format=%b HEAD > "$commit_body_file"

  mut gh pr merge "$PR_NUMBER" \
    --squash --admin --delete-branch \
    --subject "$commit_subject" \
    --body-file "$commit_body_file" || \
    abort_disarm "s5" "gh pr merge failed (admin merge unavailable?)"

  rm -f "$commit_body_file"

  if [[ "$DRY_RUN" != "1" ]]; then
    local state
    state=$(gh pr view "$PR_NUMBER" --json state --jq .state 2>/dev/null || echo "UNKNOWN")
    if [[ "$state" != "MERGED" ]]; then
      log "s5" "post-merge state is '$state' — not MERGED; leaving arm in place for inspection"
      release_lock
      exit 1
    fi
  fi

  mut git checkout main || true
  mut git pull --ff-only origin main || log "s5" "git pull --ff-only had non-zero exit (continuing)"
  mut git branch -D "$ARM_BRANCH" 2>/dev/null || true

  printf '%s\tS5_OK\tPR#%s\t%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$PR_NUMBER" "$ARM_BRANCH" >> "$HISTORY_LOG"
  log "s5" "Ship complete: PR #$PR_NUMBER merged to main"
  rm -f "$ARMED_FILE"
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

main() {
  cat >/dev/null  # discard stdin

  gate_0_armed_file_exists
  gate_0_parse_armed_file
  gate_0_not_expired
  gate_0_branch_matches
  gate_0_branch_firewall
  gate_0_has_work
  gate_0_no_git_in_progress
  gate_0_no_live_pid

  acquire_lock

  log "main" "armed=$ARM_BRANCH dry_run=$DRY_RUN real_eval=$ARM_REAL_EVAL_MODE"
  if [[ "$DRY_RUN" == "1" ]]; then
    : > "$DRYRUN_LOG"
  fi

  stage_1_commit
  stage_2_push
  stage_3_pr
  stage_4_ci
  stage_5_merge

  log "main" "single-shot ship cycle finished"
  exit 0
}

main "$@"
