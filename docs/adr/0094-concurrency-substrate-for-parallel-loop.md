# 0094: 병렬 루프를 위한 동시성 안전 substrate (atomic loop-state + lease manager + 전역 concurrency budget)

- Status: proposed
- Date: 2026-06-02
- Deciders: User, Claude Code
- Related: [ADR 0083](./0083-local-gate-completion-and-real100-v2-judge-egress.md) (`make 시작` local-gate completion / EXECUTE_SHIP=0), [ADR 0085](./0085-infinite-mode-active-auto-loop.md) (무한 모드 active-auto-loop + 안전 가드), [ADR 0087](./0087-opt-in-omc-team-parallel-runner.md) (opt-in omc 병렬 runner / `_resolve_omc_worker_mix`), [ADR 0080](./0080-active-loop-registry-v2-dual-agent-lanes.md) (registry v2 / lease + lane policy), [ADR 0001](./0001-preserve-naive-baseline.md) (baseline byte-identical 보존), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (private 데이터 경계), [ADR 0061](./0061-external-and-paid-api-dependencies-allowed.md) (외부/유료 API opt-in 3조건)
- Issue: #1762

## Context

`make 시작`(active-auto-loop, [`scripts/agent_loop.py`](../../scripts/agent_loop.py))을 X×Y×Z
3-level 병렬화([ADR 0095](./0095-task-parallel-bounded-loop.md))로 확장하려는 maintainer 결정
앞에서, Plan 설계 패스 + 독립 codex 리뷰 + Claude 3자가 **YELLOW** 로 수렴했다 — 병렬화 자체는
표준 concurrency engineering 으로 sound 하지만, **transactional per-task state substrate 가 먼저
착륙(land FIRST)해야 한다**.

codex 의 가장 날카로운 지적: `leases.json` 은 **이름만 lease(lease in name only)** 다 —
`write_active_start` / `acquire_active_agent` / `release_active_agent` /
`assert_claimed_files_disjoint` 전반에 snapshot-load → 메모리 변형 → full-file rewrite 가
일어나는데 read→check→write 를 묶는 **atomic critical section 이 전혀 없다**. 동시 task 가 두 개
진입하면 `assert_claimed_files_disjoint` 가 본 snapshot 과 실제 쓰기 사이에 다른 writer 가
끼어드는 **snapshot TOCTOU** 가 발생해 claimed-files 겹침 방지 보증이 깨진다.

마찬가지로 `auto_loop_state.json` ledger 쓰기 — `write_cycle_checkpoint`(cycle 체크포인트)와
terminal write — 는 lock 없는 full-file `write_text` 이라 동시성 하에서 **last-writer-wins**(마지막
writer 가 이김)다: completed / deferred / cycles / blockers count 가 유실(lost update)된다.

그리고 Z role-parallelism 은 현재 throttle 되지 않는다 — `--max-parallel` 은 선택된 session
count 만 검증하는 guard 일 뿐 실제 동시 실행을 제한하는 semaphore 가 아니다(ADR 0087 이 in-repo
`--max-parallel` 을 "가짜 동시성" 으로 정정한 그 표면). X(task pool)·Y(omc worker)·Z(role)를
각각 독립적으로 풀면 동시 CLI subprocess 수가 곱(multiply)으로 수백 개까지 폭증할 수 있다.

즉 substrate(원자적 상태 기록 + 진짜 lease + 전역 동시성 천장)는 X 를 켜기 전(precede)에 안전
hardening 으로 먼저 들어가야 한다.

## Decision

병렬 루프를 위한 **동시성 안전 substrate** 를 도입한다. 이 substrate 는 X 활성화와 **분리**되어
있다 — X=1 에서도 안전 hardening 으로서 가치가 있고, 기본값(X=1, M=8)에서 산출 codex 명령 +
`auto_loop_state.json` 페이로드 + lease 파일이 **byte-identical**(ADR 0001 gate)이다.

- **(1) atomic write helper**: temp file 작성 → `os.replace`(원자적 rename) → `fcntl.flock`
  (POSIX exclusive lock)의 조합. `fcntl` 은 import guard 로 감싸 비-POSIX 환경에서는 **atomic-rename
  only** 로 degrade 한다(파일 교체는 여전히 원자적). 이 helper 를 2개 ledger write site
  (`write_cycle_checkpoint`, terminal write) + `_write_active_leases` 에 적용한다.
- **(2) `LedgerState` single serialized writer**: completed / deferred / cycles / blockers /
  consecutive_blockers 를 in-process `threading.Lock` 뒤의 **단일 직렬 writer** 로 모은다. ledger
  엔트리는 **append-only fact**(완료/지연/blocker 사실의 누적)이므로 single-writer = **zero
  lost-update** — N-way read-modify-write 충돌 해소 로직이 불필요하다.
