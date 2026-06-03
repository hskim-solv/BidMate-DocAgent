# Plan: T-2026-0074 XYZ parallelism stack — 3-level 병렬화(X task-pool × Y omc multi-worker × Z roles) + 동시성 안전 substrate

- Status: proposed
- Owner role: Planner
- Related task: `tasks/queue.md::T-2026-0074`
- Related issue / PR: #1762
- Related ADR: [ADR 0094](../adr/0094-concurrency-substrate-for-parallel-loop.md) (동시성 안전 substrate), [ADR 0095](../adr/0095-task-parallel-bounded-loop.md) (task-level 병렬 X + omc multi-worker Y)
- Created: 2026-06-02
- Last updated: 2026-06-02

## Problem Statement

`시작omc` / `make 시작` bounded-completion autonomous loop([`scripts/agent_loop.py`](../../scripts/agent_loop.py))는
현재 ready-queue 를 **직렬(serialize-only)** 로 한 task 씩 처리한다. 유지보수자(maintainer)는
처리량(throughput) 증대를 위해 X×Y×Z 3-level 병렬화를 원한다 — X = task-level pool(서로 다른
queue task N개 동시), Y = per-task omc multi-worker(worker 다중화, ADR 0087 이 현재 1로 핀고정),
Z = intra-task role parallelism(이미 존재하는 `spawn_and_wait`).

reviewer-visible / 운영자-visible 결과: 순진한(naive) 병렬화는 루프가 공유하는 단일 상태
(shared singleton)를 **손상(corrupt)** 시킨다. Plan 설계 패스 + 독립 codex 리뷰 + Claude
3자가 모두 **YELLOW** 로 수렴했다 — 표준 concurrency engineering 으로 sound 하지만,
**transactional per-task state substrate 가 먼저 착륙(land FIRST)해야 한다**. codex 의 가장
날카로운 지적: `leases.json` 은 이름만 lease(lease in name only) 다 — `write_active_start` /
`acquire_active_agent` / `release_active_agent` / `assert_claimed_files_disjoint` 전반에
snapshot-load + full-file rewrite 가 일어나는데 **atomic section 이 전혀 없다**. 마찬가지로
`auto_loop_state.json` ledger 쓰기(`write_cycle_checkpoint`, terminal write)는 lock 없는
full-file `write_text` 이라 동시성 하에서 last-writer-wins(마지막 writer 가 이김)다. 또한
Z role-parallelism 은 현재 throttle 되지 않는다(`--max-parallel` 은 semaphore 가 아니라 guard
일 뿐).

이 plan 이 수행되지 않으면: 병렬을 켜는 순간 ledger 의 완료 사실(completed/deferred fact)이
유실되고, lease 의 disjoint 보증(claimed-files 겹침 방지)이 TOCTOU race 로 깨지며, ship/artifact
경로가 서로 덮어쓴다.

## Current Behavior

새 세션이 재발견(rediscovery) 없이 재개할 수 있도록 현재 구현을 기술한다. 관련 파일은
[`scripts/agent_loop.py`](../../scripts/agent_loop.py)(20,113 lines, `LOAD_BEARING_PATHS` 밖,
autonomy core).

- **직렬 루프**: `write_active_auto_loop` 가 ready task 를 한 개씩 선택 → 처리 → ledger 기록의
  순차 wave 를 돈다. 동시 task 진입점이 없다.
- **lock 없는 ledger 쓰기**: `write_cycle_checkpoint`(cycle 체크포인트) + terminal write 가
  `auto_loop_state.json` 을 unlocked full-file `write_text` 로 쓴다. 동시 쓰기 시 last-writer-wins
  → completed/deferred/cycles/blockers count 유실(lost update).
- **lease singleton, atomic section 부재**: `leases.json` / `session_registry.json` 이
  snapshot-load → 메모리 변형 → full-file rewrite 패턴이다. `write_active_start`(lease 생성),
  `acquire_active_agent` / `release_active_agent`(active_agent borrow/return),
  `assert_claimed_files_disjoint`(claimed-files 겹침 검사)가 **read→check→write 를 하나의 atomic
  critical section 으로 묶지 않는다** → snapshot TOCTOU(검사 시점과 쓰기 시점 사이 다른 writer
  개입).
- **`_resolve_omc_worker_mix` 1-worker 핀**: 총 worker 수를 항상 `total_workers = 1` 로 강제하고
  `assert ... == 1` 로 잠근다(ADR 0087 의 single-worker pin). multi-worker diff 캡처는 ADR 0087
  이 명시적으로 follow-up 으로 미뤘다.
- **Z `spawn_and_wait` batch launch**: 한 task 내 role lane 전체 배치를 띄운다. `--max-parallel`
  은 선택된 session count ≤ max-parallel 만 검증하는 **guard-only** 이고, 실제 동시 실행을
  제한하는 semaphore 가 아니다(ADR 0087 이 in-repo `--max-parallel` 을 "가짜 동시성" 으로 정정).
