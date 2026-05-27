# Active Agent Loop

이 문서는 `agent_loop.py active-loop`가 운영하는 4-session active
orchestrator 계약이다. 목적은 사람이 다음 세션을 계속 수동 배정하지 않아도,
repo-local ledger가 작업권(lease), 하트비트(heartbeat), 할당(assignment), ship
gate를 보존하게 하는 것이다.

## Topology

기본 topology는 고정 4개 session이다.

| Session | Role | Write authority |
|---|---|---|
| `orchestrator` | Orchestrator | ledger, queue/plan proposal, gate decision |
| `implementer` | Implementer | assigned issue branch/worktree only |
| `reviewer` | Reviewer | read-only review report |
| `ci-eval-auditor` | CI/Eval Auditor | read-only CI/eval/claim report |

Worker 간 direct communication은 필요 조건이 아니다. 모든 이어받기는
`reports/agent_loop/active/` ledger와 기존 handoff block으로 복구 가능해야 한다.

## Ledger

`reports/agent_loop/active/`는 ignored operational state다. Review evidence로
그 자체를 커밋하지 않는다.

- `session_registry.json`: session id, role, task, branch, status, last heartbeat,
  next command.
- `leases.json`: task/issue/branch/worktree 단위 write lease, claimed files,
  owner session, expiry, recovery command.
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
- `Reviewer`와 `CI/Eval Auditor` session heartbeat status가 pass 계열이다.

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
