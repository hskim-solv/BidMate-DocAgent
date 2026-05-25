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

| Status | Meaning |
|---|---|
| `backlog` | 아직 ready가 아니다. goal은 있으나 acceptance/evidence가 부족할 수 있다. |
| `ready` | 바로 시작 가능하다. scope, non-goals, acceptance, validation이 있다. |
| `running` | agent가 실행 중이다. owner role과 latest handoff가 있어야 한다. |
| `blocked` | external decision, missing data, failed validation 등으로 멈췄다. |
| `review` | 구현은 끝났고 reviewer/deep reviewer/benchmark auditor 검토가 필요하다. |
| `done` | evidence와 PR/commit/link가 남아 완료됐다. |

## Operating Rules

- 새 multi-session 작업은 `queue.md`에 task entry를 남긴다.
- 큰 작업은 [`docs/plans/TEMPLATE.md`](../docs/plans/TEMPLATE.md)를 복사해 plan doc를 만든다.
- Eval/benchmark task는 [`docs/evaluation/surface-map.md`](../docs/evaluation/surface-map.md)의
  surface와 allowed claim을 적는다.
- Review 요청 전 [`docs/reviews/ai-review-checklists.md`](../docs/reviews/ai-review-checklists.md)의
  필요한 checklist를 선택한다.
- 완료 후 task entry에 validation command와 evidence link를 남긴다.

## Minimal Entry

```markdown
## T-YYYY-NNNN — Title

- Status:
- Owner role:
- Goal:
- Plan:
- Acceptance criteria:
- Validation commands:
- Evidence required:
```
