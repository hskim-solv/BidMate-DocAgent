# 0092: `make 시작` lane 적응형 effort autotune (opt-in, recommendation-only PR1)

- Status: proposed
- Date: 2026-06-01
- Deciders: User, Claude Code
- Related: [ADR 0087](./0087-opt-in-omc-team-parallel-runner.md) (opt-in runner 백엔드 / (d) runner 산출물 non-load-bearing), [ADR 0085](./0085-infinite-mode-active-auto-loop.md) (무한 모드 active-auto-loop), [ADR 0086](./0086-lane-tool-sandbox-policy-option-c.md) (lane Tool/Sandbox 정책), [ADR 0080](./0080-active-loop-registry-v2-dual-agent-lanes.md) (registry v2 / dual-agent lanes), [ADR 0061](./0061-external-and-paid-api-dependencies-allowed.md) (외부/유료 API opt-in 3조건), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (private 데이터 경계), [ADR 0001](./0001-preserve-naive-baseline.md) (baseline byte-identical 보존)
- Issue: #1716

## Context

`make 시작`(active-auto-loop)은 per-`(role,agent)` lane을 병렬로 실행하지만, lane별 실행시간이
**display-only**였다 ([`scripts/agent_loop.py`](../../scripts/agent_loop.py)의 claude/codex
lane `elapsed`는 `_emit_progress`로만 흘렀다). 어떤 lane이 상대적으로 느린지, 반복적으로
실패하는지에 대한 **가시성이 영속되지 않아** 운영자가 effort 노브(claude `--effort`,
codex `-c model_reasoning_effort`)를 수동 조정할 근거가 없었다. deep-dive trace가 찾은 진짜
갭은 동시성이 아니라 **lane 병목 가시성**이다.

codex CLI는 `-c model_reasoning_effort=<level>`을 받고(`~/.codex/config.toml`이 `xhigh`까지
사용 확인), claude CLI는 `--effort`를 받는다. 즉 두 주 병렬 표면 모두 effort actuation이
원리적으로 가능하다. 다만 actuation은 진동(oscillation)·비용·order-correctness(codex `-c`
삽입 위치) 리스크가 있어 **측정/감지와 분리**해야 한다.

## Decision

`make 시작` active-auto-loop에 **opt-in** per-`(role,agent)` lane 적응형 effort autotune을
도입한다. 2-PR one-concern 분할:

- **PR1 (이 ADR 범위) — Sense + Detect, recommendation-only**:
  1. **새 측정 표면**: per-lane `elapsed_s`를 `ActiveCodexRunnerResult.sessions`로 흘리고
     (`item["elapsed_s"]`), iteration 경계에서 `auto_loop_state.json`의 `cycles[].lane_stats`
     로 영속. 신규 sibling 로더 `_load_active_lane_stats(state_path) -> (list, dict)` — 기존
     `_load_active_auto_ledger`(3-tuple, 단일 unpack 호출처)는 시그니처 불변.
  2. **순수 컨트롤러** `compute_lane_autotune(prior_lane_stats, config) -> (recommendations, events)`
     (cooldown_state 인자 없음): **within-agent** `elapsed_s > K × median(같은 agent active lane)`
     (K 기본 2.0) flag + per-lane `(role,agent)` `fail_rate` 윈도우(W 기본 3, min-sample 2) +
     agent-flip 시 lane 윈도우 reset + 같은 agent active lane < 2면 no-op. I/O·env·clock 없음.
  3. **recommendation 기록**: 병목 lane + 권고 방향(fail_rate>임계 → strengthen / 아니면
     accelerate)을 `auto_loop_state.json`의 `lane_autotune_recommendations`로 기록. **effort
     actuation 없음.**
- **PR2 (후속 issue, stacked) — Actuate**: `_resolve_lane_effort_override` threading
  (claude `--effort` / codex `-c model_reasoning_effort`, positional `-` 이전 삽입) +
  per-agent effort ladder clamp + **cooldown** 강제. PR2가 컨트롤러를 cooldown_state
  시그니처로 확장.

**Default OFF == byte-identical**: `ACTIVE_LANE_AUTOTUNE` 미설정 시 컨트롤러는 호출되지
않고, per-lane `elapsed_s`·`lane_stats`·recommendations 어느 것도 영속되지 않는다. 산출
codex 명령(`-c model_reasoning_effort` 미주입)과 `auto_loop_state.json` 페이로드가 오늘과
바이트 동일하다.

## Drivers

1. **runner 산출물 byte-identical (ADR 0087(d) non-load-bearing)** — 기본 경로 무변경. 모든
   신규 분기는 `ACTIVE_LANE_AUTOTUNE` gate 안. *(ADR 0001 baseline이 아니라 0087(d)에
   re-anchor.)*
