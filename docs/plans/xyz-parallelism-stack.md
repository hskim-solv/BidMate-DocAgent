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