- **per-task artifact singleton**: `patch_artifact.json`(+ run-specific `artifact_path`)이 task
  당 단일 경로다. 동시 task 가 같은 경로를 덮어쓴다(ship/artifact race).
- **bounded guard 는 infinite-only**: 연속-blocker(consecutive-blocker) / wall-clock 가드는
  ADR 0085 가 무한 모드(`START_INFINITE=1`) 한정으로 도입했다. bounded 5-task 기본은 이 가드를
  타지 않는다.
- **ship 무실행**: Makefile `시작` target 은 `EXECUTE_SHIP=0`(ADR 0083) — 루프는 main 에 머지하지
  않고 human-gated ship 경로로만 라우팅한다.

## Desired Behavior

관찰 가능한(observable) 최소 유효 종단 상태:

- **transactional per-task state**: ledger / lease / artifact 쓰기가 atomic 하게 직렬화되어
  동시성 하에서도 completed fact / disjoint 보증 / artifact 가 유실·충돌하지 않는다.
- **단일 전역 concurrency budget M**: X×Y×Z 가 **곱(multiply)** 으로 폭증하지 않도록 모든 CLI
  spawn 이 하나의 전역 `BoundedSemaphore(M)` 를 acquire 한다(기본 M=8). X·Y·Z 각각의 독립 cap 이
  아니라 단일 천장.
- **X default-dark**: task pool 은 기본 X=1(직렬과 동일 동작)로 착륙하고, substrate + 테스트가
  안정화된 뒤(PR-F) X=2 로 flip.
- **Y default-on**(omc path 한정): `_resolve_omc_worker_mix` 의 1-worker 핀을 제거해 omc runner
  에서 multi-worker 가 기본 동작. 단 `runner=omc` 는 이미 ack-gated 이므로 기본 `make 시작`(codex)
  경로는 불변.
- **byte-identical default**: X=1 / M=8 기본에서 산출 codex 명령 + `auto_loop_state.json`
  페이로드 + lease 파일이 오늘과 바이트 동일(ADR 0001 gate).

## Constraints

- **Scope constraints**: PR-0(이 plan) 은 design-of-record + decision record + queue entry 만.
  `agent_loop.py` 코드 변경 0. 7-PR 시퀀스는 Task Breakdown 참조.
- **Architecture constraints**: `agent_loop.py` 는 `LOAD_BEARING_PATHS` 밖 유지(ADR 0080/0085/0086/0087
  결정 계승). substrate 는 in-process shared-memory lock(`threading.Lock` / `BoundedSemaphore`) +
  POSIX file lock(`fcntl.flock`) 조합.
- **Compatibility constraints**: ADR 0083 `EXECUTE_SHIP=0` human-gated ship 불변. ADR 0001
  byte-identical default(X=1/M=8). ADR 0085 가드 SEMANTICS(연속-blocker / wall-clock / exit-code)
  보존, concurrency 용으로 재표현.
- **Eval/privacy constraints**: ADR 0005(private 데이터 경계) / ADR 0061(외부·paid API opt-in
  3조건) 보존. omc multi-worker 의 out-of-process egress 증폭은 best-effort cap(`OMC_MAX_WORKERS`).
  no real-eval impact(docs-only PR-0; 후속 PR 도 RAG runtime 미변경).
- **Tooling/CI constraints**: issue #1719 의 worktree confinement primitive 재사용(per-task
  teardown / scope 재부과). fcntl POSIX-only → 비-POSIX CI 는 atomic-rename only 로 degrade.
- **Non-goals**: per-task runner 선택(task 별 codex/omc/claude 라우팅)은 post-v1. main 자동
  머지·force-push 영구 금지. 무한 모드 + 병렬 조합의 정밀 튜닝은 별도.

## Architecture Impact

- **Affected modules or docs**: [`scripts/agent_loop.py`](../../scripts/agent_loop.py)(전 단계),
  `Makefile`(`시작` target env), [`docs/operations/active-agent-loop.md`](../operations/active-agent-loop.md)
  (PR-F runbook), [`docs/adr/0094`](../adr/0094-concurrency-substrate-for-parallel-loop.md) /
  [`0095`](../adr/0095-task-parallel-bounded-loop.md).
- **Affected contracts or invariants**: 신규 reviewer 계약 3종 — atomic-write helper(temp +
  `os.replace` + `fcntl.flock`), `LeaseManager.claim_disjoint`(단일 flock critical section),
  전역 `BoundedSemaphore(M)`. `auto_loop_state.json` 페이로드는 X=1/M=8 에서 불변.
- **Load-bearing paths**: `agent_loop.py` 는 SSoT [`scripts/_governance.py`](../../scripts/_governance.py)
  의 `LOAD_BEARING_PATHS` 에 **올리지 않는다**(retrieval/verifier/answer/eval 런타임 미변경).
