# 0095: task-level 병렬 bounded 루프 (X) + omc multi-worker (Y) default-on

- Status: proposed
- Date: 2026-06-02
- Deciders: User, Claude Code
- Related: [ADR 0094](./0094-concurrency-substrate-for-parallel-loop.md) (동시성 안전 substrate — 본 ADR 의 전제), [ADR 0087](./0087-opt-in-omc-team-parallel-runner.md) (opt-in omc 병렬 runner / single-worker pin), [ADR 0085](./0085-infinite-mode-active-auto-loop.md) (무한 모드 + 안전 가드 SEMANTICS), [ADR 0083](./0083-local-gate-completion-and-real100-v2-judge-egress.md) (`make 시작` local-gate completion / EXECUTE_SHIP=0), [ADR 0001](./0001-preserve-naive-baseline.md) (baseline byte-identical 보존), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (private 데이터 경계), [ADR 0061](./0061-external-and-paid-api-dependencies-allowed.md) (외부/유료 API opt-in 3조건)
- Issue: #1762

## Context

maintainer 는 `make 시작`(active-auto-loop, [`scripts/agent_loop.py`](../../scripts/agent_loop.py))
의 직렬(serialize-only) 처리를 X×Y×Z 3-level 병렬화로 확장하기로 결정했다 — X = task-level
pool(서로 다른 queue task N개 동시), Y = per-task omc multi-worker, Z = intra-task role
parallelism(이미 존재하는 `spawn_and_wait`). 본 ADR 은 [ADR 0094](./0094-concurrency-substrate-for-parallel-loop.md)
의 동시성 안전 substrate(atomic-write + `LeaseManager.claim_disjoint` + 전역 `BoundedSemaphore`)에
**의존**한다 — substrate 가 먼저 착륙해야 X 를 안전하게 켤 수 있다(3자 YELLOW 합의의 핵심).

바뀌는 두 가지: (1) `_resolve_omc_worker_mix` 의 single-worker 핀(`total_workers = 1` +
`assert ... == 1`, [ADR 0087](./0087-opt-in-omc-team-parallel-runner.md))과 (2) 직렬 루프 body
(`write_active_auto_loop` 가 task 를 한 개씩 처리하는 순차 wave). Z 는 이미 존재하므로 throttle
만 [ADR 0094](./0094-concurrency-substrate-for-parallel-loop.md) 의 전역 M 으로 받는다.

## Decision

XYZ 병렬화를 도입하되 **X 는 default-dark(기본 X=1)**, **Y 는 default-on(omc path 한정)** 으로
착륙시킨다. 단일 전역 budget M 은 [ADR 0094](./0094-concurrency-substrate-for-parallel-loop.md) 에서
온다. `EXECUTE_SHIP=0`(ADR 0083) human-gated ship 은 불변이다.

- **Y (omc multi-worker) default-on**: `_resolve_omc_worker_mix` 의 `total_workers=1` 핀 +
  `assert ... == 1` 을 제거한다. worker 수는 agent_mix 정책에서 도출하되 `OMC_MAX_WORKERS`(기본
  ≤3) ∧ M 으로 clamp 한다. [ADR 0087](./0087-opt-in-omc-team-parallel-runner.md) 이 미룬
  **multi-worker per-worker diff 캡처** 를 빌드하되 **NO auto-merge** 를 유지한다(캡처된 diff 는
  privacy 재감사 + scope 재부과 + 기존 active-apply / Conservative Gate / human-gated ship 으로만
  라우팅 — main 미머지). 이미 ack-gated 된 `runner=omc` 경로에 **한정** 되므로 기본 `make 시작`
  (codex runner)은 영향받지 않는다. omc 의 단일 기존 ack(`ACTIVE_OMC_RUNNER_ACK=1`)은 maintainer
  결정에 따라 **N-fold egress 에 대한 consent** 로 수용한다.
- **X (task pool) DEFAULT X=1 (dark)**: 루프 body 를 `run_one_task` 로 refactor 하고
  `ThreadPoolExecutor` + locked `claim_next_task`(다음 task 선택을 atomic 하게)로 묶는다. race-free
  completed-count, convergent stop(#1719 teardown 재사용), per-task artifact namespacing(동시 task
  의 `patch_artifact.json` 충돌 방지)을 구현한다. **기본 X=1 으로 dark 착륙** 하고, substrate +
  테스트 안정화 후 별도 PR(PR-F)에서 X=2 로 flip 한다.
- **단일 전역 M**: [ADR 0094](./0094-concurrency-substrate-for-parallel-loop.md) 의
  `BoundedSemaphore(M)`(기본 8)를 모든 CLI spawn 이 acquire — X·Y·Z 곱셈 폭증 방지.

