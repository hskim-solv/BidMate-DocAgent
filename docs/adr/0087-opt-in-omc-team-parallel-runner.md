# 0087: opt-in OMC team 병렬 실행 runner 백엔드 (`--runner omc`) — 데이터-경계 ack fail-closed + no-auto-merge gate 라우팅

- Status: accepted
- Date: 2026-05-29
- Deciders: User, Claude Code
- Related: [ADR 0085](./0085-infinite-mode-active-auto-loop.md) (무한 모드 / unlimited caps), [ADR 0086](./0086-lane-tool-sandbox-policy-option-c.md) (lane Tool/Sandbox 정책), [ADR 0080](./0080-active-loop-registry-v2-dual-agent-lanes.md) (registry v2 / dual-agent lanes), [ADR 0061](./0061-external-and-paid-api-dependencies-allowed.md) (외부 API 데이터-경계 3조건), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md) (private 데이터 경계), [ADR 0001](./0001-preserve-naive-baseline.md) (baseline byte-identical 보존), [ADR 0007](./0007-issue-linked-branch-naming.md)
- Issue: #1679

## Context

in-repo `active-codex-runner`의 `--max-parallel`은 **가짜 동시성**이다: `subprocess.Popen`을
배치로 띄운 뒤 순차로 wait하며, 실제로는 선택된 session count ≤ max-parallel만 검증한다.
OMC의 `omc team`은 **진짜 동시** tmux worker를 per-worker git-worktree 격리로 제공한다.

조사 중 **CRITICAL SAFETY FINDING**: `omc team`은 per-worker sandbox / permission / network
플래그를 **전혀 노출하지 않는다**. 그 worker(claude/codex CLI)는 자체 **DEFAULT** 권한으로
돌아 — in-repo runner의 명시적 `--sandbox read-only`(codex) / tool allowlist(claude)보다
**덜 통제**된다. 즉 OMC worker는 worktree의 비공개 데이터를 읽고 네트워크로 egress할 수 있으며,
`--auto-merge`는 worker commit을 leader 브랜치로 머지한다. 이는 ADR 0086의 danger-full-access와
같은 ADR 0005 데이터-경계 리스크지만 **더 강하다**(sandbox 옵션 자체가 없음). 유지보수자는 이를
명시적 **OPT-IN**으로, 데이터-경계 acknowledgment 뒤에 gating해 ship하기로 결정했다.

## Decision

- **(a) `--runner {codex,omc}` opt-in, 기본 codex byte-identical.** `active-codex-runner`와
  `active-auto-loop` argparse 양쪽에 `--runner`(choices `codex`/`omc`, default `codex`)를
  추가하고 `write_active_codex_runner`(신규 keyword `runner: str = "codex"`) →
  `write_active_auto_loop` → runner 호출로 thread한다. Makefile `ACTIVE_RUNNER ?= codex`를
  `active-codex-runner` / `active-auto-loop` / `시작` target에 `--runner "$(ACTIVE_RUNNER)"`로
  넘긴다. **기본 `codex`는 오늘과 byte-identical**(ADR 0001 보존) — omc 분기는
  `runner == "omc"`일 때만 진입한다.
- **(b) omc worker는 uncontrolled → ack 없이 fail-closed.** `runner=omc`는 명시적
  acknowledgment env `ACTIVE_OMC_RUNNER_ACK=1`(모듈 상수 `OMC_RUNNER_ACK_ENV`)을 요구한다.
  ack가 없으면 **FAIL-CLOSED**: blocked `ActiveCodexRunnerResult`를 반환하고
  (메시지 상수 `OMC_RUNNER_REQUIRES_ACK_MESSAGE`) **omc를 절대 spawn하지 않는다**. omc team
  worker는 per-worker sandbox가 없어(network + private-data access) ADR 0005 경계를 완화하므로,
  그 완화는 명시 opt-in으로만 허용한다(ADR 0061 데이터-경계 조건).