- **ADR required**: yes — 새 동시성 substrate(atomic write / lease manager / semaphore)는
  reviewer 가 의존할 계약을 고정하므로 ADR 0094. task-level 병렬 + worker-pin 번복은 ADR 0095
  (ADR 0087/0085 부분 supersede/replace).
- **Backward compatibility expectation**: 기본 경로(X=1, M=8, codex runner) byte-identical.
  병렬은 전부 opt-in 분기 또는 default-dark.

## Affected Interfaces

- **CLI/API/config**: `active-auto-loop` argparse 신규 노브(X pool 크기 / 전역 M) — 기본값은
  Makefile front door SSoT 와 통일(ADR 0085 패턴). env `BIDMATE_AGENT_LOOP_GLOBAL_CONCURRENCY`
  (M) / `OMC_MAX_WORKERS`(Y cap) / 전역 kill-switch `BIDMATE_AGENT_LOOP_PARALLELISM_KILL=1`.
  Makefile `ACTIVE_GLOBAL_CONCURRENCY`.
- **Input data**: ready-queue(`tasks/queue.md` 파생 registry session) — 변경 없음.
- **Output artifacts**: `auto_loop_state.json`(ledger) / `leases.json` / `session_registry.json` /
  `patch_artifact.json`. PR-E 에서 per-task artifact namespacing 도입(동시 task 충돌 방지).
- **Docs/review surfaces**: PR-F 에서 runbook + ADR Accepted 전환.
- **Tests/eval entrypoints**: `tests/test_agent_loop.py`(`-k 'ledger or lease or atomic or
  concurrency or task_pool or omc_multi or global_concurrency or convergent'`). RAG eval 미변경.

## Data / Eval Impact

- **Surface**: none(docs-only PR-0). 후속 구현 PR 도 RAG eval 표면 미변경 — `agent_loop.py` 는
  retrieval/verifier/answer/eval 런타임 밖.
- **Data boundary**: no data touched(PR-0). omc multi-worker(Y)의 외부 egress 증폭은 ADR 0005/0061
  관할, `OMC_MAX_WORKERS` best-effort cap + 기존 ack gate(ADR 0087) 계승.
- **Allowed claim**: "throughput 병렬화 substrate + decision record 추가", "X=1/M=8 byte-identical".
- **Disallowed claim**: real-eval 수치 변화 / retrieval·answer 품질 변화 주장(이 epic 은 운영
  처리량 layer 이지 RAG 품질 layer 가 아님).
- **Baseline or control affected**: no — ADR 0001 baseline byte-identical(naive_baseline 미경유).
- **Benchmark/eval auditor required**: no(docs + 운영 루프 layer; RAG eval 무관).

## Task Breakdown

7-PR phased 시퀀스(A1 → A2 → B → C → D → E → F). substrate(A1~C)가 X(E) 보다 먼저 착륙.

1. **PR-A1 — atomic-write primitives** ([`scripts/agent_loop.py`](../../scripts/agent_loop.py)):
   temp file + `os.replace` + `fcntl.flock`(POSIX, import guard) helper 를 2개 ledger write site
   (`write_cycle_checkpoint`, terminal write) + `_write_active_leases` 에 적용. 비-POSIX 는
   atomic-rename only 로 degrade. 동작 무변경(직렬), 쓰기 단위만 atomic.
2. **PR-A2 — `LedgerState` single serialized writer**: completed / deferred / cycles / blockers /
   consecutive_blockers 를 in-process `threading.Lock` 뒤의 단일 직렬 writer 로 모은다. ledger 는
   append-only fact 이므로 single-writer = zero lost-update(N-way RMW-under-lock 불필요).
3. **PR-B — `LeaseManager.claim_disjoint`**: read → disjoint-check → write 를 **하나의**
   `flock(LOCK_EX)` critical section 으로 묶어 `assert_claimed_files_disjoint` 의 snapshot TOCTOU
   를 닫는다. `acquire_active_agent` / `release_active_agent` 를 같은 lock 아래로 retrofit.
4. **PR-C — global budget M** (`BoundedSemaphore`): 기본 M=8, env
   `BIDMATE_AGENT_LOOP_GLOBAL_CONCURRENCY` / Makefile `ACTIVE_GLOBAL_CONCURRENCY`. 모든 CLI spawn
   (claude write / codex patch / read-review / omc)이 acquire. fail-closed: M<=0 → 1.
   X×Y×Z 가 곱으로 폭증하지 않는 단일 천장.
5. **PR-D — Y default-on omc multi-worker**: `_resolve_omc_worker_mix` 의 `total_workers=1` 핀 +
   `assert ... == 1` 제거. worker 수는 agent_mix 정책에서 도출하되 `OMC_MAX_WORKERS`(기본 ≤3)
   ∧ M 으로 clamp. ADR 0087 이 미룬 per-worker diff 캡처를 빌드하되 **NO auto-merge** 유지.
   `runner=omc`(이미 ack-gated) 경로 한정 → 기본 `make 시작`(codex) 불변.
