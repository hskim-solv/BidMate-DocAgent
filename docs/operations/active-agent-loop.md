# Active Agent Loop

이 문서는 `agent_loop.py active-loop`가 운영하는 active
orchestrator 계약이다. 목적은 사람이 다음 세션을 계속 수동 배정하지 않아도,
repo-local ledger가 작업권(lease), 하트비트(heartbeat), 할당(assignment), ship
gate를 보존하게 하는 것이다.

## Topology

기본 topology는 backward-compatible 4개 session이다.

| Session | Role | Write authority |
|---|---|---|
| `orchestrator` | Orchestrator | ledger, queue/plan proposal, gate decision |
| `implementer` | Implementer | assigned issue branch/worktree only |
| `reviewer` | Reviewer | read-only review report |
| `ci-eval-auditor` | CI/Eval Auditor | read-only CI/eval/claim report |

장기 RAG/eval governance 작업은 optional 8-session topology를 사용할 수 있다.

```bash
python3 scripts/agent_loop.py active-loop --mode full-ship --topology expanded-eight --dry-run --from-git
```

| Session | Role | Write authority |
|---|---|---|
| `orchestrator` | Orchestrator | ledger, queue/plan proposal, gate decision |
| `planner-triage` | Planner / Issue Triage | read-only queue/plan/workset proposal |
| `experiment-scout` | Experiment Scout | read-only hypothesis, ablation, aggregate evidence |
| `implementer` | Implementer | assigned issue branch/worktree only |
| `reviewer` | Reviewer | read-only review report |
| `deep-reviewer` | Deep Reviewer | read-only architecture/load-bearing review |
| `ci-regression-auditor` | CI / Regression Auditor | read-only CI/regression report |
| `eval-claim-privacy-auditor` | Eval / Claim / Privacy Auditor | read-only eval/claim/privacy report |

Worker 간 direct communication은 필요 조건이 아니다. 모든 이어받기는
`reports/agent_loop/active/` ledger와 기존 handoff block으로 복구 가능해야 한다.

## Dual-Agent Lanes (registry v2)

각 session은 단일 worker가 아니라 Claude lane과 Codex lane을 함께 가진다.
Dual-agent는 별도 topology가 아니라 기존 `four-role`/`expanded-eight` 위에
얹는 **lane policy**다 (새 topology enum을 추가하지 않는다). 이를 위해
`session_registry.json`은 `schema_version: 2`로 올라간다. v1 registry는 읽을 때
자동으로 v2로 lift되며, `four-role` 동작은 불변이다.

session item마다 다음이 추가된다.

- `lanes`: `{claude: {...}, codex: {...}}`. 각 lane은 `agent`, `status`,
  `current_turn`, `wu_spent_rolling`를 가진다.
- `write_lease_owner`: `Implementer` session만 `true`. 기본 write lease는
  Implementer 하나만 소유한다.
- `ship_gate`: session이 Conservative Gate에서 갖는 분류 —
  `lease-owner`(Implementer), `blocking`(required reviewer/auditor),
  `non-blocking`(Planner / Experiment Scout), `control-plane`(Orchestrator).

top-level에는 `gate_policy: "conservative"`와 `agent_mix`가 추가된다. `agent_mix`는
Claude:Codex 작업량을 session 수가 아니라 **Work Unit(WU)** 기준 rolling window로
맞춘다.

```bash
python3 scripts/agent_loop.py active-loop --mode full-ship \
  --topology expanded-eight --agent-mix claude=5,codex=5 --dry-run --from-git
```

`--agent-mix claude=5,codex=5`는 WU target을 registry의 `agent_mix`와
`reports/agent_loop/active/agent_mix.json`(rolling ledger)에 기록한다.
`session-heartbeat --agent claude|codex`는 한 lane의 상태만 갱신한다 (생략하면
기존 session-level heartbeat).

Phase 1은 lane scaffold + dry-run ledger까지다. 실제 Claude/Codex turn 실행과 WU
집계는 read-only 실행 어댑터(Phase 2)에서 붙는다. 이 registry v2 계약은
[ADR 0080](../adr/0080-active-loop-registry-v2-dual-agent-lanes.md)이 고정한다.

## Ledger

`reports/agent_loop/active/`는 ignored operational state다. Review evidence로
그 자체를 커밋하지 않는다.

- `session_registry.json`: session id, role, task, branch, status, last heartbeat,
  next command, per-session `lanes`, `write_lease_owner`, `ship_gate`, top-level
  `gate_policy`/`agent_mix` (registry v2).
- `leases.json`: task/issue/branch/worktree 단위 write lease, claimed files,
  owner session, expiry, recovery command, `lease_type`, `active_agent`.
- `agent_mix.json`: Claude:Codex Work Unit target policy + rolling window ledger.
- `events.jsonl`: sanitized append-only operational events.
- `assignments/<session_id>.md`: role별 prompt/context pack.