- **(3) `LeaseManager.claim_disjoint`**: read → disjoint-check → write 를 **하나의**
  `flock(LOCK_EX)` critical section 안에서 수행해 `assert_claimed_files_disjoint` 의 snapshot
  TOCTOU 를 닫는다. 같은 lock 아래로 `acquire_active_agent` / `release_active_agent`(active_agent
  borrow/return)를 retrofit 한다 — 검사와 쓰기가 하나의 임계 구역이 되도록.
- **(4) 전역 `BoundedSemaphore(M)`**: 기본 M=8, env `BIDMATE_AGENT_LOOP_GLOBAL_CONCURRENCY`,
  Makefile `ACTIVE_GLOBAL_CONCURRENCY`. **모든 CLI spawn**(claude write / codex patch /
  read-review / omc)이 이 단일 전역 semaphore 를 acquire 한다 — X·Y·Z 가 각자의 cap 으로 곱셈
  폭증하지 않도록 하는 단일 천장이다. fail-closed: M<=0 → 1 로 보정.

이 substrate 는 X 를 켜는 것과 **별개**다(SEPARATE from enabling X). X=1 에서도 안전한 hardening
이며, 기본(X=1, M=8)에서 byte-identical 이다(ADR 0001 gate). task pool(X)·omc multi-worker(Y)의
정책 결정은 [ADR 0095](./0095-task-parallel-bounded-loop.md) 가 담당한다.

`scripts/agent_loop.py` 는 본 단계에서도 `LOAD_BEARING_PATHS` 에 올리지 않는다(ADR 0080/0085/0087
결정 계승) — 동시성 substrate 는 retrieval/verifier/answer/eval 런타임을 건드리지 않는다.

## Drivers

1. **transactionality-first (YELLOW 합의)** — 3자(Plan/codex/Claude)가 "병렬은 sound 하나
   transactional 상태 substrate 가 먼저" 로 수렴했다. lock 없는 ledger/lease 쓰기는 X 이전에
   닫아야 할 안전 결함이다.
2. **결정론적 테스트 가능성** — atomic-write / `claim_disjoint` / semaphore 를 fake + barrier 로
   실 spawn 없이 결정론 동시성 테스트.
3. **재사용 / SSoT** — 신규 sidecar 파일 0; 기존 `auto_loop_state.json` 단일 출처 재사용 + issue
   #1719 confinement primitive 재사용.

## Alternatives considered

- **ledger 를 N-way RMW-under-lock 로.** 기각: ledger 는 append-only fact 라 single-writer 가 더
  단순하고 lost-update 가 구조적으로 0이다. 충돌 해소(merge) 로직은 불필요한 복잡도.
- **sidecar timing/lease 파일(별도 저장).** 기각: `auto_loop_state.json` / `leases.json` 이 이미
  cycle/lease 의 단일 출처(SSoT)다. 신규 파일은 SSoT 분산.
- **multi-process 모델(file-only 조정).** 기각: in-process shared-memory lock(`threading.Lock` /
  `BoundedSemaphore`)이 파일-only 조정보다 단순하고 deadlock 추론이 쉽다. 파일 lock 은
  cross-worktree 경계용으로만 `flock` 을 쓴다.
- **전역 cap 없음 / 독립 cap(X·Y·Z 각각).** 기각: X×Y×Z 가 곱으로 폭증해 동시 CLI 수백 개 →
  자원 고갈. 단일 전역 천장 M 이 곱셈을 막는다.

## Consequences

- `fcntl` 는 POSIX-only → 비-POSIX CI 에서는 atomic-rename only 로 degrade(파일 교체는 여전히
  원자적, in-process 직렬화는 `threading.Lock` 이 담당). 이는 graceful degradation 이다.
- 신규 reviewer 계약 3종이 추가된다 — atomic-write helper(temp + `os.replace` + `fcntl.flock`),
  `LeaseManager.claim_disjoint`(단일 flock critical section), 전역 `BoundedSemaphore(M)`. reviewer
  는 이 계약과 X=1/M=8 byte-identical 회귀 테스트를 검토한다.
- `agent_loop.py` 는 `LOAD_BEARING_PATHS` 비승격 유지(ADR 0080/0085/0087) — RAG 런타임 미변경.
- 기본(X=1, M=8)에서 산출 codex 명령 + `auto_loop_state.json` 페이로드 + lease 파일이 오늘과
  byte-identical(ADR 0001 보존). 병렬 활성화는 [ADR 0095](./0095-task-parallel-bounded-loop.md).

## Verification

```bash
python3 -m pytest -q tests/test_agent_loop.py -k 'ledger or lease or atomic or concurrency'
python3 scripts/_governance.py --check-adr-readme-parity docs/adr/0094-concurrency-substrate-for-parallel-loop.md
git diff --check
```

<!-- verifies-key: scripts/agent_loop.py:write_cycle_checkpoint -->
<!-- verifies-key: scripts/agent_loop.py:_write_active_leases -->
<!-- verifies-key: scripts/agent_loop.py:assert_claimed_files_disjoint -->
<!-- verifies-key: scripts/agent_loop.py:acquire_active_agent -->