6. **PR-E — X task pool**(DEFAULT X=1 dark): 루프 body 를 `run_one_task` 로 refactor →
   `ThreadPoolExecutor` + locked `claim_next_task`. race-free completed-count, consecutive-blocker
   를 "since-last-completion(마지막 완료 이후 blocker)" 로 재정의, per-task wall-clock budget,
   convergent stop(#1719 teardown 재사용), per-task artifact namespacing(redaction-scan scoping
   포함). 기본 X=1 으로 dark 착륙.
   - **2-PR 분할 — E1(#1817 path/privacy substrate) / E2(#1816 X task pool)**: privacy(누출
     방지)와 throughput(동시 task) concern 을 분리하고 **gating-first**(누출 가드를 X 도입
     *전에* 착륙)로 진행한다. **E1**(이 단계) = redaction-scan per-task scoping + expected-가드
     확장 + `_finalize_omc_runner_result` `standard_path` 인자화 + per-task run-root helper +
     slug sanitize 계약(alnum+`-`+`_`, task-scoped fail-closed) — 모두 X=1 byte-identical
     인프라(ADR 0001), X>1 은 미도입. **E1 은 HIGH-4 를 slot/fence 로 닫지 않는다**:
     `global_concurrency_limiter()` 는 BoundedSemaphore(M) capacity throttle 일 뿐 publication
     mutex 가 아니므로(두 sibling run 이 둘 다 permit 을 쥔 채 같은 `standard_path` 를
     last-writer-wins) fence 로 쓰면 안 된다 — E1 은 오직 `standard_path` 파라미터화 substrate 만
     깐다(X=1 은 dark 라 동시 publication 자체가 없음).
   - **E2/E3 재분할 (codex BLOCK 후, worktree-per-task isolation 으로 재설계)**: 첫 E2 시도가
     producer artifact 경로(`patch_runs/<slug>`)만 scoping 하고 `active/` 의 coordination+apply+gate
     표면 전체를 singleton 으로 남겨 X>1 race 를 닫지 못한다는 codex BLOCK 을 받았다. slug 별 per-file
     fence 를 더 늘리는 대신, **각 task cycle 의 `repo_root` 를 per-task git worktree 로** 바꾼다 —
     그러면 `active/` 의 모든 경로(registry/assignments/events/apply/gate/patch_runs/codex_runs/
     omc_runs)가 worktree-local 이라 **construction 으로 disjoint** → HIGH-1..4 를 per-file 이 아니라
     **repo_root 경계에서** 닫는다. PARENT repo 에는 `leases.json`(PR-B flock) + `auto_loop_state.json`
     ledger(PR-A2)만 남고 driver 가 future join **후** 완료를 기록 → ledger merge 없음.
     - **E2(#1816) — isolation substrate + structure DARK, X=1 byte-identical (이 단계)**:
       `write_active_auto_loop` body 를 leaf-lock `claim_next_task`(in-process `threading.Lock`,
       flock 아님; select+append 만 감싸고 `write_active_start`/semaphore acquire **전에** release) +
       `run_one_task` closure(cycle body verbatim move; `break`→`stop_event.set()`+return / `continue`→
       return) + `run_task_in_worktree`/모듈레벨 `_run_cycle_in_task_worktree`(X=1→worktree 없이
       `repo_root=ROOT_DIR`, byte-identical; X>1→create+seed+confine+commit-before-exit+teardown 을
       try/finally 로 **모든 exit(blocker/exception/stop/budget)** 에서 teardown; write-lane spawn 전
       `assert_worktree_confinement` fail-closed; worktree create CLI spawn 은
       `global_concurrency_limiter().slot()` 1 permit) + `ThreadPoolExecutor` driver(X=1 직렬 path =
       claim→submit→`future.result()`→next claim = pre-E2 순서 → byte-identical) 로 refactor.
       **substrate 만 DARK** — knob>1 이어도 effective pool 을 1 로 clamp(advisory warning). MUST FIX:
       stop_event in-flight fail-closed(terminal blocker 후 in-flight sibling promote 금지 + driver
       pending cancel + bounded post-stop join no-promote). fcntl gating + per-task wall-clock budget
       (default 0 = no-op) + kill-switch + convergent stop 구현. 기존 `_scratch_worktree_paths`(write-lane
       scratch, `{task_id}-{agent}`)와 충돌 피하려 cycle worktree 는 `{task_id}-cycle` naming.
       `create_scratch_worktree`/`seed_scratch_worktree_from_parent`/`assert_worktree_confinement`/
       `commit_scratch_worktree_before_exit`/`teardown_scratch_worktree` git 메커닉 재사용(injected runner).
     - **E3 — X>1 fan-out enable + ledger/lease reconciliation**: E2 의 effective-pool clamp 를 제거하고
       `ThreadPoolExecutor(N)` + `FIRST_COMPLETED` drain 으로 실제 동시 cycle 을 돌린다. driver 가 per-cycle
       `repo_root` 를 인자로 전달(nonlocal rebinding 제거 → siblings 가 root 공유 안 함). `leases.json`
       `claim_disjoint` 의 first-writer-wins **rejection** 결정(현재 REPORT-only). X>1 disjoint-active-surface
       + M>1 publication 회귀 테스트가 여기 산다(E2 에서는 clamp 때문에 불가).
7. **PR-F — flip-on(X=2) + ADR Accepted + runbook**: X 기본을 2 로 올리고 ADR 0094/0095 를
   proposed → accepted 로 전환, [`docs/operations/active-agent-loop.md`](../operations/active-agent-loop.md)
   에 운영 runbook 추가.

## Acceptance Criteria

- [ ] PR-0: [`docs/plans/xyz-parallelism-stack.md`](xyz-parallelism-stack.md) + ADR 0094 + ADR 0095
      (둘 다 Proposed) + README index rows + queue T-2026-0074 row 가 모든 governance check 를
      통과(`--check-adr-collision` / `--lint-adr-consequences` ×2 / `--check-adr-readme-parity` /
      `--check-adr-readme-status` / `--check-adr-crossref` / `git diff --check`).
- [ ] **ADR 0001 gate**: X=1 / M=8 기본에서 산출 codex 명령 + `auto_loop_state.json` 페이로드가
      byte-identical 임을 증명하는 회귀 테스트(PR-A1~PR-E 각 단계).
- [ ] atomic-write / `LeaseManager.claim_disjoint` / 전역 semaphore 가 fake + barrier 기반
      결정론 동시성 테스트로 검증된다(실 spawn 없이).
- [ ] consecutive-blocker / wall-clock / exit-code 가드 SEMANTICS 가 concurrency 하에서도 보존
      (재표현된 invariant-based 테스트).
- [ ] 전역 kill-switch `BIDMATE_AGENT_LOOP_PARALLELISM_KILL=1` 가 모든 병렬 분기를 직렬로 강등.

## Validation Strategy

Commands that must be run:

```bash
# PR-0 governance (docs-only):
python3 scripts/_governance.py --check-adr-collision
python3 scripts/_governance.py --lint-adr-consequences docs/adr/0094-concurrency-substrate-for-parallel-loop.md
python3 scripts/_governance.py --lint-adr-consequences docs/adr/0095-task-parallel-bounded-loop.md
python3 scripts/_governance.py --check-adr-readme-parity docs/adr/0094-concurrency-substrate-for-parallel-loop.md docs/adr/0095-task-parallel-bounded-loop.md
python3 scripts/_governance.py --check-adr-readme-status
python3 scripts/_governance.py --check-adr-crossref
git diff --check

# 후속 구현 PR (A1~F) 별:
python3 -m pytest -q tests/test_agent_loop.py -k 'ledger or lease or atomic or concurrency or task_pool or omc_multi or global_concurrency or convergent'
python3 -m py_compile scripts/agent_loop.py
```

Expected evidence:

- Test/eval output: 동시성 테스트(fake + barrier) green; byte-identical 회귀 테스트 green.
- Generated or updated artifact: PR-0 = plan + ADR 0094/0095 + README rows + queue row(런타임
  artifact 변화 없음).
- Reviewer checklist or manual inspection: atomic-write / claim_disjoint / semaphore 계약 3종을
  [`docs/reviews/ai-review-checklists.md`](../reviews/ai-review-checklists.md) regression 패스로 검토.
- Explicitly not validated, with reason: real-eval 수치 — `agent_loop.py` 는 RAG eval 런타임 밖,
  이 epic 은 운영 처리량 layer.

## Rollback Strategy

각 구현 PR 은 default-dark 또는 byte-identical default 로 착륙하므로 revert 가 안전하다. X 는
PR-E 에서 기본 1 → PR-F 에서 2 로 flip 하므로, 회귀 시 X=1 으로 되돌리면 직렬 동작 복원.
전역 kill-switch `BIDMATE_AGENT_LOOP_PARALLELISM_KILL=1` 가 코드 revert 없이 즉시 직렬 강등 경로
제공. `auto_loop_state.json` / `leases.json` 은 운영 상태 파일이므로 rollback 중 삭제 금지
(in-flight task 상태 유실 방지) — 직렬 모드로 자연 소진(drain)시킨다.

## Failure Modes

- **Failure mode**: omc out-of-process egress 증폭(Y multi-worker 가 N-fold 외부 egress).
  - Detection signal: omc worker 수 × 외부 호출. Stop condition or fallback: `OMC_MAX_WORKERS`
    (기본 ≤3) best-effort cap + 기존 ADR 0087 ack gate; cap 은 best-effort(out-of-process 라
    hard enforce 불가)임을 명시.
- **Failure mode**: redaction-scan cross-task interference — `_redact_active_*` glob 이 동시 task
  의 파일을 교차 스캔.
  - Detection signal: per-task redaction scope 누수. Stop condition or fallback: **PR-E 전에
    `_redact_active_*` glob 을 반드시 trace** 해 per-task scoping 으로 좁힌다(미해결 시 PR-E 보류).
- **Failure mode**: guard-semantics shift — concurrency 하에서 consecutive-blocker / wall-clock
  의미가 바뀜.
  - Detection signal: completed-set 비결정성(guard trip 시). Stop condition or fallback:
    consecutive-blocker 를 "since-last-completion" 으로 재정의 + invariant-based 테스트.
- **Failure mode**: fcntl portability — 비-POSIX 환경에서 `fcntl` import 실패.
  - Detection signal: ImportError. Stop condition or fallback: import guard → atomic-rename only
    로 degrade(파일 교체는 여전히 atomic, in-process lock 은 `threading.Lock` 이 담당).
- **Failure mode**: two-lock + semaphore deadlock(ledger lock × lease lock × semaphore).
  - Detection signal: hang. Stop condition or fallback: **strict lock ordering**(semaphore 를
    lock 바깥에서 acquire) + bounded acquire timeout.
- **Failure mode (PR-D 해소됨): stale worker-* artifacts from prior N>1 run — false human promotion**.
  `_run_omc_team_runner` 의 stale eviction 이 team-launch 직전에 위치하면 no-ack / task-scope /
  pre-launch blocked early-return 이 eviction 을 우회해 prior run 의 proposed `worker-{idx}/
  patch_artifact.json` 이 disk 에 잔존 — human 이 오래된 proposed 를 promote 할 수 있다. 해소:
  eviction 을 **함수 초입(`execute=True` 가드)**으로 이동해 모든 early-return 앞에 실행. dry-run
  (`execute=False`)은 round-9 fix #2 read-only 불변으로 제외.
- **HIGH-4 (X>1-only artifact publication race; X=1 dark 동안 무해) — PR-D / E1 / E2 분할**.
  `_finalize_omc_runner_result`(artifact write + heartbeat invalidation)와 teardown(shutdown)이
  `global_concurrency_limiter().slot()` 밖에서 실행된다. 모든 omc run 이 공유하는 단일 표준
  경로(`patch_runs/implementer/patch_artifact.json`)에서 X>1 동시 omc run 시 last-writer-wins
  race 가 발생한다.
  - **PR-D**: 이 race 를 만들지만 X=1 dark(동시 omc run 0개)라 **무해**.
  - **PR-E1**(이 단계): `standard_path` **파라미터화 substrate** 만 깐다 — slot/fence 가
    **아니다**. semaphore 는 capacity throttle 이지 publication mutex 가 아니므로(M=1 이어도
    teardown gap 이 launch/capture 순서와 publication 순서를 분리, M>1 이면 두 run 이 동시에
    permit 을 쥔 채 같은 path 를 clobber) fence 로 쓰면 last-writer-wins data loss 를 못 막고
    partial-write tearing 만 막는다. legacy 공유 경로에 flock 을 거는 것도 같은 이유로 오답이며,
    E2 가 path 를 disjoint 로 만들면 redundant 가 된다. X=1 byte-identical(ADR 0001).
  - **PR-E2(#1816) SHRUNK** (codex round-1 BLOCK + round-2 SHRINK 후 확정): X=1 byte-identical
    ThreadPoolExecutor driver + `claim_next_task`/`run_one_task` extraction + `complete_if_not_stopped`
    fail-closed(ALL 3 terminal sites) + worktree lifecycle primitive (Finding 4 seed teardown 포함) +
    `_e2_task_pool_dark_clamp_enabled` patch-point + Finding 5 budget X>1-only. X>1 분기는
    `RuntimeError`(E3 work-list 코드 문서화)로 명시 deferred; `_run_cycle_in_task_worktree` 단위 테스트
    완료. E1 redaction slug surface INTACT(unused).
  - **PR-E3 work-list** (codex round-2 HIGH 2개):
    - leases coordination_root **전 표면**: `write_active_loop`/`write_active_start` write + `_load_active_
      leases` read + `acquire_active_agent`/`release_active_agent` acquire/release + `build_overlap_preflight`
      overlap-preflight — 전부 coordination_root(parent)를 사용해야 cross-task lease overlap 가시.
    - cycle worktree parent **branch/issue inheritance**: origin/main 기반 생성, 현재 branch tied issue
      메타데이터 sibling task 에 미전파.
    - `run_one_task`/`run_repair_apply` two-root threading (`cycle_repo_root` + `coordination_root`).
    - `claim_disjoint` first-writer-wins **REJECT** (현재 REPORT-only).
    - `_e2_task_pool_dark_clamp_enabled` 제거 + effective X>1 fan-out 활성화.
    - X>1/M>1 disjoint-active-surface + publication 회귀 테스트.

## Observability

- `auto_loop_state.json` 의 cycle / completed / deferred / blocker count(ledger).
- `leases.json` / `session_registry.json` 의 lease 상태(claim_disjoint 결과).
- `tests/test_agent_loop.py` 동시성 + byte-identical 회귀 테스트 결과.
- governance check 출력(PR-0).
- 전역 kill-switch 활성 시 직렬 강등 로그.

## Reviewer Notes

reviewer 가 먼저 공격할 지점:

1. **claim wording**: real-eval 수치 변화를 주장하지 않음을 확인(이 epic 은 운영 처리량 layer).
2. **contract drift**: atomic-write / `LeaseManager.claim_disjoint` / 전역 semaphore 3계약이
   reviewer-checkable 한지(ADR 0094 verifies-key 마커가 기존 심볼을 가리키는지).
3. **baseline preservation**: X=1/M=8 byte-identical(ADR 0001). codex 명령 + ledger 페이로드 불변.
4. **data boundary**: Y omc multi-worker 의 egress 증폭이 ADR 0005/0061 + ack gate 안에 머무는지;
   `_redact_active_*` per-task scoping 이 PR-E 전에 trace 됐는지.
5. **rollback path**: kill-switch + X=1 강등이 즉시 직렬 복원하는지.
6. **missing tests**: 모든 동시성 경로가 fake + barrier 결정론 테스트로 덮였는지; guard-semantics
   재표현이 invariant-based 인지.

## Handoff Notes

Update this section at every session boundary or context compaction.

```markdown
## Session Handoff - 2026-06-02 (PR-0 scaffolding)

- Role: Planner (scaffolding) → Implementer/Reviewer (후속 PR-A1~F)
- Branch / worktree: `docs/issue-1762-xyz-parallel-scaffold` / `/Users/hskim/Desktop/projects/bidmate-wt/issue-1762-xyz-scaffold`
- Issue / PR: issue #1762 (PR-0 = 이 scaffolding PR)
- Task: `T-2026-0074` — XYZ parallelism epic PR-0 (design-of-record + ADR 0094/0095 Proposed + queue)
- Current status: PR-0 docs-only. `agent_loop.py` 코드 변경 0. 7-PR 시퀀스는 후속.
- Files touched: docs/plans/xyz-parallelism-stack.md(신규), docs/adr/0094·0095(신규), docs/adr/README.md(index 2행), tasks/queue.md(Order 74 1행).
- Decisions made: 3자 YELLOW 합의 = substrate-first. ADR 0094(substrate: atomic-write + LeaseManager + 전역 semaphore) → ADR 0095(X task-pool dark + Y omc multi-worker default-on, ADR 0087 worker-pin 부분 supersede / ADR 0085 single-writer 안전논거 replace).
- Commands run: governance check 6종 + git diff --check(PR-0 게이트).
- Results: PR-0 모든 governance check 통과 목표.
- Next safe command: PR-A1(atomic-write primitives) 구현 — temp + os.replace + fcntl.flock 를 write_cycle_checkpoint / terminal write / _write_active_leases 에 적용.
- Open questions: per-task runner 선택(post-v1 deferred); omc egress hard-cap 불가(best-effort).
- Risks: redaction-scan cross-task interference(PR-E 전 trace 필수); two-lock+semaphore deadlock(strict ordering + bounded timeout).
```

```markdown
## Session Handoff - 2026-06-03 (PR-E2 re-design: worktree-per-task isolation, X task pool DARK)

- Role: Implementer (E2 = brick 6/7, 재설계)
- Branch / worktree: `feat/issue-1816-x-task-pool` / `/Users/hskim/Desktop/projects/bidmate-wt/issue-1816-x-task-pool`
- Issue / PR: issue #1816 (E2 = X task pool; E1 #1817 이미 origin/main 머지)
- Task: `T-2026-0074` — XYZ parallelism epic E2 (X task pool substrate DARK, X=1 byte-identical)
- Current status: E2 RE-IMPLEMENTED + tested locally (Codex adversarial review + ship 은 orchestrator — implementer 커밋 안 함). X=1 default-dark, byte-identical.
- 재설계 이유: 첫 E2 시도(uncommitted, 이제 stash)가 producer artifact 경로(`patch_runs/<slug>`)만 scoping 하고 `active/` coordination+apply+gate 표면 전체를 singleton 으로 남겨 X>1 race → codex BLOCK. slug per-file fence 를 더 늘리는 대신 **cycle 의 `repo_root` 를 per-task worktree 로** 바꿔 `active/` 전 경로를 construction 으로 disjoint(HIGH-1..4 를 repo_root 경계에서 닫음).
- Files touched: scripts/agent_loop.py(`_resolve_task_pool_size`/constants/`--task-pool`/Makefile 브리지 + `claim_lock`/`claim_next_task` + `run_one_task`(cycle body verbatim move) + `run_task_in_worktree` + 모듈레벨 `_run_cycle_in_task_worktree` + `_task_cycle_worktree_paths`/`create_task_cycle_worktree`/`teardown_task_cycle_worktree` + `ThreadPoolExecutor` driver + stop_event fail-closed + fcntl gating + per-task budget + E2-dark clamp), tests/test_agent_loop.py(+16 tests), docs/plans(이 노트 + E2/E3 재분할), docs/adr/0095(PR-E2 worktree 항목 + leases-overlap open Q).
- Decisions made: (a) X=1 → worktree 없이 `repo_root=ROOT_DIR` (byte-identical; slug ternary 전무). (b) cycle worktree 는 `{task_id}-cycle` naming 으로 write-lane scratch(`{task_id}-{agent}`)와 disjoint. (c) 첫 E2 의 모든 slug path-injection RIP OUT(write_active_start/write_active_codex_runner/_run_omc_team_runner/_write_active_codex_patch/run_repair_apply/write_active_apply) — E1 redaction slug(`_redact_active_*`/`_sanitize_task_slug`/`_omc_task_run_root`)는 merged 라 INTACT(unused-but-kept). (d) E2 는 substrate DARK — effective pool 을 1 로 clamp(advisory warning), 실제 X>1 fan-out 은 E3. (e) worktree 라이프사이클을 모듈레벨 `_run_cycle_in_task_worktree` 로 추출해 injected git runner 로 모든 exit path(blocker/exception/stop/budget) teardown 을 단위 테스트. (f) DRIVER-ROOT != CYCLE-ROOT: driver ledger/state 는 PARENT ROOT_DIR, cycle 만 worktree root, future join 후 완료 기록 → ledger merge 없음. (g) stop_event fail-closed: terminal completion(local-gate-complete + ship) 전 `stop_event.is_set()` 체크 + driver pending cancel + bounded post-stop no-promote.
- Commands run: python3 -m py_compile scripts/agent_loop.py; pytest tests/test_agent_loop.py tests/test_global_concurrency_limiter_regression.py -q (398 passed); ruff check (clean); bash scripts/test.sh.
- Results: all green; X=1 byte-identical = `test_active_auto_loop_x1_byte_identical` + 기존 39 auto_loop 테스트.
- Next safe command: PR-E3 — effective-pool clamp 제거 + `FIRST_COMPLETED` drain + per-cycle repo_root 인자화 + `claim_disjoint` first-writer-wins rejection + X>1/M>1 disjoint-surface 회귀 테스트.
- Open questions: `leases.json` `claim_disjoint` 가 overlap REPORT-only(REJECT 는 E3); X>1 omc out-of-process worker egress 상호작용(best-effort cap, PR-D ack gate).
- Risks: X=1 dark 에서 신규 위험 없음. X>1 enable 은 E3 + disjoint-worktree + fcntl-clamp 가드 뒤.

## Session Handoff - 2026-06-03 (PR-E2 codex adversarial review 5 finding 수정)

- Role: Implementer (E2 review fix = 첫 구현의 5 finding patch)
- Branch / worktree: `feat/issue-1816-x-task-pool` / `/Users/hskim/Desktop/projects/bidmate-wt/issue-1816-x-task-pool`
- Task: E2 codex review (#1816-E2-review) — 5개 finding ALL CONFIRMED by maintainer, all fixed in same worktree; DO NOT commit (orchestrator re-runs codex after)
- Changes:
  - Finding 1 (HIGH): `complete_if_not_stopped(task_id)` 헬퍼 추가. repair-applied(3rd site) 포함 ALL 3 terminal completion site 를 헬퍼로 routing. `stop_event.is_set()` 시 False(no-op)/True(completed) 반환.
  - Finding 2+3 (HIGH): `nonlocal repo_root` + `_run_cycle` 클로저 제거. `run_one_task` 에 `cycle_repo_root` + `coordination_root` two explicit params 추가. `write_active_loop`/`write_active_start` 에 `coordination_root: Path | None = None` 추가(None→repo_root fallback→byte-identical). `run_repair_apply` 에 `cycle_root: Path | None = None` 추가.
  - Finding 4 (MED): `_run_cycle_in_task_worktree` 의 `try/finally` 를 create **직후**로 이동. seed 가 예외를 던져도 teardown 실행.
  - Finding 5 (MED): `per_task_wall_clock_budget` 를 `effective_task_pool_size > 1` 일 때만 resolve. X==1 에서는 env 무시 + 0 hard-clamp → state JSON 변경 없음 → byte-identical.
- New tests: `test_stop_event_fail_closed_covers_repair_path` / `test_worktree_lifecycle_teardown_on_seed_failure` / `test_x1_budget_env_ignored_byte_identical` / `test_two_root_leases_on_coordination_root` (4개). 기존 `test_per_task_wall_clock_budget_trips_independently` 수정(Finding 5 행동 반영).
- Commands run: python3 -m py_compile + pytest -q (402 passed).
- Next: orchestrator codex adversarial re-review → pass 시 commit + PR.
```