2. **테스트 가능성** — 컨트롤러가 순수 함수라 실 spawn 없이 결정론적 단위 테스트.
3. **재사용 / SSoT** — 신규 sidecar 파일 0; 기존 `auto_loop_state.json` 단일 출처 재사용.
   PR2 effort threading은 `_resolve_lane_model_override` 패턴 미러링.

## Alternatives considered

- **컨트롤러를 항상 호출 + 무조건 측정 영속.** 기각: off-mode에서 `auto_loop_state.json` /
  runner 상태 파일이 바뀌어 byte-identical 불변식 위반. 측정조차 gate 안으로.
- **`_load_active_auto_ledger` 확장(lane_stats 추가).** 기각: 3-tuple 반환을 단일 호출처가
  3개로 unpack — 시그니처 변경은 회귀 위험. 별도 sibling 로더로.
- **sidecar 파일(per-lane timing 별도 저장).** 기각: `auto_loop_state.json`이 이미 cycle
  체크포인트의 단일 출처. 신규 파일은 SSoT 분산.
- **`os.environ` 변이로 effort 주입(PR2).** 기각: 멀티-worktree 누수 + 컨트롤러 순수성 파괴.
  PR2는 param threading(Option A).
- **claude-only effort (codex는 effort 불가 오판).** 기각: codex `-c model_reasoning_effort`로
  주 병렬 표면도 actuate 가능(PR2).
- **PR1에 cooldown 포함.** 기각: cooldown(재조정 억제)은 actuation이 있어야 의미. PR1은
  lane-stats 윈도우만 관리하고 agent-flip 시 reset; cooldown_state set/decrement는 PR2 신설.

## Consequences

- opt-in 시 per-lane timing이 `auto_loop_state.json`에 영속(새 reviewer 계약 — `lane_stats`,
  `lane_autotune_recommendations` 키). off 시 byte-identical.
- omc runner([ADR 0087](./0087-opt-in-omc-team-parallel-runner.md))는 단일 worker·per-lane
  timing 부재 → autotune은 codex runner 한정, omc 시 컨트롤러는 자연히 no-op(`lane_stats`
  비어있음).
- claude `elapsed_s`는 artifact/heartbeat 오버헤드 포함, codex는 순수 subprocess wait →
  **교차-agent 비교 불가**. 컨트롤러는 within-agent median만 사용.
- codex effort 상한(`xhigh` vs `max`)은 PR2 빌드 smoke로 확정.

## Deferred / follow-up

- **effort actuation (PR2 — landed).** claude `--effort` / codex `-c model_reasoning_effort`
  threading (positional `-` 이전 삽입) + per-agent ladder clamp + cooldown. controller가
  `compute_lane_autotune(prior_lane_stats, cooldown_state, config) ->
  (effort_overrides, recommendations, new_cooldown_state, events)`로 확장됨. codex effort 가드는
  controller ladder-clamp 단독(`_validate_effort_for_model`은 claude lane 전용 — 오인용 금지).
- **codex `xhigh` rung.** controller 사다리는 `high` 상한; `~/.codex/config.toml`이 `xhigh`를
  쓰더라도 PR2 사다리는 `high`까지만 → 필요 시 후속 검토.
- **model-swap actuation.** blast radius·비용 가드 필요 → deferred.
- **cross-agent 정규화 비교.** claude 오버헤드 보정 후 교차 비교 → 별도 측정 작업.
- **claude `max` rung.** 코드 profile 상한이 `xhigh`라 `max`는 제외(코드 부재); 필요 시 smoke
  (`claude --effort max`) 후 추가.

## Verification

```bash
python3 -m pytest -q tests/test_agent_loop.py -k 'autotune or lane_effort or active_runner or lane_stats'
python3 scripts/_governance.py --check-adr-readme-parity docs/adr/0092-lane-adaptive-autotune.md
git diff --check
```

<!-- verifies-key: scripts/agent_loop.py:compute_lane_autotune -->
<!-- verifies-key: scripts/agent_loop.py:_load_active_lane_stats -->
<!-- verifies-key: scripts/agent_loop.py:LaneAutotuneConfig -->
<!-- verifies-key: scripts/agent_loop.py:LANE_AUTOTUNE_ENV -->
<!-- verifies-key: scripts/agent_loop.py:_lane_autotune_enabled -->
<!-- verifies-key: scripts/agent_loop.py:_resolve_lane_autotune_config -->
<!-- verifies-key: scripts/agent_loop.py:_resolve_lane_autotune_config_for_cli -->
<!-- verifies-key: scripts/agent_loop.py:_LANE_AUTOTUNE_FAILURE_STATUSES -->
<!-- verifies-key: scripts/agent_loop.py:_resolve_lane_effort_override -->
<!-- verifies-key: scripts/agent_loop.py:_step_lane_effort -->
<!-- verifies-key: Makefile:ACTIVE_LANE_AUTOTUNE -->