**[ADR 0087](./0087-opt-in-omc-team-parallel-runner.md) 의 single-worker pin 을 부분 supersede 한다**:
0087 의 거버넌스/ack 기계(데이터-경계 ack fail-closed, no-auto-merge, privacy 재감사, scope
재부과, gate 라우팅)는 **그대로 유지** 되고, 오직 **worker-count 결정**(`total_workers=1` 강제)만
번복된다.

**[ADR 0085](./0085-infinite-mode-active-auto-loop.md) 의 직렬 루프가 *암묵적으로* 의존하던 단일
ledger writer 안전성(0085 가 명시한 결정이 아니라 직렬 설계의 ambient 불변식)을
[ADR 0094](./0094-concurrency-substrate-for-parallel-loop.md) 의 명시적 locking 계약으로 대체한다**: 0085 의 가드 **SEMANTICS**(연속-blocker, wall-clock, exit-code)는
**보존** 되며 concurrency 용으로 재표현된다 — 특히 consecutive-blocker 를 "blockers since last
completion(마지막 완료 이후 누적된 blocker)" 으로 재정의한다.

`scripts/agent_loop.py` 는 본 단계에서도 `LOAD_BEARING_PATHS` 에 올리지 않는다(ADR 0080/0085/0087
계승) — task-level 병렬은 retrieval/verifier/answer/eval 런타임을 건드리지 않는다.

## Drivers

1. **X dark-first** — Plan + codex 가 "X 는 dark 로 착륙, 안정화 후 flip" 을 권고했다(폭주
   리스크를 default-off 로 격리). substrate 가 검증되기 전에 X 를 기본 켜지 않는다.
2. **Y default-on, omc-only** — maintainer 가 omc multi-worker 를 기본 동작으로 원한다. 이미
   ack-gated 된 omc 경로에 한정하므로 기본 codex 경로 byte-identical 이 보존된다(ADR 0001).
3. **재사용 / SSoT** — [ADR 0094](./0094-concurrency-substrate-for-parallel-loop.md) substrate +
   issue #1719 confinement primitive + 기존 active-apply/gate 라우팅(ADR 0087) 재사용.

## Alternatives considered

- **X 를 처음부터 default-on.** 기각: Plan + codex 가 dark-first 를 권고. substrate + 동시성
  테스트가 안정화되기 전 X 기본 활성은 폭주(runaway) 리스크. PR-F 에서 flip.
- **Y 도 ack 뒤 opt-in 유지(default-off).** 기각: maintainer 가 명시적으로 default-on 을 결정.
  단 omc 경로 자체가 이미 `ACTIVE_OMC_RUNNER_ACK=1` 로 gated 이므로 기본 codex 경로는 불변.
- **per-task runner 선택(task 별 codex/omc/claude 라우팅).** 기각/연기: post-v1 deferred. v1 은
  단일 runner 정책 + Y(omc) 다중화에 집중.
- **독립 cap(X·Y·Z 각각).** 기각: [ADR 0094](./0094-concurrency-substrate-for-parallel-loop.md) 의
  단일 전역 M 으로 곱셈 폭증을 막는다.

## Consequences

- omc multi-worker 의 외부 egress 증폭은 best-effort 로 `OMC_MAX_WORKERS`(기본 ≤3) ∧ M 에 의해
  bounded 된다 — out-of-process worker 라 hard enforce 는 불가하며, 그 한계는 기존 ADR 0087 ack
  gate 와 ADR 0005/0061 데이터-경계가 보완한다(N-fold egress 는 ack consent 로 수용).
- 가드-semantics 변경이 문서화된다 — consecutive-blocker 가 "since last completion" 으로 재정의
  되고, wall-clock 은 per-task budget 으로 재표현된다. exit-code 가드 SEMANTICS 는 보존.
- redaction-scan per-task scoping 이 요구된다 — `_redact_active_*` glob 이 동시 task 를 교차
  스캔하지 않도록 PR-E 전에 trace + scoping 필요(미해결 시 PR-E 보류).
- guard trip 하에서 completed-set 이 비결정적(nondeterministic)일 수 있다 → count 기반 정확 일치
  대신 invariant-based 테스트로 검증한다.
- `EXECUTE_SHIP=0`(ADR 0083) 불변, X=1/M=8 byte-identical(ADR 0001), `agent_loop.py`
  `LOAD_BEARING_PATHS` 비승격 유지.

## Verification

```bash
python3 -m pytest -q tests/test_agent_loop.py -k 'task_pool or omc_multi or global_concurrency or convergent'
python3 scripts/_governance.py --check-adr-readme-parity docs/adr/0095-task-parallel-bounded-loop.md
git diff --check
```

<!-- verifies-key: scripts/agent_loop.py:write_active_auto_loop -->
<!-- verifies-key: scripts/agent_loop.py:_resolve_omc_worker_mix -->
<!-- verifies-key: scripts/agent_loop.py:loop_should_continue -->
<!-- verifies-key: scripts/agent_loop.py:_run_omc_team_runner -->