Ledger는 privacy-safe여야 한다. Raw private question/answer/evidence,
`doc_id`, `chunk_id`, filename, prompt/response body, absolute local private path를
쓰지 않는다.

## Tick Flow

```bash
python3 scripts/agent_loop.py active-loop --mode full-ship --dry-run --from-git
```

한 tick은 다음을 수행한다.

1. 현재 branch, issue, changed files, existing ledger를 읽는다.
2. stale session heartbeat를 표시한다.
3. expired lease의 worktree를 검사한다. Dirty, detached, missing, inspection-failed
   worktree는 `recovery-needed`로 남기고 재할당하지 않는다.
4. `overlap-preflight`로 duplicate issue branch, open PR overlap, stale worktree
   위험을 막는다.
5. `Implementer` write lease와 각 role assignment를 갱신한다.
6. Full ship gate 결과를 report한다.

## One-command Start

사람이 "시작"만 눌러도 local orchestration surface가 한 번에 만들어져야 할 때는
`active-start`를 사용한다.

```bash
python3 scripts/agent_loop.py active-start --from-git
```

`--repair-branch` 없는 기본 CLI 호출은 remote mutation을 하지 않는다. 대신
`reports/agent_loop/active/` 아래에 expanded-eight ledger, role assignment, dashboard,
approval packet, readiness score, privacy audit, ship simulation, auto-ship dry-run plan을
한 번에 쓴다.

현재 branch가 detached HEAD이거나 ADR 0007 issue branch가 아니어도 Make wrapper는
`--repair-branch`를 켜서 issue-linked local branch를 먼저 만들거나 전환한 뒤 start pack을
쓴다. `ISSUE=<N>`이 없으면 public-safe GitHub issue를 생성해 branch 번호로 사용한다.
변경 파일과 issue branch가 모두 없으면 PR corpus 기반 `continue-loop` dry run을 자동으로
bootstrap한다. 기본 `PR_BODY_OUT` 경로가 아직 없으면 PR body draft도 먼저 쓴다.

Make wrapper:

```bash
make agent-loop-active-start
```

Make wrapper는 여기서 멈추지 않고 기본적으로 `agent-loop-active-codex-runner`를
`ACTIVE_CODEX_EXECUTE=1`로 이어서 호출한다. 즉 `make agent-loop-active-start` 한
번이면 start pack 생성 후 8-session Codex runner spawn까지 진행한다.

준비만 하고 process를 띄우지 않으려면 다음처럼 끈다.

```bash
make agent-loop-active-start ACTIVE_START_RUNNER=0
```

runner report까지만 보고 실제 spawn을 막으려면 다음처럼 dry-run으로 낮춘다.

```bash
make agent-loop-active-start ACTIVE_START_RUNNER_EXECUTE=0
```

Korean alias는 완주형 bounded loop를 실행한다. 기본값은 `START_TASK_LIMIT=5`이며,
각 iteration에서 start pack, Codex runner, conservative gate를 순서대로 확인한다.
기본 alias는 ship을 실행하지 않는다. ship이 꺼진 상태에서는 Codex runner가 완료되고
conservative gate가 ready이며 privacy gate가 clean일 때만 local completed ledger에
기록한다. spawned Codex sessions는 기본 `read-only` sandbox로 실행된다.
실행 직전에는 `queue-parallel-plan`을 먼저 생성해 upcoming queue를 우선순위별로
정렬하고 `parallel-safe`, `review-only`, `serial-gated` lane으로 묶는다.
이어서 `queue-recommendations`를 report-only로 생성해 최근 diff, queue 상태,
`real100_v2` checkpoint/Chroma artifact 여부, local-LLM baseline gap 같은 신호를
다음 task 후보로 정리한다.

```bash
make 시작
```

task 수를 고정하려면 다음처럼 덮어쓴다.

```bash
make 시작 START_TASK_LIMIT=2
```

## Codex Runner

Python `active-start` CLI는 ledger와 assignment만 만들지만, Make wrapper는 runner를
이어 실행한다. 8-session을 별도 Codex process로 띄우는 standalone 표면은 다음
target이다.

```bash
make agent-loop-active-codex-runner
```

기본값은 dry-run이며, `reports/agent_loop/active/session_registry.json`과
`assignments/<session_id>.md`를 읽어 8개 `codex exec` command와 출력 경로를
`reports/agent_loop/active/codex_runner.md`에 렌더링한다. 실제 spawn은 다음처럼
명시한다.

```bash
make agent-loop-active-codex-runner ACTIVE_CODEX_EXECUTE=1
```

기본 인증 정책은 Codex CLI의 **ChatGPT login** 기반 구독제 경로다. Execute mode는
spawn 전에 `codex login status`가 `Logged in using ChatGPT`를 보고하는지 확인하고,
API-key login, 미로그인, 인증 오류는 fail-closed 한다. Dry-run은 인증 출처를 확인하지
않지만 report/state에 `auth_mode`와 `auth_status`를 남긴다. 임시 우회가 필요하면
`ACTIVE_CODEX_AUTH_MODE=any`를 명시한다.

