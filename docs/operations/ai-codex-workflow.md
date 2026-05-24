# AI Codex Workflow

이 문서는 ChatGPT + Codex 반복 작업을 결정 표면별로 나누는 운영 계약이다.
목표는 사람이 매번 repo 상태, readiness audit, open PR 상태를 다시 읽고 다음
Codex 작업을 손으로 고르는 비용을 줄이는 것이다.

## Roles

| Role | Responsibility |
|---|---|
| ChatGPT | Planner/reviewer. repo 상태, readiness aggregate, PR 상태를 읽고 다음 작업을 고른다. |
| Codex | Scoped executor. 한 번에 하나의 좁은 task를 구현하고 focused verification을 남긴다. |
| GitHub | State store. issue, PR, review, CI, merge state를 보관한다. |
| Human | Merge authority. 최종 merge와 scope 판단의 책임자는 사람이다. |

## Planner Surface

`scripts/ai_next_actions.py`는 외부 LLM API를 호출하지 않는 deterministic planner다.
입력은 public-safe aggregate readiness summary/report와 `gh pr list --json ...`
export다. 스크립트는 기본적으로 다음 로컬 생성물을 쓴다.

```bash
python3 scripts/ai_next_actions.py \
  --readiness-summary experiments/private_runs/readiness_audit/readiness_summary.json \
  --readiness-report experiments/private_runs/readiness_audit/readiness_report.md \
  --pr-json tmp/open-prs.json
```

- `reports/ai_next_actions.md`: 현재 상태와 최우선 Codex task
- `reports/codex_tasks/*.md`: Codex에게 넘길 scoped task briefs

`reports/*`는 기본 gitignore 대상이므로 이 산출물은 로컬 workflow artifact다.
committable evidence가 필요하면 별도 redacted aggregate 산출물로 승격해야 한다.

## Classification Contract

Planner는 다음 순서로 active work를 분류한다.

| Classification | Meaning |
|---|---|
| `blocked` | readiness blocker, requested changes, merge blocker, failing check가 있다. |
| `needs_private_delta` | private delta evidence가 필요한 PR 또는 load-bearing change가 있다. |
| `ready_for_review` | blocker-free 상태라 reviewer handoff가 가능하다. |
| `failed_experiment` | NO-GO 또는 negative experiment 신호가 있다. |
| `next_experiment_candidate` | 위 신호가 없으므로 다음 측정 후보를 고른다. |

Page citation claim은 readiness summary의 page metadata gate가 `NO-GO`이거나
missing page metadata rate가 `1.0`이면 NO-GO로 취급한다. 이 경우 planner는
page-aware parser/index rebuild 작업을 Codex 후보로 만든다.

## Privacy Boundary

Planner는 raw private content를 렌더링하지 않는다. 입력에서 forbidden raw/private
field가 발견되면 값이나 키 목록을 출력하지 않고, sanitized input이 있었다는
상태만 표시한다. reviewer-facing 문서에는 aggregate 또는 redacted artifact만
사용한다.
