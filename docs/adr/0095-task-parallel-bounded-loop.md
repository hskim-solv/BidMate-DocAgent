# 0095: task-level 병렬 bounded 루프 (X) + omc multi-worker (Y) default-on

- Status: accepted
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

XYZ 병렬화를 도입한다. **X 는 PR-E2~E3c 에서 default-dark(기본 X=1)로 dark 착륙한 뒤 PR-F(#1948)에서
기본을 X=2 로 flip 했다 — 현재 기본 = X=2 병렬**(X=1 직렬·ADR 0001 byte-identical 경로는
`ACTIVE_TASK_POOL=1` / `BIDMATE_AGENT_LOOP_TASK_POOL=1` / kill-switch override 로 유지). **Y 는
default-on(omc path 한정)**. 단일 전역 budget M 은 [ADR 0094](./0094-concurrency-substrate-for-parallel-loop.md) 에서
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
- **X (task pool) DEFAULT X=2 (go-live)**: 루프 body 를 `run_one_task` 로 refactor 하고
  `ThreadPoolExecutor` + locked `claim_next_task`(다음 task 선택을 atomic 하게)로 묶는다. race-free
  completed-count, convergent stop(#1719 teardown 재사용), per-task artifact namespacing(동시 task
  의 `patch_artifact.json` 충돌 방지)을 구현한다. **기본 X=1 으로 dark 착륙**(PR-E2~E3c) 후 substrate +
  테스트가 안정화되어, **PR-F(#1948)에서 기본을 X=2 로 flip 했다(현재 기본 = X=2 병렬)**. X=1(직렬,
  ADR 0001 byte-identical 경로)은 `ACTIVE_TASK_POOL=1` / `BIDMATE_AGENT_LOOP_TASK_POOL=1` 또는
  kill-switch(`BIDMATE_AGENT_LOOP_PARALLELISM_KILL=1`)로 여전히 사용 가능하다.
  - **X>1 시작 가드 — HEAD≠origin/main demote(PR-F, codex round-3 Option B + round-4 exact parity)**:
    X>1 cycle worktree 는 `origin/main` 에서 fork 하고 parent 의 **DIRTY(uncommitted) 파일만** seed
    하므로, cycle tree 가 parent checkout 과 일치하는 건 **HEAD == origin/main(정확히 같은 commit)** 일
    때 뿐이다. 어느 방향으로든 어긋나면 cycle 이 X=1(parent repo 직접 실행)과 다른 tree 에서 돈다: HEAD 가
    **앞서면** committed-but-unpushed 작업이 cycle 에서 안 보이고(round-3, data-loss 방향), origin/main 이
    **앞서면** cycle 이 operator 가 checkout 한 것보다 새 코드에서 fork 돼 stale HEAD 가 origin/main tip
    으로 fan-out 된다(round-4, stale-base 방향). 따라서 driver 시작 시 `_head_matches_origin_main(repo_root)`
    (= `rev-parse HEAD` 와 `rev-parse origin/main` commit id 비교)로 1회 확인하고, 같지 않으면 X 를 1 로
    **강등(demote)** 하고 경고를 emit 한다 — cycle 코드 가시성을 항상 X=1 과 일치시킨다. **ancestor 검사로는
    round-4 를 못 잡는다**(HEAD 가 더 새 origin/main 의 ancestor 이지만 tree 는 다름) → commit id 등치 비교.
    fcntl clamp 와 같은 **correctness 가드**라 명시적 knob 값에도 적용된다(선호가 아님). FAIL-SAFE: 어느 ref
    든 미해결이면 `_git_ref` 가 None → False → 강등(검증 불가한 base 로 cycle 실행 금지). within-run task
    commit 은 X>1 에서도 안전(lease 가 claimed-file disjoint 강제) — PRE-RUN checkout 상태만 위험하므로 시작
    시점 1회 검사로 충분. HEAD 를 origin/main 으로 sync(push/merge 또는 pull) 하면 X>1 재활성화.
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
   리스크를 default-off 로 격리). substrate 가 검증되기 전에 X 를 기본 켜지 않았고, 검증·테스트
   안정화 후 PR-F(#1948)에서 기본을 X=2 로 flip 했다.
2. **Y default-on, omc-only** — maintainer 가 omc multi-worker 를 기본 동작으로 원한다. 이미
   ack-gated 된 omc 경로에 한정하므로 기본 codex 경로 byte-identical 이 보존된다(ADR 0001).
3. **재사용 / SSoT** — [ADR 0094](./0094-concurrency-substrate-for-parallel-loop.md) substrate +
   issue #1719 confinement primitive + 기존 active-apply/gate 라우팅(ADR 0087) 재사용.

## Alternatives considered

- **X 를 처음부터 default-on.** 기각: Plan + codex 가 dark-first 를 권고. substrate + 동시성
  테스트가 안정화되기 전 X 기본 활성은 폭주(runaway) 리스크. 안정화 후 PR-F(#1948)에서 X=2 로 flip 했다.
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
  **PR-E2(#1816) 의 worktree-per-task isolation** 으로 한다 — E1 의 per-file `standard_path`/
  `task_slug` fence 가 아니라 **cycle 의 `repo_root` 경계**에서 닫는다(아래 PR-E2 항목). E1 의
  redaction `task_slug` substrate 는 merged 인 채로 유지하되(다른 concern), E2 의 worktree 전략은
  그것을 wiring 하지 않는다(unused-but-intact).
- **PR-E2(#1816) 착륙 — SHRUNK scope: X=1 byte-identical driver + 추출 primitives + worktree lifecycle (DARK)**:
  codex round-1 BLOCK(slug-scope → repo_root 전략 재설계) + round-2 SHRINK(two-root split 은 write만
  절반 wiring — read/acquire/release/overlap 미완 → 깨끗한 E3 경계가 낫다) 2라운드 검토 후 확정된 최소
  범위. **E2 delivers**:
  - **(a) X=1 byte-identical driver**: `ThreadPoolExecutor(1)` + claim→submit→`future.result()`→next claim
    = 정확한 pre-E2 직렬 순서. effective pool 은 `_e2_task_pool_dark_clamp_enabled()` 로 1 로 clamp
    (PR-E3 에서 이 함수+호출 제거); `_resolve_task_pool_size` / `--task-pool` / Makefile 브리지 / fcntl
    gating / kill-switch 함께 착륙. per-task wall-clock budget 은 `effective_task_pool_size > 1` 일 때만
    resolve — X==1 에서 env 무시 → byte-identical (Finding 5).
  - **(b) cycle body extraction**: `claim_next_task`(leaf `threading.Lock`, select+append 감싸고
    `write_active_start`/semaphore **전에** release) + `run_one_task`(cycle body verbatim move;
    `break`→`stop_event.set()+return`, `continue`→`return`) + `run_task_in_worktree`(X==1→직접
    `run_one_task`; X>1→E3-deferred `RuntimeError` — 코드에 E3 work-list 문서화).
  - **(c) stop_event fail-closed** (Finding 1, general correctness — X==1 에서도 bounded-blocker 시
    작동): `complete_if_not_stopped(task_id)` 헬퍼가 ALL 3 terminal completion site (local-gate /
    ship / repair-applied)를 guard. X==1 에서는 event 가 mid-cycle set 되지 않아 항상 True → byte-identical.
  - **(d) worktree lifecycle primitive** (Finding 4 seed-failure teardown 포함): `_task_cycle_worktree_
    _paths` / `create_task_cycle_worktree` / `teardown_task_cycle_worktree` / `_run_cycle_in_task_worktree`
    — 모듈레벨, injected git runner 로 모든 exit path(seed failure/blocker/exception/stop/budget)
    teardown 단위 테스트 완료. PR-E3 가 이 primitive 를 `run_task_in_worktree` X>1 분기에 wire.
    `try/finally` 를 `create` 직후(seed **전**)로 이동해 seed 예외도 teardown 보장 (Finding 4).
  **X>1 는 PR-E2 에서 명시적으로 deferred** — `run_task_in_worktree` X>1 분기는 `RuntimeError` 로
  E3 work-list 를 문서화(코드 경계 가시화); E2-dark clamp 로 runtime unreachable.
  - **PR-E3 work-list** (codex round-2 HIGH findings): leases coordination_root — `write_active_loop`/
    `write_active_start` 의 write 뿐 아니라 **`_load_active_leases`(read) + `acquire_active_agent`/
    `release_active_agent`(acquire/release) + `build_overlap_preflight`(overlap-preflight)** 전부
    coordination_root(parent) 를 사용해야 cross-task lease overlap 이 가시적. 추가: cycle worktree 의
    parent branch/issue inheritance(origin/main 기반 생성, 현재 branch tied issue 미전파), `run_one_task`/
    `run_repair_apply` 에 `cycle_repo_root`+`coordination_root` two explicit root threading, `claim_disjoint`
    first-writer-wins REJECT(현재 REPORT-only). `_e2_task_pool_dark_clamp_enabled` 제거.
  - **Open question**: `claim_disjoint` REPORT-only — E2-dark 에서는 disjointness 가 task selection
    (`select_next_task` 이 `attempted_this_run` 제외)에서 나와 문제없음. E3 가 first-writer-wins 결정.

## Resolution

- **PR-F(#1948) go-live**: `DEFAULT_ACTIVE_TASK_POOL` 을 1 → 2 로 flip 해 X-병렬 bounded-loop 실행을
  기본값으로 켰다 — 이로써 X=1 기본 경로의 byte-identity(dark-brick 불변)는 **의도적으로 종료**된다
  (Makefile `ACTIVE_TASK_POOL` 기본값도 2 로 동반 flip). X=1(직렬, ADR 0001 byte-identical)은
  `ACTIVE_TASK_POOL=1` / kill-switch 로 여전히 사용 가능하고, 그 byte-identity 회귀는
  `test_active_auto_loop_x1_byte_identical`(양 arm 모두 `task_pool=1` 고정)이 계속 지킨다.
- **End-to-end X>1 증거**: 이전 X>1 driver 테스트는 전부 `_run_cycle_in_task_worktree` 를 stub 했기에
  REAL worktree create→seed→confine→mirror→teardown 체인이 2-task fan-out 하에서 한 번도 실행되지
  않았다. PR-F 의 신규 테스트 **`test_x_gt_1_full_driver_real_worktree_e2e`** 가 그 공백을 닫는다 —
  REAL git tmp repo + `task_pool=2` 로 실제 `agent/<id>/cycle` worktree 2개를 만들고(codex/gate +
  GitHub-side read 만 fake, 실제 PR side effect 없음), (a) 두 task 의 convergent 완료, (b) 각 task
  artifact 의 parent 미러링 + teardown 생존, (c) disjoint cycle branch 생성→정리, (d) ledger
  무충돌 reconcile, (e) mirror-failure warning 부재(silent partial-mirror 가 성공으로 통과 못함)를
  증거로 단언한다. ADR 0094 동시성 substrate 는 이미 accepted 다.
- **Go-live 정합성 수정(codex+architect 2026-06-04 adversarial 리뷰)**: flip 시점의 pre-commit
  codex 8-pass 리뷰가 X=2 기본화로 새로 노출되는 2건을 제기했고, architect tie-breaker 가 코드로
  판정했다. (1) **REACHABLE** — `_active_task_context_files` 가 모든 task claim set 에
  `tasks/queue.md` 를 prepend 하는데 `assert_claimed_files_disjoint` 의 context-only 제외가
  whole-set 단위라, 서로 다른 real 파일을 만지는 두 task 가 queue.md 로 false-overlap → reject →
  X>1 이 조용히 serial 로 강등됐다. **per-file 제외(`_is_context_only_path`)로 수정**
  (`test_disjoint_mixed_claim_compares_real_files_only` + `_still_blocks_real_file_conflict`).
  (2) **NOT REACHABLE** — cross-process cycle-worktree 삭제는 teardown 의 `worktree remove` 가
  호출자 `repo_root` 로 path-scoped + git 이 타 worktree 에 checked-out 된 branch 의 `-D` 를
  거부하므로 불가하며, 암묵적이던 이 불변식을 `test_teardown_cannot_delete_branch_checked_out_elsewhere`
  (real git 2-worktree)로 고정했다.
- **Go-live 정합성 수정 2차(codex+architect 2026-06-04, 2~3라운드)**: flip 을 staging 한 뒤
  pre-commit codex 리뷰가 X=2 기본화 고유의 **회복·격리 공백 2건(둘 다 REACHABLE)** 을 더 표면화했고,
  주목할 점은 **그 1차 수정 자체가 다음 라운드에서 불완전으로 판정**되어 2번 다듬은 것이다(“각 라운드가
  새 X>1 gap 을 드러낸다”의 자기예시). (A) **create-failure teardown 이 preserved/sibling cycle
  worktree 를 삭제** — 직전 X>1 run 이 artifact 미러링에 실패하면 `.claude/worktrees/<task>-cycle` 을
  의도적으로 보존하는데, 같은 root 의 다음 run 이 기존 경로에서 create 실패 후 그 worktree 를
  teardown → fail-closed 회복 상태가 데이터 손실로 전환. 1차 수정(create 직전 `cycle_path_preexisted`
  캡처 후 pre-existing 일 때만 보존)은 **probe→add TOCTOU race** 가 남았다(probe 시 부재여도 sibling 이
  add 직전 생성 가능 → 여전히 sibling worktree 삭제). 그래서 **create 실패 시 무조건 teardown 하지 않고
  보존 + recovery blocker** 로 정정(`git worktree prune` 로 out-of-band GC; 소유권 증명 불가하므로
  unconditional). `test_worktree_lifecycle_create_failure_fails_closed_and_preserves`(path 부재) +
  `test_worktree_lifecycle_preexisting_cycle_path_is_preserved_not_torn_down`(보존 artifact 생존)으로
  핀. r1-(2) 의 cross-process 삭제(NOT REACHABLE)와 달리 이건 **same-root 재시도** 경로라 도달 가능.
  (B) **cycle seed 가 unscoped** — X>1 cycle 이 `seed_scratch_worktree_from_parent` 를 `include_paths`
  없이 호출해 parent 의 모든 dirty 파일을 각 cycle 로 복사 → X=2 에서 무관한 두 task(+로컬/staged 편집)가
  서로의 미커밋 상태 상속, claimed-file disjointness 무의미화. 1차 수정(seed 를
  `_active_task_context_files(task)` 로만 한정)은 **claim footprint 의 `requested_files`(=changed_files)를
  누락**해 task 가 자기 in-flight 작업을 못 보는 과도 축소였다. 그래서 claim 과 **동일한 footprint**
  (`requested_files` + context files)를 쓰는 `_cycle_seed_include_paths` 헬퍼를 추출해 `run_one_task`
  의 claim 계산(`context_files`)을 미러링하도록 정정(`None` 은 legacy copy-all 보존). 회귀:
  `test_cycle_seed_include_paths_includes_changed_files`(changed_files-only 경로 포함) +
  `test_worktree_lifecycle_seed_is_scoped_to_task_include_paths`(forwarding) + 필터 자체는 기존
  `test_seed_scratch_worktree_from_parent_can_limit_to_claimed_files`. go-live flip 의 blast radius 가
  dark-brick 들이 X=1 에서 잠재워 둔 latent X>1 isolation/recovery gap 들을 활성화함을 보여준다.
  (2차에서 informational·freq 1/8 로 남겼던 "cycle 이 `origin/main` base 라 committed-but-unpushed
  parent-branch state 미상속"은 3차에서 blocking 으로 escalate → Option B 로 해소, 아래.)
- **Go-live 정합성 수정 3·4차(codex 2026-06-04, Option B + exact parity)**: 2차에서 informational
  (freq 1/8)로 남겼던 origin/main-base 미상속이 X=2 기본 flip 의 blast-radius 하에서 3차에 **freq
  4/8·2/8 high 로 escalate**(go-live 시 cycle 이 stale tree 에서 실행될 위험). codex 권고는 (a) cycle 을
  parent HEAD/branch 기준으로 생성, 또는 (b) branch-local commit 감지 시 X=1 로 강등 + 경고였고, **사용자가
  (b) Option B 를 선택**했다(E3b 격리 설계 유지 + 최소 변경). **3차 1차 구현**은 `_git_is_ancestor("HEAD",
  "origin/main")` 즉 "HEAD 가 origin/main 을 벗어나는가"(HEAD-ahead) 만 검사했는데, **4차 리뷰가 그
  ancestor 검사의 반대 방향 공백을 freq 3/8 high 로 표면화**: origin/main 이 HEAD 보다 **앞서면**(로컬
  stale) HEAD 는 새 origin/main 의 ancestor 라 검사를 통과하지만 cycle 은 더 새 코드에서 fork → stale HEAD
  fan-out. **최종 구현**: `_head_matches_origin_main(repo_root)`(= `rev-parse HEAD` 와 `rev-parse
  origin/main` commit id 등치; 기존 `_git_ref` 재사용)로 **정확한 parity** 검사 → 양방향(ahead/behind/
  diverged) 모두 강등. `write_active_auto_loop` 시작 가드(fcntl clamp 와 동격 correctness 가드 — 명시적
  knob 값에도 적용; FAIL-SAFE: 어느 ref 든 미해결 → None → 강등). 회귀 4종:
  `test_head_matches_origin_main_true_only_when_exactly_equal`(real git: equal→True / HEAD-ahead→False
  [round-3 sentinel] / origin/main-ahead→False [round-4; ancestor 검사는 통과함을 같은 테스트에서 대조]),
  `test_head_matches_origin_main_false_when_origin_main_unresolved`(fail-safe),
  `test_x_gt_1_demotes_to_serial_when_head_ahead_of_origin_main`(real git: HEAD ahead + task_pool=2 →
  강등 경고 + cycle 0개 + 각 task 가 committed sentinel parent tree 에서 실행),
  `test_x_gt_1_demotes_to_serial_when_origin_main_ahead_of_head`(real git: origin/main ahead +
  task_pool=2 → 강등 경고 + cycle 0개; behind checkout 은 기존 stale-base overlap-preflight 가 runner
  전에 추가로 block = defense-in-depth). dispatch 테스트의 X>1 precondition 은 `_patch_active_loop_clear`
  가 `_head_matches_origin_main→True` 로 명시 greenlight 한다(이전엔 faked subprocess 에 암묵 의존).
  round-3 freq-1/8 MEDIUM("Accepted ADR 가 여전히 X=dark serial 이라 기술")은 Decision lead 를 X=2 기본·
  X=1 serial override 로 재작성해 해소.

## Verification

```bash
python3 -m pytest -q tests/test_agent_loop.py -k 'task_pool or omc_multi or global_concurrency or convergent or e2e or lifecycle or origin_main'
python3 -m pytest -q tests/test_agent_loop_worktree_confinement.py -k 'disjoint or teardown'
python3 scripts/_governance.py --check-adr-readme-parity docs/adr/0095-task-parallel-bounded-loop.md
git diff --check
```

<!-- verifies-key: scripts/agent_loop.py:write_active_auto_loop -->
<!-- verifies-key: scripts/agent_loop.py:_resolve_omc_worker_mix -->
<!-- verifies-key: scripts/agent_loop.py:loop_should_continue -->
<!-- verifies-key: scripts/agent_loop.py:_run_omc_team_runner -->
<!-- verifies-key: scripts/agent_loop.py:_head_matches_origin_main -->