- **(c) adapter가 거버넌스를 재부과 + NO auto-merge → gate 라우팅.** 어댑터
  `_run_omc_team_runner`는 injectable callable(`omc_runner=None`, 기본 실 subprocess wrapper —
  `popen_factory` injection 패턴 미러)을 통해서만 omc를 부르므로 **테스트는 실 omc를 절대
  spawn하지 않는다**. 명령은 `omc team N:claude,M:codex --no-decompose "<task>"`를
  env `OMC_TEAM_WORKTREE_MODE=branch`(per-worker git-worktree 격리)로 띄우되 **`--auto-merge`는
  절대 넘기지 않는다**.
  - **ENV-var secrets 제거 (round-2 fix #1, round-4 fix #1 정정 — defense-in-depth,
    완전한 자격증명 경계 아님):** `_build_omc_env`가 `_OMC_ENV_ALLOWLIST`(PATH / HOME / USER /
    SHELL / TERM / LANG / LC_* / TMUX* / OMC_HOME / XDG_CONFIG_HOME / CI /
    GIT_{AUTHOR,COMMITTER}_{NAME,EMAIL} / NODE_PATH)만 필터링해 전달한다. **round-4 fix #1:**
    `OMC_CONFIG`, `XDG_CACHE_HOME`, `XDG_RUNTIME_DIR`을 허용리스트에서 제거(omc에 불필요,
    표면 축소). ANTHROPIC_API_KEY / OPENAI_API_KEY / GH_TOKEN / AWS_* / DATABASE_URL 등
    ENV-var 시크릿은 차단된다. **단, 이것은 완전한 자격증명 경계가 아니다.** omc worker는
    user의 자체 인증된 CLI(claude/codex)를 실행하며, 그 CLI는 파일시스템 경로(~/.codex,
    ~/.claude, ~/.config/gh, ~/.aws)에서 직접 자격증명을 로드한다. HOME은 CLI 인증에 필수이므로
    유지한다. env 허용리스트는 **defense-in-depth**이며, `ACTIVE_OMC_RUNNER_ACK=1` ack가
    home-scoped 자격증명 + 네트워크 egress 접근을 명시 수용하는 핵심 게이트다.
  - **단일 worker 강제 + `--read-agent` 우선 (round-2 fix #2, round-3 fix #2 강화):**
    `_resolve_omc_worker_mix`는 총 worker 수를 항상 1로 강제한다(`total_workers = 1`).
    **round-3 fix #2:** `read_agent: str = "auto"` 파라미터 추가. 명시적 `"claude"` →
    무조건 `(1, 0)`, `"codex"` → 무조건 `(0, 1)`, `"auto"`만 agent_mix 정책 majority로
    fallback. `read_agent`는 `_run_omc_team_runner` → `write_active_codex_runner`에서
    thread된다. >1 worker를 launch하면 leader 외 diff가 묵묵히 버려지고 ADR 0005 노출이
    배수로 늘어난다. multi-worker diff 캡처/머지는 follow-up.
  - **`task_id` 전파 + standalone 파생 (round-2 fix #3, round-4 fix #2):**
    `_run_omc_team_runner`에 `task_id: str | None` 파라미터를 추가해
    `write_active_codex_runner`의 `task_id`를 흘린다. **round-4 fix #2:** `--task` 없이
    standalone으로 호출할 때(`task_id is None`) 선택된 registry session, 그 다음 전체 registry
    session 순으로 `T-YYYY-NNNN` task_id를 파생한다. 파생 불가 시 omc spawn 전 fail-closed
    (높은 비용의 run이 `write_active_apply` 거부 artifact를 만들지 않도록). `write_active_apply`는
    유효한 task_id가 없으면 항상 거부한다.
  - **heartbeat 무효화는 실행된 run에만 (round-2 fix #4):** `_finalize_omc_runner_result`에
    `invalidate_heartbeats: bool` 파라미터를 추가한다. no-ack / dry-run(execute=False) /
    pre-spawn 차단(privacy 실패 등) 경로는 모두 `invalidate_heartbeats=False` — omc team이
    실제로 launch된 경우(try/finally 블록 진입 후)에만 `True`를 전달한다. 이전 구현은
    _finalize_omc_runner_result를 항상 호출해 no-ack/dry-run 경로에서도 registry를 오염시켰다.
  - **`<task>` 강화 privacy scrub (round-1 fix #2, ADR 0005 data-boundary):** task text에
    `_redact_private_text` + `_privacy_findings_for_text` 사전 감사를 적용한다.
  - **deadline-based poll loop + per-command 타임아웃 (round-1 fix #1, round-3 fix #1 강화,
    round-5 fix #1 API 수정):** deadline 기반 polling으로 terminal 상태 확인; timeout 경과 →
    blocked + teardown. **round-3 fix #1:** `_default_omc_runner`에 `timeout: float | None = None`
    파라미터 추가; 모든 subprocess 호출에 `timeout=_remaining_budget()`. shutdown은
    `timeout=30.0`. **round-5 fix #1 [CRITICAL]:** `omc team status`(텍스트 출력)와
    `omc team api get-diff`는 **실 omc CLI에 존재하지 않는다.** poll loop는
    `omc team api get-summary --input '{"team_name":"<name>"}' --json`으로 교체됐다.
    응답 `data.summary.tasks`의 `in_progress == 0 and failed == 0 and total > 0 and completed == total` →
    terminal-success; `in_progress == 0 and failed > 0` → terminal-fail. diff 캡처는
    `summary.workers[0].worktree_path`를 읽어 `git_runner(["git", "-C", <worktree>, "diff", "HEAD"])`로
    대체됐다. 테스트의 `_fake_omc_runner`는 strict 계약 검사 — `get-diff` 시도 시 AssertionError.
    injectable `git_runner=None`(기본 `_git_worktree_runner`) 파라미터로 테스트가 git를 제어한다.
  - **committed worker diff 캡처 — merge-base diff (round-6 fix #1 [CRITICAL]):** OMC worker는
    per-worker branch에 **commit**한다. `git diff HEAD`는 uncommitted 변경만 캡처하므로 committed
    work가 있으면 empty diff를 반환 — "empty/completed"로 잘못 리포트되고 scope/privacy/gate
    라우팅을 완전히 건너뜀. 수정: diff 캡처 전에
    `git -C <worktree> merge-base HEAD origin/main`으로 분기 지점 SHA를 먼저 계산하고,
    `git -C <worktree> diff <base_sha>`로 교체 — committed + staged + unstaged 전체를 캡처.
    merge-base 계산 실패(remote ref 없음, shallow clone 등) → 워닝 발행 + `git diff HEAD`로
    graceful fallback(uncommitted-only, 운영에서 merge-base 실패는 발생하지 않아야 함).
  - **gate heartbeat 무효화 (round-1 fix #3):** `_invalidate_omc_blocking_gate_heartbeats`로
    blocking-role status를 `pending-omc-review`로 초기화 (실행된 run에만 적용 — round-2 fix #4).
  - **scope 검사 warn-open → fail-closed (round-5 fix #2):** `_finalize_omc_runner_result`에서
    active write lease에 `claimed_files`가 없거나 lease가 없는 상태로 `verdict == "proposed"`이면
    무조건 `blocked`로 강등된다(이전: 경고만). omc worker는 uncontrolled이므로 명시적 scope
    선언 없이 proposed diff를 허용하는 것은 위험하다. `claimed_files`가 있어도 diff가 범위 밖
    파일을 포함하면 기존대로 blocked.
  - **scope 검사를 current task_id lease로 한정 (round-6 fix #2 [CRITICAL]):** 이전
    `_find_active_write_lease(lease_id=None)`는 첫 번째 active write lease를 반환했다.
    `active-start`가 기존 lease를 보존한 채 새 lease를 추가하면 **다른 task**의 stale lease가
    먼저 반환될 수 있다 — 잘못된 `claimed_files`로 omc diff가 검증되거나(보안 위반), 현재
    task의 유효한 diff가 잘못 blocked됨. 수정: lease 목록을 현재 `task_id`로 필터링해
    정확히 1개의 matching lease를 요구. 0개(현재 task lease 없음) → blocked fail-closed;
    2개 이상(ambiguous) → blocked fail-closed.
  - **lease scope 완전 강화 — no-task-id lease 허용 제거 (round-7 fix #1 [HIGH]):** round-6의
    구현이 `task_id` 필드가 없는 구형(legacy) lease도 eligible로 취급하는 fallback을 남겨두었다.
    이는 fail-open edge다 — task_id 없는 lease는 어느 task에도 속할 수 있는 stale/유출 lease.
    수정: `task_id`가 설정된 경우, lease의 `task_id` 필드가 **명시적으로** 현재 `task_id`와
    **정확히 일치**하는 lease만 eligible. task_id 없는 lease 일체 거부. `task_id is None/""` 인
    standalone call은 기존대로 any active write lease 허용. `_write_expanded_active_runner_fixture`가
    lease dict에 `"task_id": task_id`를 명시적으로 기록하도록 업데이트됨.
  - **shutdown 실패 가시화 + --force fallback (round-7 fix #2 [HIGH]):** 이전 finally 블록은
    `omc team shutdown` rc를 검사하지 않아 비정상 종료된 worker가 silent하게 방치됐다. 수정:
    shutdown 결과의 rc를 확인해 nonzero → warning 기록 + `omc team shutdown <team> --force`
    fallback 시도(timeout=10s). `TimeoutExpired` 시도 마찬가지로 warning + force fallback. force
    fallback 자체도 실패하면 warning 추가(raise 없이 teardown 최선 유지). `_fake_omc_runner`가
    `shutdown_rc` / `shutdown_force_rc` 파라미터를 지원해 테스트가 두 경로를 모두 검증한다.
  - **assignment 파일 누락/빈 경우 spawn 전 block (round-7 fix #3 [MEDIUM]):** 이전
    `_build_omc_task_text`는 assignment 파일이 없거나 비어있으면 silently 빈 body나 generic fallback
    text로 계속 진행했다. 정의되지 않은 scope의 omc worker를 spawn하는 것은 안전 위반이다.
    수정: `_build_omc_task_text`의 반환형을 `str` → `tuple[str, list[str]]` (`text`, `blockers`)로
    변경. 선택된 session 중 assignment 파일이 없거나(`FileNotFoundError`) 내용이 비어있으면
    해당 session별 blocker를 `blockers` 리스트에 추가. 호출자에서 `task_text_blockers`가
    비어있지 않으면 omc spawn 전 **fail-closed** 반환. `invalidate_heartbeats=False`(omc team
    미실행).
  - **--force shutdown 결과 검사 (round-8 fix #1 [HIGH]):** round-7 fix #2는 shutdown nonzero →
    `--force` fallback을 추가했으나 `--force` 결과(returncode/stderr)를 검사하지 않았다. `--force`도
    실패하면 네트워크/자격증명 접근 가능한 omc worker가 여전히 실행 중일 수 있다. 수정: `--force`
    결과를 캡처해 nonzero rc 또는 stderr → warning 기록("may still be running — manual cleanup
    required"). `TimeoutExpired` 경로의 `--force` fallback도 동일하게 결과 검사. raise 없이 teardown
    최선 유지.
  - **run-specific artifact 항상 덮어쓰기 (round-8 fix #2 [HIGH]):** `_finalize_omc_runner_result`의
    `else` 브랜치(no-ack / dry-run / pre-spawn block / empty diff — `write_artifact=False` 또는
    `diff_text=""`)가 표준 소비 경로(`patch_runs/implementer/patch_artifact.json`)는 overwrite하지만
    run-specific `artifact_path`(`omc_runs/omc-team/patch_artifact.json`)는 overwrite하지 않았다.
    state가 `sessions[0].assignment`에 `artifact_path`를 기록하므로, 해당 경로에 prior proposed
    artifact가 있으면 현재 blocked/empty run의 출력인 것처럼 소비될 수 있다. 수정: `else` 브랜치에서
    `artifact_path`에 먼저 blocked artifact를 **항상** 쓴다(parent mkdir 포함). 이제 `artifact_path`와
    `standard_path` 양쪽 모두 unconditionally 현재 run 결과를 반영한다.
  - **merge-base 실패 시 fail-closed — git diff HEAD fallback 제거 (round-8 fix #3 [HIGH]):**
    round-6 fix #1은 merge-base 실패 시 `git diff HEAD`로 graceful fallback을 구현했다. 그러나
    omc worker는 per-worker branch에 **commit**하므로 `git diff HEAD`는 uncommitted 변경만 잡는다.
    shallow clone / remote ref 부재 환경에서 worker의 committed 변경이 전혀 캡처되지 않아 privacy
    감사 / scope 검사 / gate 라우팅을 완전히 우회한 채 `empty`/`completed`로 완료된다. 이는 graceful
    degradation이 아니라 안전 허점이다. 수정: merge-base 실패 → **fail-closed**: blocker 추가 후 반환.
    `git diff HEAD` fallback 경로 삭제. 운영자는 `origin/main`이 worker worktree에서 접근 가능한지
    먼저 확인해야 한다. `_fake_git_runner` 기본 `merge_base_sha="deadbeef00000000"`(비어있지 않은
    sentinel SHA)으로 변경해 기존 테스트가 merge-base-success 경로를 운용하게 됨.
  - **gate-heartbeat 무효화 실패 → blocked (round-9 fix #1 [CRITICAL]):** 이전
    `_invalidate_omc_blocking_gate_heartbeats`는 `OSError`/`JSONDecodeError`/`ValueError`를 `pass`로
    삼켜 빈 리스트를 반환했다. 호출자는 이를 "무효화할 것이 없음"과 구별하지 못해, registry 쓰기
    실패 시에도 stale "passed" 리뷰어/감사자 heartbeat가 그대로 남아 Conservative Gate가 READY로
    보일 수 있었다 — omc uncontrolled path에서의 fail-open. 수정: 반환형을 `list[str]` → `tuple[list[str],
    str | None]`(`(invalidated_roles, error_message)`)으로 변경. `error_message`가 None이 아닐 때
    (`invalidate_heartbeats=True` 경로에서 쓰기 실패) — `decision = "blocked"` + blocker 추가
    ("omc gate-heartbeat invalidation failed"). 정상 무효화 성공 시 기존과 동일하게 warning 기록.
  - **dry-run은 artifact 무변경 (round-9 fix #2 [HIGH]):** round-8 fix #2의 `else` 브랜치가
    `execute=False` (dry-run/plan-only) 경로에서도 `artifact_path`와 `standard_path`를 덮어썼다.
    dry-run은 읽기 전용 planning 액션이므로 이전 executed run이 생산한 proposed artifact를 지워서는
    안 된다 — 이후 `active-apply`가 live proposed diff를 잃는다. 수정: round-8 `else` 브랜치를
    `elif execute:`로 변경해 **`execute=True` 경우에만** artifact overwrite를 실행. dry-run은
    disk의 artifact를 일체 건드리지 않는다.
  - **untracked worker 파일 diff 캡처 (round-10 fix #1 [HIGH]):** round-6/8 diff 캡처는
    `git -C <worktree> diff <base_sha>`를 직접 실행했다. omc worker가 추가한 신규(untracked)
    파일은 이 명령에 표시되지 않아 privacy/scope 검사를 완전히 우회한 채 diff가 비어 보이는
    false-empty completion이 발생했다. 수정: diff 직전에 `git -C <worktree> add -A`로 모든
    변경(committed + staged + untracked)을 staging하고, `git -C <worktree> diff --cached <base_sha>`
    로 변경. `add -A` 실패 시 blocker + blocked. 이제 신규 파일도 privacy redaction / scope /
    gate 경로를 통과해야만 proposed artifact로 이어진다.
  - **단일 task 일관성 검증 (round-10 fix #2 [HIGH]):** 선택된 sessions가 두 개 이상의 서로
    다른 task_id를 가지면, 여러 task의 assignment text를 단일 omc worker에 전달하게 된다 —
    데이터 경계 위반이자 의도치 않은 cross-task context 누출. 마찬가지로 `--task T-A`와 함께
    T-B sessions이 선택되면 잘못된 task 컨텍스트가 worker에 전달된다. 수정: `_build_omc_task_text`
    호출 **직전에** 선택된 sessions의 task_id 집합(`selected_task_ids`)을 구성한다.
    (1) `len(selected_task_ids) > 1` → blocked fail-closed ("ambiguous: spans N distinct task IDs").
    (2) `not task_id` + `len == 1` → 유일 task_id로 자동 파생(기존 동작 유지).
    (3) `task_id` 제공 + `selected_task_ids`에 불일치 → blocked fail-closed ("mismatch:
    --task X does not match selected sessions"). omc는 어떤 경우에도 spawn되지 않는다.
  - worker diff 캡처 후 privacy 재감사 + `claimed_files` scope 검사 fail-closed 재부과. 결과를
    `ActiveCodexRunnerResult` + 동일한 `patch_artifact.json` 모양으로 매핑해 active-apply /
    Conservative Gate / human-gated ship이 변경 없이 동작한다 — diff는 main으로 머지되지 않고
    기존 gate 경로로 라우팅된다. team은 finally에서 항상 `omc team shutdown`; 실패 시 raise 없이
    blocked 결과 반환.
  - **stale 표준 패치 아티팩트 덮어쓰기 (round-3 fix #3):** `_finalize_omc_runner_result`에서
    `write_artifact=False` (no-ack / pre-spawn 차단 / dry-run) 경우에도 표준 소비 경로
    `patch_runs/implementer/patch_artifact.json`이 존재하면 blocked 아티팩트로 **덮어쓴다**.
    이전 successful run의 stale proposed patch가 이후 blocked run을 우회해 `write_active_apply`에
    소비되는 것을 막는다. `write_artifact=True` 경로에서도 `decision == "blocked"` 이면
    동일하게 blocked 아티팩트를 표준 경로에 쓴다.
  - **auto-loop `task_id` 전파 (round-3 fix #4):** `write_active_auto_loop`의
    `write_active_codex_runner(...)` 호출에 `task_id=task.task_id`를 추가한다. 이전에는
    `task_id`가 전달되지 않아 omc 경로에서 생성된 `patch_artifact.json`에 `null` task_id가
    기록되어 `write_active_apply`가 artifact를 거부했다.
- **(d) `agent_loop.py`는 `LOAD_BEARING_PATHS` 비승격 유지** (ADR 0080/0085/0086 결정 유지) —
  병렬 runner 백엔드는 retrieval/verifier/answer/eval 런타임을 건드리지 않으며, ship 실행은
  여전히 기존 human-gated 경로가 담당한다.

## Consequences

- 운영자가 명시적으로 `ACTIVE_OMC_RUNNER_ACK=1` + `--runner omc`를 켰을 때만 진짜 동시
  tmux worker로 병렬 실행되고, 그 외에는 byte-identical codex 경로가 그대로 돈다.
- omc worker는 uncontrolled(no per-worker sandbox)이지만, 캡처된 diff가 privacy 재감사 +
  scope 검사 + no-auto-merge를 통과해야만 active-apply/gate로 흐르므로 Conservative Gate와
  human-gated ship이 유지된다 — main으로의 자동 머지는 없다.
- **ENV-var secrets 제거 (round-2 fix #1, round-4 fix #1 정정):** `_OMC_ENV_ALLOWLIST`가
  ANTHROPIC_API_KEY / OPENAI_API_KEY / GH_TOKEN / AWS_* / DATABASE_URL 등 ENV-var 시크릿을
  차단한다. 이는 **defense-in-depth**이지 완전한 자격증명 경계가 아니다. omc worker는 user의
  자체 인증된 CLI이므로 HOME 아래 파일시스템 경로(~/.codex, ~/.claude, ~/.config/gh, ~/.aws)로
  자격증명에 독립 접근한다. HOME은 CLI 동작에 필수이므로 유지한다. `ACTIVE_OMC_RUNNER_ACK=1`
  ack는 이 home-scoped 자격증명 접근 + 네트워크 egress를 명시 수용한다. `OMC_CONFIG`,
  `XDG_CACHE_HOME`, `XDG_RUNTIME_DIR`은 round-4에서 허용리스트에서 제거했다(불필요, 노출 축소).
- **단일 worker 강제 (round-2 fix #2):** `_resolve_omc_worker_mix`가 항상 1 worker만 반환한다.
  agent_mix가 claude=5,codex=5 이어도 `omc team 1:claude ...`만 launch된다. multi-worker diff
  캡처가 구현될 때까지 노출 배수 문제가 발생하지 않는다.
- **`--read-agent` 명시 우선 (round-3 fix #2):** `read_agent="claude"` / `"codex"` 전달 시
  agent_mix 정책을 무시하고 해당 lane으로 고정된다. `"auto"`(기본)만 정책 majority로 fallback.
- **`task_id` 전파 + standalone 파생 (round-2 fix #3, round-3 fix #4, round-4 fix #2):**
  patch_artifact.json에 유효한 T-YYYY-NNNN task_id가 채워져 `write_active_apply`가 artifact를
  거부하지 않는다. `write_active_auto_loop`의 호출에 `task_id=task.task_id`(round-3 fix #4).
  **round-4 fix #2:** standalone(`--task` 미전달) 시 registry session에서 first-valid
  `T-YYYY-NNNN`을 파생한다. 파생 불가 시 omc spawn 전 fail-closed(높은 비용 run 낭비 방지).
- **heartbeat 무효화 범위 제한 (round-2 fix #4):** no-ack / dry-run / pre-spawn 차단 경로는
  레지스트리를 건드리지 않는다. 실제 launch된 run에서만 blocking-role status가 초기화된다.
- **강화된 ADR 0005 data-boundary 보장 (round-1 fix #2):** task text는 `_redact_private_text`
  강화 redaction 후 `_privacy_findings_for_text` 사전 감사를 통과해야 omc가 spawn된다.
- **false-complete 방지 + per-command 타임아웃 (round-1 fix #1, round-3 fix #1, round-5 fix #1):**
  deadline-based poll loop는 `get-summary` 응답의 terminal-success 조건(`in_progress == 0 and
  failed == 0 and total > 0 and completed == total`) 확인 후에만 diff 캡처를 진행한다.
  `timeout_seconds > 0` 이면 모든 subprocess 호출에 남은 예산이 `timeout=`으로 전달된다.
  **round-5 fix #1:** poll API를 실 omc CLI 계약과 일치시킴(`get-summary --input JSON --json`);
  diff는 `git -C <worktree> diff HEAD`로 캡처(API에 `get-diff` 없음).
- **committed worker diff 캡처 (round-6 fix #1, round-8 fix #3 강화):** diff 캡처 커맨드가
  `git -C <worktree> merge-base HEAD origin/main` → `git -C <worktree> diff <base_sha>`로 바뀌어
  worker가 commit한 변경을 누락 없이 캡처한다. **round-8 fix #3:** merge-base 실패 시 graceful
  fallback(round-6 방식) 대신 **fail-closed** — `git diff HEAD` 경로 삭제. 실패 시 blocker 기록
  + blocked 반환. `_fake_git_runner` 기본값 `merge_base_sha="deadbeef00000000"` — 기존 테스트는
  merge-base-success 경로를 운용한다.
- **scope 검사 fail-closed (round-5 fix #2):** write lease에 `claimed_files`가 없으면 proposed diff가
  있어도 `blocked`로 강등된다. omc worker는 uncontrolled이므로 명시적 scope 없이 proposed artifact
  허용은 위험하다. `_write_expanded_active_runner_fixture`가 proper write lease(claimed_files 포함)를
  초기화하므로 테스트가 fixture 레벨에서 계약을 검증한다.
- **scope 검사를 current task_id lease로 한정 (round-6 fix #2):** lease 목록에서 `task_id`로
  필터링한 정확히 1개의 active write lease를 요구한다. 0개(현재 task lease 없음) 또는 2개 이상
  (중복) → blocked fail-closed. 다른 task의 `claimed_files`로 검증하는 것을 원천 차단한다.
- **no-task-id lease 완전 거부 (round-7 fix #1):** `task_id` 설정 시 lease에 **동일한 `task_id`
  필드**가 없으면 eligible에서 제외된다. unscoped/legacy lease가 scope 검사를 통과하는 fail-open
  경로가 완전히 닫혔다. 테스트 fixture `_write_expanded_active_runner_fixture`가 lease에 명시적
  `task_id`를 기록한다.
- **shutdown 실패 가시화 (round-7 fix #2):** shutdown nonzero rc → warning 기록 + `--force`
  fallback. `TimeoutExpired` → warning + `--force` fallback. 두 경로 모두 raise 없음(teardown
  최선 유지). 운영자는 warning으로 orphaned worker를 인지할 수 있다.
- **missing/empty assignment 시 spawn 차단 (round-7 fix #3):** `_build_omc_task_text`가
  `tuple[str, list[str]]`을 반환한다. assignment 파일이 없거나 비어있으면 caller가 omc spawn
  전 fail-closed 반환한다. 정의되지 않은 scope의 worker가 절대 spawn되지 않는다.
- **--force shutdown 결과 검사 (round-8 fix #1):** `--force` 결과(rc/stderr)를 확인해 실패 시
  "may still be running — manual cleanup required" warning을 추가한다. `TimeoutExpired` 경로도
  동일. 이제 두 단계 shutdown(normal + force) 모두 결과를 기록한다.
- **run-specific artifact 항상 덮어쓰기 (round-8 fix #2):** `_finalize_omc_runner_result`의
  `else` 브랜치(`write_artifact=False` 또는 `diff_text=""`)에서 `artifact_path`에 blocked artifact를
  **항상** 쓴다. 이전 proposed artifact가 `state.sessions[0].assignment` 경로를 통해 소비될 수
  없다. `standard_path`도 unconditionally overwrite(이전엔 `standard_path.exists()` 조건부였음).
- **merge-base 실패 시 fail-closed (round-8 fix #3):** round-6 `git diff HEAD` fallback 제거.
  merge-base 실패 → blocker + blocked 반환. shallow clone/remote ref 부재 환경에서 worker committed
  변경이 privacy/scope 우회하는 false-empty completion이 불가능해졌다. `_fake_git_runner` 기본
  `merge_base_sha="deadbeef00000000"`로 변경 — 기존 테스트가 merge-base-success path를 운용.
  round-6 `test_active_codex_runner_omc_fallback_to_head_diff_when_merge_base_fails`가
  `test_active_codex_runner_omc_blocked_when_merge_base_fails`로 이름 변경 + blocked 검증으로 갱신.
- **gate-heartbeat 무효화 실패 → blocked (round-9 fix #1):** `_invalidate_omc_blocking_gate_heartbeats`
  반환형이 `list[str]` → `tuple[list[str], str | None]`으로 변경됐다. `error_message != None` 시
  `_finalize_omc_runner_result`가 `decision = "blocked"` + blocker를 추가한다. registry 쓰기 실패로
  stale reviewer/auditor heartbeat가 생존해 Conservative Gate가 오판(READY)하는 fail-open 경로가 닫혔다.
- **dry-run은 artifact 무변경 (round-9 fix #2):** round-8 fix #2의 `else` 브랜치를 `elif execute:`로
  변경. `execute=False` dry-run은 `artifact_path`와 `standard_path` 양쪽 모두 건드리지 않는다. 이전
  proposed artifact를 지워 active-apply를 실패시키는 round-8 regression이 수정됐다.
- **untracked 파일 캡처 포함 (round-10 fix #1):** diff 캡처가 `git add -A` → `git diff --cached
  <base_sha>` 시퀀스로 변경됐다. omc worker가 신규 파일을 생성하면 이전 `git diff <base_sha>` 방식은
  untracked 파일을 놓쳐 false-empty로 완료됐다. 이제 committed + staged + untracked 변경 모두 캡처해
  privacy/scope/gate 검사를 거친다. `git add -A` 실패 → blocker + blocked.
- **단일 task 일관성 gate (round-10 fix #2):** omc spawn 직전에 선택된 sessions의 task_id 집합을
  검증한다. 두 개 이상의 서로 다른 task_id → blocked fail-closed ("ambiguous"). `--task X`와 selected
  sessions의 task_id가 불일치 → blocked fail-closed ("mismatch"). cross-task assignment text가 단일
  worker에 전달되는 것이 차단됐다.
- **Conservative Gate stale-pass 방지 (round-1 fix #3):** 실제 launch된 run에서만
  `_invalidate_omc_blocking_gate_heartbeats`가 호출되어 blocking-role status가 `pending-omc-review`로
  초기화된다. 실제 blocking-role session이 실행되어야만 gate가 READY 상태가 된다.
- **stale 표준 패치 아티팩트 덮어쓰기 (round-3 fix #3, round-9 fix #2 scope):** executed blocked /
  no-ack 경로에서 표준 소비 경로의 기존 패치 아티팩트를 blocked 아티팩트로 덮어쓴다. 이전 successful
  run의 proposed diff가 이후 blocked executed run을 우회하는 것이 차단된다. **dry-run은 제외**
  (round-9 fix #2): dry-run은 artifact를 건드리지 않는다.
- injectable `omc_runner`로 테스트가 실 omc 없이 명령/환경/거버넌스 경로를 전부 검증한다.
- (scope-down) 단일-worker diff 캡처 경로만 완전 구현. >1 worker worktree의 diff 캡처/머지는
  의도적 follow-up — `_resolve_omc_worker_mix`가 단일 worker를 강제하므로 현재는 도달 불가.

## Alternatives considered

- **in-repo runner를 진짜 동시성으로 재작성.** 기각: `omc team`이 per-worker git-worktree
  격리 + tmux 동시성을 이미 제공한다(재발명 회피). 핵심 리스크는 동시성이 아니라 OMC worker의
  uncontrolled 권한이며, 그건 ack gate + 캡처-diff 거버넌스 재부과로 닫는다.
- **omc를 ack 없이 기본 허용.** 기각: omc worker는 sandbox 옵션 자체가 없어 비공개 데이터
  egress가 가능하다 → ADR 0005 경계를 무조건 완화. 명시 opt-in(ack)이 ADR 0061 데이터-경계
  조건이다.
- **`--auto-merge`로 worker commit을 leader 브랜치에 자동 머지.** 기각: 거버넌스(privacy /
  scope / Conservative Gate / human-gated ship)를 우회해 main에 닿는다. diff는 반드시 기존
  active-apply / gate 경로로만 라우팅한다.
- **codex 기본 동작 변경(omc를 기본 runner로).** 기각: ADR 0001 byte-identical 보존 위반.
  omc는 순수 opt-in 분기로만 둔다.

## Deferred / follow-up

- **multi-worker diff 캡처/머지 보류.** worker 브랜치가 여럿일 때의 diff 합성 + 충돌 해소는
  본 ADR 범위 밖이다. `_resolve_omc_worker_mix`가 총 worker=1을 강제하므로 현재 절대 다수
  worker가 launch되지 않는다. 구현 완료 시 `_resolve_omc_worker_mix` 수정 + 이 ADR 업데이트.
- **`_OMC_ENV_ALLOWLIST` 확장.** omc/tmux 런타임이 추가 환경 변수를 요구하면 허용리스트에
  추가 (단, 자격증명·토큰 류는 추가 금지).

## Verification

```bash
python3 -m pytest -q tests/test_agent_loop.py -k 'omc or active_runner_parser'
python3 scripts/_governance.py --check-adr-readme-parity docs/adr/0087-opt-in-omc-team-parallel-runner.md
git diff --check
```

<!-- verifies-key: scripts/agent_loop.py:OMC_RUNNER_ACK_ENV -->
<!-- verifies-key: scripts/agent_loop.py:_run_omc_team_runner -->
<!-- verifies-key: scripts/agent_loop.py:OMC_RUNNER_REQUIRES_ACK_MESSAGE -->
<!-- verifies-key: scripts/agent_loop.py:_OMC_TERMINAL_SUCCESS_STATES -->
<!-- verifies-key: scripts/agent_loop.py:_OMC_ENV_ALLOWLIST -->
<!-- verifies-key: scripts/agent_loop.py:_build_omc_env -->
<!-- verifies-key: scripts/agent_loop.py:_invalidate_omc_blocking_gate_heartbeats -->
<!-- verifies-key: scripts/agent_loop.py:_default_omc_runner -->
<!-- verifies-key: scripts/agent_loop.py:_resolve_omc_worker_mix -->
<!-- verifies-key: docs/operations/active-agent-loop.md:OMC Runner (opt-in) -->
