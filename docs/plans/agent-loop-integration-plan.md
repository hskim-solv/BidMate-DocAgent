# Agent-loop 보조 도구 통합 plan (핸드오프)

> **작성:** 2026-06-01 세션 (worktree 청소 → salvage PR #1739/#1740 머지 직후 도출).
> **상태:** ✅ **완료** — T-X1~X4 전부 구현·머지(2026-06-01). 아래 "완료 기록" 참조. 이 문서는 핸드오프 plan 의 역사적 기록.
> **이유:** 직전 세션이 극도로 길어 컨텍스트 한계 + 일부 통합이 agent-loop 자기수정이라 신중 설계 필요.

## 완료 기록 (2026-06-01)

4종 모두 **advisory-only(호출만)** 로 구현 — 제어 흐름 불변(preflight exit code · gate ready 결정 · auto-loop defer/stop 흐름 그대로), `EXECUTE_SHIP=0` 유지. 각 통합 = 이슈 + ADR 0007 브랜치 + 회귀 테스트, 별도 worktree 작업.

| # | 통합 | PR | 이슈 | 끼운 곳 |
|---|---|---|---|---|
| T-X3 | ralplan plan-gate advisory | #1743 | #1741 | `render_preflight` (모호 task = AC·validation 둘 다 없을 때만) |
| T-X2 | eval-anomaly-investigator advisory | #1744 | #1742 | `write_active_gate_evidence` (eval surface 터치 시) |
| T-X1 | wiki + memory-curator advisory | #1747 | #1745 | `write_active_auto_loop` 완료 (사이클 실행 시) |
| T-X4 | codex:rescue / tracer escalation advisory | #1748 | #1746 | auto-repair lane 소진 후 defer 경로 |

- 🔴 자기수정 항목(T-X1/T-X4)은 사용자 명시 확인 후 **advisory-only** 방식 채택(Stop-hook/auto-invoke 거부) — 자율 루프가 자기 코드를 실행 중 고치지 않음.
- #1748 은 #1747 과 `write_active_auto_loop` 앞 helper 추가 위치에서 충돌 → 두 advisory 헬퍼 모두 보존하는 방식으로 해소, CI(pytest 4 shard) green 후 머지.

## 목표

`make 시작`(agent-loop, ADR 0082/0085/0092) 시스템에 보조 도구 4종을 통합해 약점(학습 누적·도메인 진단·막힘 백스톱)을 메운다.

## 배경 — 현재 agent-loop이 가진 것 (중복 추가 금지)

runner 분배(claude 6/codex 4, quota 기반) · role lane(Planner/Reviewer/Benchmark·Privacy·Security Auditor, ADR 0082) · codex adversarial review(pre-commit, ADR 0066) · auto-repair · readiness gate · ship(EXECUTE_SHIP=0). 실행 엔진은 이미 강함. `code-reviewer`/`verifier`/`critic`은 role lane으로 이미 커버.

## 통합 항목 (우선순위 + 자기수정 위험)

| # | 통합 | 끼우는 곳 | 자기수정 | 시작 omc 자율 |
|---|---|---|---|---|
| T-X1 | **wiki + memory-curator** (학습 누적 — 최대 갭) | `Stop` hook / auto-loop 완료 콜백 | ⚠️ hook 추가 | 사람 검토 |
| T-X2 | **eval-anomaly-investigator** 트리거 | review 게이트 (eval 회귀 감지 시) | 호출만 | ✅ 안전 |
| T-X3 | **ralplan** 계획 게이트 | queue 선정 → preflight 사이 (모호 task crystallize) | 호출만 | ✅ 안전 |
| T-X4 | **codex:rescue / tracer** 에스컬레이션 | `agent_loop.py` repair 분기 (N회 실패 시) | 🔴 **agent_loop.py 수정** | **자율 금지** |

보조: `Workflow` 도구(task 내 병렬), `ai-slop-cleaner`(review 전 deslop) — 필요 시.

## 🔴 자기수정 금지 규칙 (load-bearing)

T-X4(codex:rescue/tracer를 `agent_loop.py`에 끼우기)는 **agent-loop이 자기 자신의 코드를 수정**하게 된다. 자율 루프가 실행 중 자기 코드를 고치면 망가졌을 때 복구 불가. **반드시 사람이 별도 worktree에서 구현·검토.** 시작 omc 자율 루프에 절대 맡기지 않는다.

> 실제 채택: T-X4 는 agent_loop.py 에 advisory 텍스트만 기록(제어 흐름 무변경)하고, 실제 codex:rescue/tracer 호출은 사람이 수행 — 자기수정 위험을 advisory-only 로 회피.

## 새 세션 시작 가이드

1. 이 plan + 직전 세션 맥락(통합 추천 도출) 확인.
2. 각 통합 = GitHub 이슈 + ADR 0007 컨벤션 브랜치. T-X1/T-X4는 ADR 필요 여부 검토(hook/repair 분기 = 동작 변경).
3. **안전 분리:** T-X2/T-X3(호출만)는 시작 omc 자율 처리 후보. T-X1/T-X4(자기수정)는 사람 직접.
4. `EXECUTE_SHIP=0` 유지 — draft까지만, 머지는 사람 게이트.
5. 동작 변경 ↔ 회귀 테스트 동반 (CLAUDE.md). 각 통합 후 `make test-fast`.
6. tasks/queue.md 에 T-X1~X4 행 추가 후 진행.

## 참조

- `scripts/agent_loop.py`, Makefile `시작` 타겟 (1102~), `reports/agent_loop/active/agent_mix.json`
- ADR 0082(lane model×effort) / 0085(infinite mode) / 0092(lane autotune) / 0066(pre-commit codex)
- 추천 도출 근거: 2026-06-01 세션 대화
