# Task Queue

이 디렉터리는 AI-agent가 세션을 넘어 이어서 작업할 수 있도록 유지하는 작은
repo-local task queue다. GitHub issue를 대체하지 않는다. 목적은 "다음 작업이
무엇인지, 어떤 역할(role)로 수행해야 하는지, 어떤 evidence가 필요한지"를
빠르게 읽게 하는 것이다.

## Files

- [`queue.md`](queue.md): active task queue. 상태(status)는 여기서 관리한다.
- [`TEMPLATE.md`](TEMPLATE.md): 새 task 작성 템플릿.
- [`examples/`](examples/): realistic example task. 실제 backlog가 아니라 운영 예시다.

## Status

허용 status 값은 아래 6개뿐이다. 예시 파일도 실제 status 값은 이 목록 중 하나를
사용한다.

| Status | Meaning |
|---|---|
| `backlog` | 아직 ready가 아니다. goal은 있으나 acceptance/evidence가 부족할 수 있다. |
| `ready` | 바로 시작 가능하다. scope, non-goals, acceptance, validation이 있다. |
| `running` | agent가 실행 중이다. owner role과 latest handoff가 있어야 한다. |
| `blocked` | external decision, missing data, failed validation 등으로 멈췄다. |
| `review` | 구현은 끝났고 reviewer/deep reviewer/benchmark auditor 검토가 필요하다. |
| `done` | evidence와 PR/commit/link가 남아 완료됐다. |

## How Agents Pick Work

1. `tasks/queue.md`를 연다.
2. `Ready Order`에서 status가 `ready`인 첫 task를 고른다.
3. task의 `Scope`, `Non-Goals`, `Evidence Required`, `Failure Conditions`를 먼저 읽는다.
4. 파일을 편집하기 전에 `python3 scripts/agent_loop.py overlap-preflight --issue <N> --branch <type>/issue-<N>-<slug>`로 같은 issue/branch/PR/worktree가 이미 진행 중인지 확인한다.
   이때 Codex, Claude Code, 루트 checkout, `.codex/worktrees/*`, `.claude/worktrees/*`, 그리고 `git worktree list`에 잡히는 외부 worktree를 모두 같은 coordination surface로 본다.
5. preflight가 `blocked`이면 그 task를 시작하지 말고 다른 issue를 고른다.
   `warn`이면 branch/PR history 경고를 기록하고, 파일 겹침이 없는지 확인한 뒤 진행한다.
6. 시작 시 status를 `running`으로 바꾸고 `Handoff Notes`에 branch/worktree와 첫 명령을 남긴다.
7. 끝나면 status를 `review` 또는 `done`으로 바꾸고 validation output, artifact, PR/commit link를 남긴다.

`backlog` task는 missing decision이나 validation이 남아 있다는 뜻이다. agent는
`backlog`를 임의로 실행하지 말고 ready 조건을 먼저 채운다.

## Required Task Schema

모든 task는 아래 필드를 포함한다.

- `ID`
- `Title`
- `Status`
- `Owner role`
- `Goal`
- `Context`
- `Scope`
- `Non-Goals`
- `Acceptance Criteria`
- `Validation Commands`
- `Evidence Required`
- `Failure Conditions`
- `Related Plan / Issue / PR Links`
- `Handoff Notes`

## Operating Rules

- 새 multi-session 작업은 `queue.md`에 task entry를 남긴다.
- 큰 작업은 [`docs/plans/TEMPLATE.md`](../docs/plans/TEMPLATE.md)를 복사해 plan doc를 만든다.
- Eval/benchmark task는 [`docs/evaluation/surface-map.md`](../docs/evaluation/surface-map.md)의
  surface와 allowed claim을 적는다.
- Review 요청 전 [`docs/reviews/ai-review-checklists.md`](../docs/reviews/ai-review-checklists.md)의
  필요한 checklist를 선택한다.
- 완료 후 task entry에 validation command와 evidence link를 남긴다.
- 실패 조건(failure condition)에 닿으면 추측으로 계속하지 말고 status를 `blocked`로
  바꾼 뒤 관측된 error와 다음 확인 명령을 남긴다.

## Minimal Entry

```markdown
## T-YYYY-NNNN — Title

- ID:
- Title:
- Status:
- Owner role:
- Goal:
- Context:
- Scope:
- Non-Goals:
- Acceptance Criteria:
- Validation Commands:
- Evidence Required:
- Failure Conditions:
- Related Plan / Issue / PR Links:
- Handoff Notes:
```
