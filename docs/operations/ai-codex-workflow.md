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
| Conservative agent gate | [ADR 0079](../adr/0079-agent-gated-offline-online-rfp-eval-loop.md)의 정책을 집행한다. routine merge, claim, private eval, cleanup 판단은 사람에게 매번 묻지 않고 보수적으로 처리한다. |
| Human | Policy owner. 기본 정책을 바꾸거나 agent gate를 중단시키는 최종 책임자다. |

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
- `reports/ai_next_actions.html`: 사람이 빠르게 보는 현재 상태판
- `reports/codex_tasks/*.md`: Codex에게 넘길 scoped task briefs

`reports/*`는 기본 gitignore 대상이므로 이 산출물은 로컬 workflow artifact다.
committable evidence가 필요하면 별도 redacted aggregate 산출물로 승격해야 한다.

## Agent Gate Review Surface

`reports/ai_next_actions.html`은 agent용 Markdown을 사람이 읽는 review surface로
투영한 정적 HTML이다. 같은 planner 결과에서 생성되므로 Markdown task brief와
판단 순서가 다르면 안 된다.

ADR 0079 이후 이 화면은 매번 사용자 승인을 받기 위한 human gate가 아니라,
Codex가 보수적 agent gate를 집행하기 위한 evidence board다. 애매한 경우 기본값은
`draft`, `no performance claim`, `follow-up issue`, `fail closed`다.

HTML 화면에서 먼저 볼 항목은 다음 네 가지다.

| Area | What to decide |
|---|---|
| Top task | 지금 검토하거나 실행할 단일 작업 |
| Page citation claim | page-level claim을 해도 되는지 여부 |
| Private delta needed | load-bearing 변경의 private delta evidence 필요 여부 |
| Privacy guard | 입력 artifact가 aggregate/redacted boundary를 지켰는지 여부 |

RFP 평가 루프의 환경 축, metric suite, adoption criteria, 종료 조건은
[Agent-Gated RFP Evaluation Loop](../evaluation/agent-gated-rfp-eval-loop.md)를 따른다.

HTML은 로컬 상태판이며 PR 증거(evidence)가 아니다. PR에 인용할 수 있는 것은
HTML 자체가 아니라 source aggregate artifact, 실행 command, diff, ADR/source-of-truth
일치 여부다.

## Classification Contract

Planner는 다음 순서로 active work를 분류한다.

| Classification | Meaning |
|---|---|
| `failed_experiment` | NO-GO 또는 negative experiment 신호가 있다. |
| `close_superseded` | stale/superseded draft PR을 active review 후보에서 제거해야 한다. |
| `blocked` | readiness blocker, requested changes, merge blocker, failing check가 있다. |
| `needs_private_delta` | private delta evidence가 필요한 PR 또는 load-bearing change가 있다. |
| `ready_for_review` | blocker-free 상태라 reviewer handoff가 가능하다. |
| `next_experiment_candidate` | 위 신호가 없으므로 다음 측정 후보를 고른다. |

Page citation claim은 readiness summary의 page metadata gate가 `NO-GO`이거나
missing page metadata rate가 `1.0`이면 NO-GO로 취급한다. 이 경우 planner는
page-aware parser/index rebuild 작업을 Codex 후보로 만든다.

## Privacy Boundary

Planner는 raw private content를 렌더링하지 않는다. 입력에서 forbidden raw/private
field가 발견되면 값이나 키 목록을 출력하지 않고, sanitized input이 있었다는
상태만 표시한다. reviewer-facing 문서에는 aggregate 또는 redacted artifact만
사용한다.
