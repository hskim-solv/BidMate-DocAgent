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

Korean alias도 같은 동작을 한다.

```bash
make 시작
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

runner는 session마다 `reports/agent_loop/active/codex_runs/<session_id>/` 아래에
`prompt.md`, `stdout.jsonl`, `stderr.log`, `last_message.md`를 둔다. 기본 sandbox는
`read-only`이고, 각 prompt는 assignment의 read-only 부분만 실행하게 제한한다.
Execute mode는 8개 process를 spawn한 뒤 종료 코드와 last message artifact가 남도록
각 process를 wait한다. 이 runner는 `session-heartbeat`를 pass로 승격하지 않고,
`active-loop --execute`의 ship gate나 `make ship-run`도 호출하지 않는다. 따라서
agent process가 끝났다는 사실은 reviewer/auditor gate 통과 근거가 아니며, gate
status는 별도 heartbeat나 검토 표면에서 유지한다.

## Patch Write-Lane (codex, mutating)

read-only runner와 별개로, `active-codex-runner`는 opt-in `--mode patch`로 **codex
write-lane**을 돈다. read-only 8-session 모드는 불변이며, patch 모드는 write-lease
owner인 **Implementer** 한 세션만 대상으로 한다 (claude `-p` headless는 모든 permission
모드에서 Edit-tool이 깨지므로 write-lane은 codex 전용).

```bash
python3 scripts/agent_loop.py active-codex-runner --mode patch --task T-2026-00NN --execute
```

흐름 (어느 단계든 실패하면 fail-closed — mutation 없음):

1. **write-lease borrow**: lease의 `active_agent`를 `codex`로 차용한다. `claude`와
   `codex`는 상호배제(동시 보유 불가)이며 종료 시 `finally`에서 반환한다.
2. **scratch worktree**: `.claude/worktrees/T-N-codex` (브랜치 `agent/T-N/codex-scratch`)를
   base에서 만든다.
3. **assignment 주입**: `assignments/<session>.md`를 읽어 프롬프트에 embed한다.
   assignment가 없으면 차단한다 (모호한 프롬프트로 workspace-write codex가 임의 편집하는
   것을 방지).
4. **codex 실행**: `codex exec --cd <scratch> --sandbox workspace-write`로 scratch
   안에서만 편집한다.
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
