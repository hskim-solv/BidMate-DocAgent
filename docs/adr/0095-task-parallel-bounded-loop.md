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
  `assert ... == 1` 을 제거한다(PR-D, #1804). worker 수는 agent_mix 정책에서 도출하되
  `OMC_MAX_WORKERS`(기본 ≤3) ∧ M 으로 clamp 한다. **explicit `--read-agent claude`/`codex` override 는
  single lane 유지**(`auto` 만 fan-out). [ADR 0087](./0087-opt-in-omc-team-parallel-runner.md) 이 미룬
  **multi-worker per-worker diff 캡처** 를 빌드하되 **NO auto-merge** 를 유지한다(캡처된 diff 는
  privacy 재감사 + scope 재부과 + 기존 active-apply / Conservative Gate / human-gated ship 으로만
  라우팅 — main 미머지).
  - **per-worker 캡처 + fail-closed 집계**: 각 worker 의 worktree 에서 merge-base→`git add -A`→
    `git diff --cached`(ADR 0087 round-6/8/10 fix 시퀀스)로 diff 를 캡처해
    `omc_runs/omc-team/worker-{idx}/patch_artifact.json` namespace 에 privacy+scope 재감사 후 기록한다.
    어느 worker 라도 (a) merge-base 실패, (b) `add -A` 실패, (c) diff 실패, (d) privacy 위반,
    (e) scope 위반 시 **전체 run blocked**(부분 성공 허용 금지; blocker 에 worker idx 기록).
  - **정본(canonical) 정책**: **N==1 + 전 검사 통과** 는 표준 active-apply 경로
    (`patch_runs/implementer/patch_artifact.json`)에 proposed 기록 — [ADR 0087](./0087-opt-in-omc-team-parallel-runner.md)
    single-worker 동작과 **byte-identical**(worker-N namespace 미생성). **N>1 + 전 검사 통과** 는 표준
    경로를 **"needs human selection" blocked artifact** 로 라우팅(active-apply 자동 소비 차단)하고
    per-worker namespace 에 각 proposed 를 보존한다 — human 이 수동으로 하나를 표준 경로로 승격한다.
    **자동 승격(auto-promotion)은 PR-D non-goal**(캡처 + 안전 라우팅까지만).
  - **OMC_MAX_WORKERS ∧ M 은 best-effort cap**: `omc team` 은 단일 out-of-process subprocess 라
    전역 semaphore(M)는 그 launch 에 **1 permit 만** 부과한다 — out-of-process omc worker 수를 in-process
    semaphore 가 hard-enforce 하지 못한다. `OMC_MAX_WORKERS` 는 runner 가 요청하는 mix_spec worker
    총수의 best-effort cap 이며, 잔여 N-fold egress 는 ack(`ACTIVE_OMC_RUNNER_ACK=1`)가 수용한다.
  이미 ack-gated 된 `runner=omc` 경로에 **한정** 되므로 기본 `make 시작`(codex runner)은 영향받지 않는다.
  omc 의 단일 기존 ack(`ACTIVE_OMC_RUNNER_ACK=1`)은 maintainer 결정에 따라 **N-fold egress 에 대한
  consent** 로 수용한다. 전역 kill-switch `BIDMATE_AGENT_LOOP_PARALLELISM_KILL=1` 는 PR-D 에서
  omc-scope 로 도입되어(`_resolve_omc_worker_mix`를 single worker 로 강등) 켜질 때 multi-worker 를
  즉시 직렬 강등한다; X-task-pool 강등은 PR-E.
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
- **per-worker 캡처 + fail-closed(PR-D, #1804)**: 각 worker diff 가 자체 worktree 에서 캡처되어
  worker 별 privacy+scope 재감사를 통과해야만 per-worker artifact 로 이어진다. 어느 worker 라도
  실패 시 전체 run 이 blocked 되어(부분 성공 없음) 한 worker 의 누출/범위이탈이 다른 worker 의
  proposed 와 함께 active-apply 로 새지 않는다.
- **정본 라우팅(PR-D)**: N==1 + 전 검사 통과는 ADR 0087 single-worker 경로와 byte-identical 하게
  표준 active-apply 경로에 proposed 를 기록한다(worker-N namespace 미생성). N>1 + 전 검사 통과는
  표준 경로가 "needs human selection" blocked artifact 가 되어 active-apply 자동 소비가 차단되고,
  per-worker proposed 는 보존된다. **자동 승격은 의도적 non-goal** — human 이 정확히 하나를 표준
  경로로 승격한다(NO auto-merge 불변).
- **kill-switch omc-scope(PR-D)**: `BIDMATE_AGENT_LOOP_PARALLELISM_KILL=1` 가 `_resolve_omc_worker_mix`
  를 single worker(`auto`→majority lane 1; explicit override 존중)로 강등한다 — 코드 revert 없이
  multi-worker 를 즉시 끈다. X-task-pool 강등은 PR-E 에서 같은 env 로 확장된다.
- **stale worker-* 증거 격리(PR-D, codex round-2/3 fix)**: stale `worker-{idx}/patch_artifact.json`
  eviction 은 `_run_omc_team_runner` **함수 초입**(`execute=True` 가드)에서 모든 pre-launch
  early-return 앞에 실행된다(이전에는 team-launch 직전에 위치해 no-ack / task-scope /
  assignment / privacy pre-launch blocked early-return 이 eviction 을 우회했다). `execute=False`
  (dry-run)는 round-9 fix #2 read-only 불변에 따라 제외. **eviction 실패는 warning-only 가 아니라
  fail-closed**: `rmtree` 실패 시 stale artifact 를 in-place blocked 로 overwrite(blocked 는
  apply-ineligible); overwrite 도 실패하면 run 을 blocked early-return(blocker 에 "fail-closed" 기록).
- 가드-semantics 변경이 문서화된다 — consecutive-blocker 가 "since last completion" 으로 재정의
  되고, wall-clock 은 per-task budget 으로 재표현된다. exit-code 가드 SEMANTICS 는 보존.
- redaction-scan per-task scoping 이 요구된다 — `_redact_active_*` glob 이 동시 task 를 교차
  스캔하지 않도록 PR-E 전에 trace + scoping 필요(미해결 시 PR-E 보류). **PR-E1(#1817)에서
  착륙**: `_redact_active_codex_runs`/`_redact_active_patch_runs` 에 `task_slug` 인자를 추가해
  scan 을 `<active>/codex_runs|patch_runs/<slug>` subtree 로 좁히고, `expected` 가드를 "표준 경로
  OR 그 직계 task-scoped 자식" 으로 확장한다(pre-E1 의 bare `runs != expected` 동치 검사는
  task-scoped 경로를 *조용히 스킵* → private 데이터 누출의 가장 미묘한 함정이었다). `task_slug`
  은 영숫자+`-_` 만 허용한다(`_sanitize_task_slug`) — `.`·`/` 를 포함한 그 외 문자는 모두
  **제거**되므로 `.`/`..`/traversal 토큰이 애초에 살아남을 수 없고(charset 자체가 방어),
  남는 글자가 없으면 `None` 을 반환한다. 미지정(`task_slug=None`) 시 표준 경로로 fallback
  하되, **task-scoped intent(`task_slug is not None`)인데 sanitize 결과가 `None`(unsafe)이면
  표준 경로를 스캔하지 않고 `0` 을 반환(fail-closed)** — task-scoped 모드에서 표준 스캔으로
  fallback 하면 실제 per-task subtree 를 건너뛰어 누출이 되기 때문(E1 기본 = byte-identical,
  E2 가 slug 주입해 활성).
- guard trip 하에서 completed-set 이 비결정적(nondeterministic)일 수 있다 → count 기반 정확 일치
  대신 invariant-based 테스트로 검증한다.
- `EXECUTE_SHIP=0`(ADR 0083) 불변, X=1/M=8 byte-identical(ADR 0001), `agent_loop.py`
  `LOAD_BEARING_PATHS` 비승격 유지.
- **pre-existing: `agent_loop` privacy redaction 이 `reports/real100/` 만 매치하고
  `real100_v2*` 를 포함하지 않는다.** PR-D diff 밖(pre-existing) — 별도 follow-up issue 로 추적 권장.
- **PR-D 한정 알려진 미결: artifact race + teardown-중 permit 조기 release(X=1 dark라 무해).**
  `_finalize_omc_runner_result`(artifact write + heartbeat invalidation)와 teardown(shutdown)이
  `global_concurrency_limiter().slot()` **밖**에서 실행된다. 모든 omc run 이 공유하는 단일 표준
  경로(`patch_runs/implementer/patch_artifact.json`)가 있기 때문에 X>1 동시 omc run에서 artifact
  last-writer-wins race 가 발생하고, teardown 진입 시점에 이미 permit 이 반환된 상태다. PR-D 는
  X=1 dark 이므로 동시 omc run 이 없어 무해하다. **이 race 는 slot/fence 가 아니라 PR-E2 의
  per-task disjoint `standard_path` 로 닫힌다** — semaphore 는 capacity throttle 이지 publication
  mutex 가 아니다(아래 PR-E1 항목). PR-E1 은 그 `standard_path` 파라미터화 substrate 만 깐다.
- **PR-E1(#1817)에서 `standard_path` substrate 착륙 — HIGH-4 는 slot/fence 로 닫지 않는다**:
  PR-E 가 2-PR 로 분할된다(E1=path/privacy substrate, E2=#1816 X task pool). E1 은 **오직**
  표준 active-apply 경로를 `_finalize_omc_runner_result` 의 `standard_path` 인자로
  parametrize 하고(4개의 하드코딩 재계산 제거 — late-blocker overwrite 포함), per-task
  run-root helper(`_omc_task_run_root`)와 task-scoped redaction scoping(`task_slug`)을 도입한다.
  **HIGH-4 의 X>1 publication race 를 slot/semaphore fence 로 닫지 않는다**:
  `global_concurrency_limiter()` 는 `BoundedSemaphore(M)` **capacity throttle** 일 뿐
  **publication mutex 가 아니다** — M=1 이어도 teardown gap 이 launch/capture 순서와 publication
  순서를 분리하고, M>1 이면 두 sibling run 이 둘 다 permit 을 쥔 채 같은 `standard_path` 를
  last-writer-wins clobber 한다(slot 은 exclusion 을 제공하지 못한다). legacy 공유 경로에 flock 을
  거는 것도 같은 이유로 last-writer-wins data loss 를 못 막고 partial-write tearing 만 막으며,
  E2 가 path 를 disjoint 로 만들면 redundant 가 된다. 따라서 E1 의 finalize 는 **어떤 slot 으로도
  감싸지 않는다**(launch slot 은 ADR 0094 의 정당한 spawn throttle 로 유지). **E1 기본값
  (standard_path 미지정, task_slug=None)은 기존 경로 계산식과 textually identical → X=1
  byte-identical(ADR 0001); X=1 은 dark 라 동시 publication 자체가 없다**. HIGH-4 의 실제 fix 는
  **PR-E2** 가 E1 substrate 의 task_slug 를 per-task **disjoint `standard_path`** 로 wiring +
  **M>1 동시 publication 회귀 테스트**(서로 다른 path 로 publish → 충돌 없음 증명)로 닫는다
  (X-enable 은 PR-F 전제).

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
