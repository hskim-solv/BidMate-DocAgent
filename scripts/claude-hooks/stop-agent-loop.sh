#!/usr/bin/env bash
# Claude Code Stop hook for BidMate agent-loop lightweight status refresh.
#
# Enforcement: pipeline (local report refresh only; not a tool-call gate).
# Classification rationale: Stop-hook only fires after Claude reply ends and
# writes ignored local status reports when explicitly armed; it never refuses
# tool use and never performs shipping mutations.
# See scripts/claude-hooks/README.md for the full enforcement taxonomy.
#
# Registered in `.claude/settings.json` as a Stop hook. Dominant path is no-op:
# unless `.claude/.agent-loop-watch` exists, or BIDMATE_AGENT_LOOP_STOP_HOOK=1
# is set, the hook exits immediately.
#
# When enabled, refreshes only status-oriented reports:
#   - reports/agent_loop/gate_status.md
#   - reports/agent_loop/loop_state.json
#   - reports/agent_loop/auto_pass.md
#
# It intentionally does not pass --run-validation to auto-pass-check, and it
# never renders auto-ship prepare/plan reports, pushes, creates/merges/closes
# PRs, deletes branches, force-pushes, runs private real-eval, or approves
# benchmark/private claims.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WATCH_FILE="$REPO_ROOT/.claude/.agent-loop-watch"
FIRE_LOG="$REPO_ROOT/.claude/.hook-fires.log"

if [[ ! -f "$WATCH_FILE" && "${BIDMATE_AGENT_LOOP_STOP_HOOK:-0}" != "1" ]]; then
  exit 0
fi

cd "$REPO_ROOT" || exit 0
mkdir -p reports/agent_loop

python3 scripts/agent_loop.py gate-status --from-git \
  --out reports/agent_loop/gate_status.md >/dev/null 2>&1 || true
python3 scripts/agent_loop.py loop-state --from-git \
  --out reports/agent_loop/loop_state.json >/dev/null 2>&1 || true
python3 scripts/agent_loop.py auto-pass-check --from-git \
  --out reports/agent_loop/auto_pass.md >/dev/null 2>&1 || true

python3 scripts/_governance.py --emit-fire \
  --outcome pipeline_end --hook agent-loop --category stop-report \
  --path reports/agent_loop/loop_state.json \
  --fire-log "$FIRE_LOG" 2>/dev/null || true

exit 0
