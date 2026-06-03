# 0099: active-loop conservative gate 에 객관 검증 신호 합성 — verdict-only → verdict ∧ objective (opt-in)

- **Status**: proposed
- **Date**: 2026-06-03
- **Deciders**: User, Claude Code as implementer
- **Related**: [ADR 0080](./0080-active-loop-registry-v2-dual-agent-lanes.md) (registry v2 / gate role-status 계약), [ADR 0082](./0082-dual-lane-adversarial-messages-api-adaptive-thinking.md) (dual-lane / verdict schema), [ADR 0086](./0086-lane-tool-sandbox-policy-option-c.md) (review lane 검증명령 금지 + mktemp isolation Deferred), [ADR 0094](./0094-concurrency-substrate-for-parallel-loop.md) (concurrency substrate), [ADR 0001](./0001-preserve-naive-baseline.md) (baseline byte-identical), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (데이터 경계); issue #1828

## Context

`make 시작` 자율루프의 conservative gate 는 reviewer/role 의 **self-report verdict 문자열**만 본다. `_active_role_status_ok` (`scripts/agent_loop.py`) 는 status ∈ {pass,passed,approved,ready-for-ship,done,clear} 포함 여부만 보고, `write_active_gate_evidence` 의 `ready = bool(required_roles) and all(role.ok)` 는 그 role status 합집합이다. reviewer 자체는 role label + `_role_header` orientation 이 붙은 공통 claude-turn 으로, 전용 시스템프롬프트도 정적분석/test 도구도 없다 — gate 가 모델이 스스로 보고한 문자열을 그대로 신뢰한다.

자산 연결·갭 조사(`.omc/research/sijak-autoloop-asset-recommendation.md` v3) + architect(Opus)↔Codex(xhigh) 2차 의견 교차검증 결론: (1) "전문 리뷰 agent 를 reviewer lane 에 subagent 로 spawn" 은 **구조적 불가** — headless `claude -p` tool_use crash(#1598) + read lane allowlist 에 `Task`/`lsp_diagnostics` 부재 + ADR 0094 concurrency; (2) 정답은 **객관 측정 신호를 gate 에 합성**; (3) 이미 자산이 있다 — `run_validation_commands` 가 allowlist 명령을 subprocess 로 실제 실행하고, 같은 evidence dict 의 `privacy = {"clean": ...}` 가 verdict-독립 객관신호의 선례다.

Codex 정정: "pytest 실행 0건"은 reviewer lane 한정이고 `run_validation_commands` 가 repo 전체에선 실제 실행하므로 **신규 실행기는 불필요**하다. 단 self-report verdict / validation result / stale heartbeat 가 섞이면 **fail-open/false-pass** 가 생기므로 source precedence 를 명시해야 한다.

## Decision

conservative gate evidence 에 객관 검증 신호를 **opt-in 으로 합성**하고 `ready` 를 `verdict ∧ objective` 로 강화한다.

- **(a) `validation` 객관신호 (opt-in).** `write_active_gate_evidence(..., run_validation: bool = False)` 를 추가한다. 기본값 `False` → evidence/`ready` 가 기존과 byte-identical (ADR 0001). `True` 면 신규 `_gate_validation_signal(files, *, repo_root)` 가 기존 `run_validation_commands` 를 **재사용**해 `{ran, passed, returncode, command_count}` 를 evidence dict 에 `privacy` 와 같은 패턴으로 기록한다.
- **(b) `ready` 강화 (toggle = `run_validation`).** `ready = bool(required_roles) and all(role.ok) and (validation["passed"] is not False)`. validation 이 `ran` 이고 `passed=False` 면 role 이 전부 pass 여도 **NOT ready**.
- **(c) source precedence 명시.** evidence `conservative_gate` 에 `objective_ok` 와 `precedence: "self-report < validation; stale heartbeat invalidated"` 를 기록한다. validation 미실행(`ran=False`)은 **명시적 미적용**(기존 role-only gate 로 fallback)이지 fail-open 이 아니다 — 이 구분을 evidence 가 드러낸다.
- **(d) read-only 계약 갱신.** `write_active_gate_evidence` docstring 을 "기본 read-only audit; `run_validation=True` 시 allowlist 검증 실행(opt-in)" 으로 고친다. 명령 안전성은 기존 allowlist `_validation_command_allowed` 가 보장한다.

**범위 한정 (one concern):** 본 ADR 은 `write_active_gate_evidence` 의 evidence gate 한 경로만 강화한다. 나머지 3개 gate 경로(`_active_role_status_ok` 직접 호출처 / codex `status_for_gate` / exit-code gate), 그리고 mktemp 완전격리(ADR 0086 Deferred output-isolation)는 **follow-up 으로 분리**한다.

## Consequences

- (+) reviewer self-report 가 객관 검증(allowlist lint/test)과 AND 되어 false-pass 를 차단한다. privacy 에 이은 두번째 verdict-독립 신호.
- (+) 기본 off 라 ADR 0001 baseline / 기존 CI / 데모 경로가 byte-identical 로 유지된다 — gate 의 `run_validation` toggle 이 유일한 동작 분기점.
- (+) 신규 실행기 없이 `run_validation_commands` 를 재사용한다 (Codex 정정 반영).
- (−) `run_validation=True` 면 gate evidence 생성이 더 이상 순수 read-only 가 아니다 (allowlist 검증 실행). opt-in + docstring 으로 한정한다.
- (−) mktemp 완전격리 전까지 `run_validation=True` 는 자기 worktree 에서 실행한다 — 동시 무한루프의 race 는 follow-up 격리로 해소한다.
- (−) gate 경로 4곳 중 1곳만 강화 → 나머지는 follow-up 까지 verdict-only 로 남는다.

## Alternatives considered

- **전문 agent subagent spawn (code-reviewer/critic/verifier).** 조사·교차검증 결과 headless `-p` tool_use crash + allowlist 부재 + ADR 0094 로 **구조적 불가**. 채택 안 함.
- **신규 검증 실행기 작성.** `run_validation_commands` 가 이미 allowlist subprocess 실행을 한다(Codex 정정). 중복이라 재사용.
- **기본 on (always-validate).** ADR 0001 byte-identical 과 ADR 0086 race 를 침해. opt-in 으로 보류 + follow-up 격리 후 재검토.

## Verification

- `run_validation=False`(기본) 회귀: evidence dict 와 `ready` 가 기존과 동일해야 한다 (byte-identical).
- `run_validation=True` + validation pass → `ready == role_ok`; validation fail → role 전부 pass 여도 `ready == False`.
- `_gate_validation_signal` 의 allowlist 거부 케이스가 `passed=False` 로 기록되는지.

<!-- verifies-key: scripts/agent_loop.py:_gate_validation_signal -->
<!-- verifies-key: scripts/agent_loop.py:run_validation -->
<!-- verifies-key: tests/test_agent_loop.py:run_validation -->