OpenAI Agents SDK orchestrator는 `OPENAI_API_KEY` 기반 API 호출 경로이므로 이 runner의
기본 운영 모델에서 제외한다. API-key 기반 orchestration을 도입하려면 구독제 runner와
분리된 issue/ADR에서 비용, 인증, privacy 경계를 다시 고정한다.

runner는 session마다 `reports/agent_loop/active/codex_runs/<session_id>/` 아래에
`prompt.md`, `stdout.jsonl`, `stderr.log`, `last_message.md`를 둔다. 기본 sandbox는
`read-only`이고, 각 prompt는 assignment의 read-only 부분만 실행하게 제한한다.
Execute mode는 8개 process를 spawn한 뒤 종료 코드와 last message artifact가 남도록
각 process를 wait한다. 이 runner는 `session-heartbeat`를 pass로 승격하지 않고,
`active-loop --execute`의 ship gate나 `make ship-run`도 호출하지 않는다. 따라서
agent process가 끝났다는 사실은 reviewer/auditor gate 통과 근거가 아니며, gate
status는 별도 heartbeat나 검토 표면에서 유지한다.

## OMC Runner (opt-in)

기본 runner(`codex`)는 위에서 설명한 in-repo Popen 배치 표면이다. **opt-in** 대안으로
`--runner omc`(make: `ACTIVE_RUNNER=omc`)를 켜면, 실제 동시 실행을 OMC `omc team`(tmux
worker + per-worker git-worktree 격리)에 위임한다 (ADR 0087).

```bash
ACTIVE_OMC_RUNNER_ACK=1 make agent-loop-active-codex-runner ACTIVE_RUNNER=omc ACTIVE_CODEX_EXECUTE=1
```

**기본은 codex이며, `--runner omc`를 명시하기 전까지 동작은 byte-identical**(ADR 0001 보존)
하다. omc 경로는 `runner == "omc"`일 때만 진입한다.

**왜 ack가 필요한가 (데이터 경계).** `omc team`은 per-worker sandbox / permission /
network 플래그를 노출하지 않는다 — 그 claude/codex CLI worker는 user **본인의 인증된 CLI**를
자체 DEFAULT 권한으로 실행하여 worktree의 비공개 데이터를 읽고 네트워크로 egress할 수 있다.
이는 in-repo runner의 명시적 `--sandbox read-only`(codex) / tool allowlist(claude)보다
**덜 통제된** 상태다. 또한 env 허용리스트가 ANTHROPIC_API_KEY 등 ENV-var 시크릿을 차단하더라도,
worker CLI는 HOME 아래 파일시스템 경로(~/.codex, ~/.claude, ~/.config/gh, ~/.aws)에서
독립적으로 자격증명을 로드한다 — **env 필터는 완전한 자격증명 경계가 아니다**.
따라서 omc runner는 **fail-closed**다: `ACTIVE_OMC_RUNNER_ACK=1`(상수 `OMC_RUNNER_ACK_ENV`)이
없으면 blocked `ActiveCodexRunnerResult`를 반환하고 **omc를 절대 spawn하지 않는다**(ADR 0061).
명시 ack는 운영자가 home-scoped 자격증명 접근 + 네트워크 egress를 의식적으로 수용했다는 의미다.

**거버넌스 재부과 + no-auto-merge.** adapter(`_run_omc_team_runner`)는 `omc team
N:claude,M:codex --no-decompose "<task>"`를 `OMC_TEAM_WORKTREE_MODE=branch` 환경으로
띄우되 **`--auto-merge`는 절대 넘기지 않는다**(worker commit이 leader/main 브랜치로 머지되면
안 됨). `<task>` 텍스트는 in-repo scrub helper로 먼저 privacy-scrub한다.

