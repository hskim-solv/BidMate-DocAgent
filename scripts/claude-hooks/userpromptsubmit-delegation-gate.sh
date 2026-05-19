#!/usr/bin/env bash
# Claude Code UserPromptSubmit hook for BidMate-DocAgent (issue #1014).
#
# Registered in `.claude/settings.json` with matcher `.*`. Inspects every
# user prompt for non-trivial change-intent keywords (Korean + English) and,
# when matched, emits a CLAUDE.md "위임 기본값" suggestion to stdout — which
# Claude receives as additional context for the next turn. Never blocks the
# user; only nudges (always exits 0).
#
# Why this hook exists: Q2-2026 self-review axis #2 (Agent 위임) graded △
# because Plan/Explore subagents were under-called on non-trivial diffs.
# CLAUDE.md already documents the rule; this hook makes the rule visible
# right at prompt time instead of relying on Claude to remember.
#
# A line is appended to `.claude/.hook-fires.log` in the existing 4-field
# format (`<ts>|<action>|<reason>|<path>`) so the `_self_review.py`
# `collect_governance_hooks` parser can count fires alongside the existing
# `memory-lines` / `load-bearing` reasons.
#
# Hook input (stdin, JSON):
#   { "session_id": "...", "transcript_path": "...", "prompt": "..." }

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

input=$(cat)

prompt=$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
except Exception:
    print("")
    sys.exit(0)
# UserPromptSubmit payload key may vary; try common variants.
p = d.get("prompt") or d.get("user_prompt") or d.get("user_message") or ""
print(p)
' 2>/dev/null)

# Non-trivial change-intent keywords (Korean + English). Tuned conservatively
# to keep the false-positive rate low — single typo fixes and one-liner
# question prompts should NOT trigger.
if printf '%s' "$prompt" | grep -qiE "리팩토링|refactor|구현해|implement|다 고쳐|전체.*수정|all files|새 기능|new feature|마이그레이션|migrat[ei]|레거시|legacy|아키텍처|architectur|재설계|redesign"; then
  # stdout → prepended to Claude's next-turn context.
  cat <<'EOF'

[agent-delegation-gate]: 비-trivial 변경 의도 감지. CLAUDE.md "위임 기본값" 적용 권장:
  • Plan subagent: >1 파일 또는 >50 LOC 예상 시 — 설계 검증 + 대안 평가
  • Explore subagent: 누적 Read ≥5회 또는 단일 파일 >200줄 예상 시 — 컨텍스트 보호

Trivial 변경(오타/단일 라인/단일 함수)은 직접 진행 OK.
EOF

  printf '%s|nudged|agent-delegation|<user-prompt>\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    >> "$REPO_ROOT/.claude/.hook-fires.log" 2>/dev/null || true
fi

exit 0
