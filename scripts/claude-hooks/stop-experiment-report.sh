#!/usr/bin/env bash
# Claude Code Stop hook — experiment-result HTML safety net (issue #1661).
#
# Enforcement: pipeline (local report refresh only; not a tool-call gate).
# Classification rationale: Stop-hook fires after the assistant reply ends and
# only writes paired .html files alongside existing aggregate/markdown reports
# under reports/. It never refuses tool use, never mutates git, and never
# performs shipping side-effects.
#
# Why this exists: Makefile targets render the paired HTML inline, but ad-hoc
# `python3 eval/run_eval.py ...` paths bypass that. This hook is the safety net
# that catches stale/missing pairs on the next Stop event.
#
# Disable per-shell with:   BIDMATE_EXPERIMENT_REPORT_STOP_HOOK=0
# Force-run for testing:    BIDMATE_EXPERIMENT_REPORT_FORCE=1

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FIRE_LOG="$REPO_ROOT/.claude/.hook-fires.log"

if [[ "${BIDMATE_EXPERIMENT_REPORT_STOP_HOOK:-1}" != "1" ]]; then
  exit 0
fi

cd "$REPO_ROOT" || exit 0

if [[ ! -d reports ]]; then
  exit 0
fi

# Fast path: if nothing is stale, exit silently. Render only the diff.
if python3 scripts/render_experiment_report_html.py --check --auto-scan --quiet 2>/dev/null; then
  : # 0 stale — no-op
else
  # Exit code 1 from --check means stale pairs exist; render them now.
  python3 scripts/render_experiment_report_html.py --auto-scan 2>&1 || true
fi

python3 scripts/_governance.py --emit-fire \
  --outcome pipeline_end --hook experiment-report --category stop-report \
  --path reports \
  --fire-log "$FIRE_LOG" 2>/dev/null || true

exit 0