**poll + diff 캡처 (round-5 fix #1, round-6 fix #1 정정).** 완료 감지는
`omc team api get-summary --input '{"team_name":"<name>"}' --json` 응답의
`data.summary.tasks`를 폴링한다(`in_progress == 0, failed == 0, completed == total`이
terminal-success). `get-diff` API는 실 omc CLI에 존재하지 않는다.

**round-6 fix #1 [CRITICAL], round-8 fix #3 강화, round-10 fix #1 강화:** OMC worker는
per-worker branch에 **commit**하므로 `git diff HEAD`(uncommitted 전용)로는 캡처되지 않는다.
수정된 diff 캡처 절차:
1. `git -C <worktree> merge-base HEAD origin/main` → 분기 지점 base SHA 계산
2. **`git -C <worktree> add -A`** → worker가 생성한 신규(untracked) 파일을 staging에 포함
3. `git -C <worktree> diff --cached <base_sha>` → committed + staged + untracked 전체 캡처

**round-8 fix #3 [HIGH]:** merge-base 실패(원격 ref 없음, shallow clone) 시 `git diff HEAD`
fallback은 **삭제**됐다. `git diff HEAD`는 uncommitted 변경만 잡으므로 worker committed 변경이
전혀 캡처되지 않아 privacy/scope 검사를 우회한 false-empty completion이 된다. 이제 merge-base
실패 → **fail-closed**: blocker 기록 + blocked 반환. 운영자는 worker worktree에서 `origin/main`이
접근 가능한지 확인해야 한다.

**round-10 fix #1 [HIGH]:** `git diff <base_sha>`(인덱스 미포함)는 untracked 신규 파일을
표시하지 않는다. omc worker가 새 파일을 생성했을 때 privacy/scope 검사가 완전히 우회됐다.
수정: diff 직전에 `git add -A`를 실행해 untracked를 staged로 올리고,
`git diff --cached <base_sha>`로 diff. `git add -A` 실패 시 blocker + blocked.

worker 완료 후 캡처된 diff에 (1) privacy 재감사(`_privacy_findings_for_text` +
`audit_privacy_output`, 누출 시 blocked), (2) `claimed_files` scope 검사를 fail-closed로
재부과한다. **round-5 fix #2:** write lease에 `claimed_files`가 없는 상태로 proposed diff가
있으면 무조건 blocked. **round-6 fix #2:** scope 검사는 현재 `task_id`에 해당하는 lease만 사용
(`task_id` 필터링) — 다른 task의 stale lease로 검증하는 것을 차단; 매칭 lease가 정확히 1개가
아니면 blocked fail-closed. **round-7 fix #1:** lease의 `task_id` 필드가 현재 `task_id`와
**명시적으로** 일치해야 eligible — `task_id` 필드가 없는(legacy/unscoped) lease는 완전 거부.
**round-7 fix #3:** omc spawn **전** `_build_omc_task_text`가 선택된 모든 session의 assignment
파일이 존재하고 비어있지 않은지 확인한다. 파일 미존재 또는 빈 내용이면 pre-spawn fail-closed
반환(`invalidate_heartbeats=False`).
**round-10 fix #2 [HIGH]:** `_build_omc_task_text` 호출 직전에 선택된 sessions의 task_id
집합(`selected_task_ids`)을 검증한다. (1) 두 개 이상의 서로 다른 task_id → blocked fail-closed
("ambiguous: spans N distinct task IDs") — 여러 task의 assignment text가 단일 uncontrolled worker에
전달되는 것을 차단. (2) `--task X`가 제공되었으나 selected sessions의 task_id가 일치하지 않으면 →
blocked fail-closed ("mismatch: --task X does not match selected sessions"). 두 경우 모두 omc는
spawn되지 않는다(`invalidate_heartbeats=False`). scope 통과 후에는 codex patch 경로와 동일한 `patch_artifact.json`
모양으로 매핑한다. 그래서 diff는 **main으로 머지되지 않고** 기존 active-apply(integration branch) /
Conservative Gate / human-gated ship 경로로 그대로 흐른다. team은 finally 블록에서 항상
`omc team shutdown`으로 정리하며(**round-7 fix #2:** shutdown rc 확인 → nonzero 시 warning 기록 +
`omc team shutdown <team> --force` fallback(timeout=10s); `TimeoutExpired`도 동일 /
**round-8 fix #1:** `--force` 결과도 검사 — nonzero rc/stderr → "may still be running" warning,
`TimeoutExpired` 경로도 동일; raise 없음), omc 실패는 raise하지 않고 blocked 결과로 기록한다.
**round-8 fix #2 / round-9 fix #2 수정:** `_finalize_omc_runner_result`의 `elif execute:` 브랜치
(executed no-ack / executed pre-spawn block / executed empty diff)에서 run-specific `artifact_path`에도
blocked artifact를 쓴다 — `state.sessions[0].assignment` 경로를 통해 prior proposed artifact가 소비
되는 것을 방지한다. **`execute=False` (dry-run)은 artifact를 일체 건드리지 않는다** — dry-run은
read-only planning 액션으로, prior executed run이 생산한 proposed artifact를 지워서는 안 된다.

**round-9 fix #1 [CRITICAL]:** `_invalidate_omc_blocking_gate_heartbeats` 반환형이
`tuple[list[str], str | None]`(`(invalidated_roles, error_message)`)으로 변경됐다. 이전에는
`OSError`/파싱 실패를 `pass`로 삼켜 호출자가 "무효화 성공/없음"과 구별하지 못했다. 이제 `execute=True`
경로에서 `error_message != None`이면 `decision = "blocked"` + blocker가 추가된다 — registry 쓰기 실패로
stale reviewer/auditor heartbeat가 생존해 Conservative Gate가 오판(READY)하는 fail-open이 닫혔다.

`scripts/agent_loop.py`는 본 단계에서도 `LOAD_BEARING_PATHS`에 올리지 않는다
(ADR 0080/0085/0086 유지).

## Active Auto Loop

`active-start` + runner를 한 번만 실행하는 wrapper와 별개로, bounded 반복 드라이버는
다음 target이다.

```bash
make agent-loop-active-auto-loop
```

흐름은 `tasks/queue.md`에서 ready/todo/backlog task를 고르고, `active-start`로
expanded-eight ledger와 assignments를 쓴 뒤, `active-codex-runner`를 실행하고,
`gate-evidence`를 기록한다. `ACTIVE_AUTO_LOOP_EXECUTE_SHIP=1`일 때만 gate 통과 후
`active-loop --execute`를 호출한다.

중요한 완료 기준: runner 완료는 task 해결이 아니다. auto loop는
`ACTIVE_AUTO_LOOP_EXECUTE_SHIP=1`이면 `active-loop --execute`가 `executed`를 반환한
task만, 기본 ship-off 경로에서는 runner 완료 + conservative gate ready + privacy clean
조건을 모두 만족한 task만 `reports/agent_loop/active/auto_loop_state.json`의
`completed_task_ids`에 기록한다. 다음 iteration/다음 invocation은 그 task를 제외하고
다음 task를 고른다. 기본값은 runner 실행까지이며 ship은 꺼져 있다.

```bash
make agent-loop-active-auto-loop ACTIVE_AUTO_LOOP_MAX_ITERATIONS=3
make agent-loop-active-auto-loop ACTIVE_AUTO_LOOP_EXECUTE_SHIP=1 ACTIVE_AUTO_LOOP_MAX_ITERATIONS=3
```

### Infinite Mode

기본 `make 시작` 은 bounded wave 다 (`START_TASK_LIMIT=5`). ready task 큐가 빌
때까지 돌리려면 `START_INFINITE=1` 을 켠다 (ADR 0085).

```bash
make 시작 START_INFINITE=1
```

무한 모드는 iteration count / completed-target 상한을 버리고 **ready-queue 소진**
+ 안전 가드만으로 종료한다. 다음 ready task 가 없으면(큐 drained) 정상 종료이며
blocker 가 아니다. 직접 CLI 로는 `--max-iterations 0`(또는 `infinite`/`unlimited`)
가 동일하다.

안전 가드 (env override, 무한 모드 한정):

- `BIDMATE_AGENT_LOOP_MAX_CONSECUTIVE_BLOCKERS` (기본 3): 연속 blocked task 가 이
  수에 도달하면 중단. 완료가 한 번 끼면 streak 은 0 으로 리셋된다.
- `BIDMATE_AGENT_LOOP_MAX_WALL_CLOCK_SECONDS` (기본 0 = 비활성): wall-clock 상한
  opt-in. per-session 캡 (`--timeout-seconds`, `--max-commands-per-session`) 은
  기본 0 = **무제한** 이므로, 이 wall-clock 예산이 무한 모드의 **단일 opt-in hang
  backstop** 이다. 설정 시 남은 예산이 **codex runner subprocess timeout 과 Claude
  read/review lane subprocess timeout 양쪽** 으로 전달되어 (wall-clock 검사는 cycle
  사이에서만 돌아 blocking subprocess wait 를 직접 못 끊으므로) 어느 lane 에서 hang
  이 나도 끊는다. 초과 시 `wall_clock_exceeded` 플래그를 남긴다. 미설정(0)이면
  codex/Claude lane 양쪽 모두 timeout 이 걸리지 않는 truly unlimited 기본이다.
- blocked task 는 `deferred_task_ids` 로 기록되어 이번 run 에서 재선택되지 않는다.

안전 가드(연속 blocker / wall-clock)로 중단하면 run decision 은 `blocked` 다 —
가드 abort 는 `limit-reached`(성공) 가 아니다. 비정상 env 값(정수 아님/음수)은
무시하고 default 로 폴백한다.

`make 시작` 기본 `ACTIVE_AUTO_LOOP_EXECUTE_SHIP=0` 은 무한 모드에서도 유지된다 —
실제 ship 은 여전히 기존 human-gated 경로가 담당한다.

## Patch Write-Lane (codex, mutating)

read-only runner와 별개로, `active-codex-runner`는 opt-in `--mode patch`로 **codex
write-lane**을 돈다. read-only 8-session 모드는 불변이며, patch 모드는 write-lease
owner인 **Implementer** 한 세션만 대상으로 한다 (claude `-p` print mode는 비-streaming
직렬화 경로의 #1598 F4 버그로 Edit-tool 호출이 깨진다. stream-json transport로
회피 가능하나 2026-06-15 Anthropic 에이전트 크레딧 분리 정책으로 채택은 보류 —
실측 근거 + 정책 함의는 아래 표).

claude `-p` Edit-tool 실측 매트릭스 (`scripts/reproduce_claude_edit_tool.py`,
claude 2.1.3, 2026-05-28, 구독 OAuth 경로, raw artifact:
`reports/agent_loop/claude_edit_repro/`). CLI 2.1.3의 `--permission-mode`
choices는 `default`, `acceptEdits`, `bypassPermissions`, `plan`, `dontAsk`,
`delegate`이고, `--dangerously-skip-permissions`는 `bypassPermissions`의 별칭이다
(독립 모드 아님):

| Cell | permission-mode | output-format | tool flag | Symptom |
|---|---|---|---|---|
| 01 | acceptEdits | json | `--allowedTools Edit` | S2 `tool_use ids must be unique` |
| 02 | acceptEdits | json | `--allowedTools Edit` (explicit prompt) | S2 |
| 03 | bypassPermissions | json | `--allowedTools Edit` | S2 |
| 04 | bypassPermissions (alias `--dangerously-skip-permissions`) | json | (none) | S2 |
| 05 | acceptEdits | text | `--allowedTools Edit` | S2 |
| 06 | default (`--permission-mode` 생략) | json | `--allowedTools Edit` | S2 |
| 07 | acceptEdits | json | `--tools Edit,Read` | S3 (90 s timeout) |
| 08 | plan | json | `--allowedTools Edit` | S3 (90 s timeout) |

해석: 측정한 독립 permission 모드 3개(`default`, `acceptEdits`, `bypassPermissions`)와
그 alias(`--dangerously-skip-permissions`)에서 모두 동일한 `messages.N.content.M:
tool_use ids must be unique` API 400을 받았다. plan-mode와 `--tools` 빌트인 셋
형식 셀은 90s timeout(S3)으로 떨어졌는데, 같은 직렬화 경로의 다른 분기로 추정 —
plan-mode는 `EnterPlanMode`/`ExitPlanMode` tool-call이 일반 tool-call과 섞여 더
취약하고, `--tools` 빌트인 셋은 tool contract 변경으로 같은 취약 경로를 자극한다.

그러나 같은 `claude` 바이너리를 **streaming transport** (`--input-format
stream-json --output-format stream-json --verbose`)로 호출하면 같은 trivial
edit 태스크가 정상 동작한다. Python SDK (`claude-agent-sdk` 0.2.87, internal
`_is_streaming = True`) 매트릭스 (`scripts/reproduce_claude_sdk_edit.py`):

| Cell | SDK permission_mode | tool_use | edited | symptom |
|---|---|---|---|---|
| 09 | `default` | 2 | yes | S4_normal |
| 10 | `acceptEdits` | 2 | yes | S4_normal |
| 11 | `plan` | 4 | no | S4 (mode spec — mutation 없음, tool_use 발생) |
| 12 | `bypassPermissions` | 2 | yes | S4_normal |
| 13 | `dontAsk` | 2 | yes | S4_normal |
| 14 | `auto` | 2 | yes | S4_normal |

SDK 없이 wrapper가 직접 subprocess로 stream-json transport를 호출해도 동등한
결과 (`scripts/reproduce_claude_streamjson_subprocess.py`):

| Cell | permission_mode | tool_use | edited | symptom |
|---|---|---|---|---|
| 15 | `default` | 2 | yes | S4_normal |
| 16 | `acceptEdits` | 3 | yes | S4_normal |
| 17 | `plan` | 1 | no | S4 (mode spec) |
| 18 | `bypassPermissions` | 3 | yes | S4_normal |
| 19 | `dontAsk` | 0 | no | S0 invalid mode (CLI rejects; raw_lines=0) |
| 20 | `auto` | 0 | no | S0 invalid mode (CLI rejects; raw_lines=0) |

CLI 2.1.3의 실제 `--permission-mode` validation은 `acceptEdits / bypassPermissions
/ default / plan` 4개만 허용한다 (`--help` 출력의 `dontAsk / delegate`는 거짓 enum).
SDK가 `dontAsk / auto`를 통과시킨 이유는 stream-json mode에서의 validation 우회
또는 stdin control message 경로로 추정 — 부수적이며 본 결론과 무관.

따라서 #1598 F4는 **permission approval 정책 계층 문제가 아니라 `claude -p` print
mode의 비-streaming 직렬화 경로 한정 버그**로 단정한다. SDK든 wrapper 직접 subprocess든
`--input-format stream-json --output-format stream-json --verbose` transport로
호출하면 유효한 4개 mode 전부에서 정상 동작한다. **즉 wrapper-side 회피는 SDK 의존성
없이도 가능하다** — `scripts/agent_loop_claude_turn.py` 같은 어댑터의 build_command를
stream-json transport로 갈아끼우면 claude write-lane이 열린다.

채택은 별 결정이다. Anthropic의 2026-06-15 에이전트 크레딧 분리 정책은 SDK + MCP +
GitHub Actions 통합을 명시 타깃하지만 stream-json subprocess가 같은 통에 들어가는지는
공지로 명확하지 않다. 본 저장소의 write-lane은 codex가 이미 안정 동작하므로 dual-agent
도입의 본질적 필요가 없고, 측정 결과는 옵션으로만 보관한다 (선택지 보존, 채택 보류).

```bash
python3 scripts/agent_loop.py active-codex-runner --mode patch --task T-2026-00NN --execute
```

흐름 (어느 단계든 실패하면 fail-closed — mutation 없음):

1. **write-lease borrow**: lease의 `active_agent`를 `codex`로 차용한다. `claude`와
   `codex`는 상호배제(동시 보유 불가)이며 종료 시 `finally`에서 반환한다.
2. **scratch worktree**: `.claude/worktrees/T-N-codex` (브랜치 `agent/T-N/codex-scratch`)를
   base에서 만든다.
3. **assignment 주입**: `assignments/<session>.md`를 읽어 프롬프트에 embed한다.
   assignment가 없으면 차단한다 (모호한 프롬프트로 full-access codex가 임의 편집하는
   것을 방지).
4. **codex 실행**: `codex exec --cd <scratch> --sandbox <DEFAULT_PATCH_SANDBOX>`로 scratch
   안에서만 편집한다 (기본 `workspace-write`; `danger-full-access` 는 `ACTIVE_PATCH_SANDBOX`
   opt-in, ADR 0086 — 아래 Tool/Sandbox Policy 참조).
5. **diff 캡처**: `git add -A` + `git diff --cached`로 신규 untracked 파일까지 포함해
   patch를 캡처한다.
6. **claimed_files scope**: 변경 파일이 lease의 `claimed_files` 밖이면 verdict를
   `blocked`로 강등한다 (claim이 비어있으면 미강제 + warning).
7. **patch artifact**: `reports/agent_loop/active/patch_runs/<session>/patch_artifact.json`에
   기록하고, privacy는 redact-and-proceed (`_redact_private_json` → 재감사; 누수 적발 시
   fail-closed block, ADR 0005).
8. **teardown + release**: scratch worktree를 제거하고 lease를 반환한다.

patch 모드는 `session-heartbeat`를 pass로 승격하지 않으며, **integration 브랜치에
apply하지 않는다** (다음 단계).

### Tool/Sandbox Policy

ADR 0086 (narrowed / safe core) 는 lane 별 도구/샌드박스를 다음으로 고정한다 — lease/gate
read-write 분리를 보존한다.

- **Write lane (codex patch / Implementer)**: `DEFAULT_PATCH_SANDBOX` (env
  `ACTIVE_PATCH_SANDBOX`) 단일 출처. **기본 `workspace-write`** — scratch worktree 편집 +
  명령 실행(실제 작업), 네트워크 egress 없음 → scope/privacy gate 관측 + load-bearing ADR
  0005 경계 유지. **`danger-full-access`(codex no-sandbox: 네트워크·의존성 설치·임의 명령·
  scratch 밖 쓰기)는 `ACTIVE_PATCH_SANDBOX` 명시 opt-in** (gate 관측성 + ADR 0005 경계
  완화 → 기본 아님). write-lease owner 인 Implementer 한 세션만 scratch worktree 안에서 돈다.
- **Claude write lane = full-access opt-in 한정**: write 경로는 `write_agent` ∈ {codex,
  claude, auto} 를 지원하나, Claude Code CLI write lane 은 bypass-style 권한으로 돌아 codex
  OS 샌드박스(`DEFAULT_PATCH_SANDBOX`)를 **강제할 수 없다**. 기본 `workspace-write` 에서
  Claude write lane 을 돌리면 광고된 no-egress 정책보다 넓게 (조용히) 돌 수 있으므로,
  **resolved write agent = claude 이고 `DEFAULT_PATCH_SANDBOX != danger-full-access` 면
  fail-closed 로 차단**(Claude write lane 미spawn). 운영자가 명시적으로 `danger-full-access`
  로 opt-in 했을 때만(어차피 OS 샌드박스를 기대하지 않는 상태) Claude write lane 이 허용된다.
  codex write lane 동작은 변경 없음.
- **Read/review lane (claude & codex): read-only 불변**. allowlist 는 `Read`/`Grep`/`Glob`
  + git-read(`Bash(git diff:*)`/`Bash(git log:*)`/`Bash(git status:*)`)뿐이고, denylist 는
  모든 mutation/ship(`Edit`/`Write`/`NotebookEdit`/`Bash(git push:*)`/`Bash(git commit:*)`/
  `Bash(git merge:*)`/`Bash(gh:*)`) + blanket `Bash(make:*)` 를 차단한다. reviewer 는 코드를
  읽고 diff/log 를 보되, 테스트·빌드 실행이나 어떤 mutation 도 하지 않는다.

**lease/gate write 분리 보존**: 오직 Implementer write-lane 만 편집하고, 오직 orchestrator
apply 단계만 commit 한다. review lane 에는 git commit/push/gh 도구가 없으므로 conservative
gate 가 유지된다.

> **Deferred (follow-up PR)**: in-lane review verification(러뷰 lane 이 직접 `make smoke`/
> `pytest`/`bash scripts/test.sh` 를 돌려 verify-by-execution)은 보류한다. 이 검증 명령은
> tracked 공유 상태(`data/index`, `outputs/answer.json`)를 mutate 해 공유 worktree 를 더럽히고
> implementer 와 race 하므로, 안전한 in-lane 검증은 output isolation(mktemp + git-diff dirty
> check)이 선행돼야 한다 — 별도 follow-up PR 로 추적한다.

## Patch Apply (orchestrator)

`active-apply`는 patch artifact를 integration 브랜치에 적용하는 Orchestrator 단계다.
**main은 절대 건드리지 않고** push/ship도 하지 않는다.

```bash
python3 scripts/agent_loop.py active-apply --task T-2026-00NN --execute
```

- patch artifact (verdict `proposed` + non-empty diff)를 읽는다.
- integration worktree (`feature/T-N-integration` @ `.claude/worktrees/T-N-integration`)를
  보장한다.
- `git apply --check`로 게이트한다. **실패 시 fail-closed** (blocker, 부분 apply 없음).
- `--execute` + clean check일 때만 `git apply` + `git add -A` + `git commit`한다.
- dry-run(기본)은 check만 수행한다.

## Gate Evidence

`gate-evidence`는 한 task의 Conservative-Gate 통과 근거를 **감사 기록**으로 묶는다.
**ship/push/merge를 트리거하지 않는다** — 실제 ship은 기존 human-gated 경로(`ship-pr` /
`make ship-arm`)가 담당한다.

```bash
python3 scripts/agent_loop.py gate-evidence --task T-2026-00NN
```

`reports/agent_loop/active/gate_evidence/<task>/`에 `evidence.json` + 요약 `evidence.md`를
쓴다. 묶는 내용: topology + gate_policy, 필수 gate role의 pass 여부와 overall ready bool,
patch artifact(verdict/files/diffstat), apply state(decision/applied/integration_branch),
agent_mix Work Unit, privacy audit(clean/issue 수). raw private 값은 포함하지 않는다
(요약 메타만, ADR 0005). 누락 아티팩트는 `null`로 graceful 처리한다.

## Full Ship Gate

`--execute`는 gate가 통과할 때만 기존 ship runner를 호출한다.

```bash
python3 scripts/agent_loop.py active-loop --mode full-ship --execute --from-git
```

Gate 조건:

- current branch가 ADR 0007 issue-linked branch다.
- active lease가 `recovery-needed`가 아니다.
- overlap preflight가 blocked가 아니다.
- generated `reports/agent_loop/` artifact privacy audit가 clear다.
- load-bearing/eval surface는 claim text 또는 PR body evidence가 있다.
- `four-role`: `Reviewer`와 `CI/Eval Auditor` session heartbeat status가 pass 계열이다.
- `expanded-eight`: `Reviewer`, `CI / Regression Auditor`,
  `Eval / Claim / Privacy Auditor` status가 pass 계열이다.
- `expanded-eight`에서 load-bearing file이 바뀌면 `Deep Reviewer` status도 pass
  계열이어야 한다.

`Planner / Issue Triage`와 `Experiment Scout`는 Conservative Gate에서 ship을
막지 않는다. 둘은 다음 work 후보, 실험 가설, aggregate-only evidence를 만들고,
Orchestrator가 tracked queue/plan으로 승격할 때만 구현 lane으로 넘어간다.

통과하면 primary ship command는 다음이다.

```bash
make ship-run DRAFT=false REAL_EVAL=auto
```

Force-push는 active loop 범위 밖이다. Remote branch deletion은 Stage 5에서 open
stacked dependent PR을 먼저 확인하고, dependent가 있거나 확인 불가하면 skip한다.

## Heartbeat

각 session은 작업 중 주기적으로 heartbeat를 남긴다.

```bash
python3 scripts/agent_loop.py session-heartbeat \
  --session-id reviewer \
  --role Reviewer \
  --task T-2026-0000 \
  --status passed
```

Expanded topology 예시:

```bash
python3 scripts/agent_loop.py session-heartbeat \
  --session-id eval-claim-privacy-auditor \
  --role "Eval / Claim / Privacy Auditor" \
  --task T-2026-0000 \
  --status clear
```

기본 TTL은 30분이다. TTL을 넘은 session은 다음 orchestrator tick에서 `stale`로
표시된다.

## Worktree Prepare

새 role worktree는 dry-run으로 먼저 확인한다.

```bash
python3 scripts/agent_loop.py active-worktree-prepare \
  --issue 1578 \
  --role Implementer \
  --slug active-agent-loop
```

`--execute`를 붙이면 issue-linked branch/worktree를 만든다. `--title`을 사용하면
먼저 GitHub issue를 생성한 뒤 그 번호로 branch/worktree를 만든다.
