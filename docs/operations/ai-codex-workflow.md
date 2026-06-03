# AI Codex Workflow

이 문서는 ChatGPT + Codex 반복 작업을 결정 표면별로 나누는 운영 계약이다.
목표는 사람이 매번 repo 상태, readiness audit, open PR 상태를 다시 읽고 다음
Codex 작업을 손으로 고르는 비용을 줄이는 것이다.

## Roles

| Role | Responsibility |
|---|---|
| ChatGPT | Planner/reviewer. repo 상태, readiness aggregate, PR corpus를 읽고 다음 workset/task lane을 계획한다. |
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

- `reports/ai_next_actions.md`: 현재 상태와 최우선 Codex workset task
- `reports/ai_next_actions.html`: 사람이 빠르게 보는 현재 상태판
- `reports/codex_tasks/*.md`: Codex에게 넘길 scoped workset task briefs

`reports/*`는 기본 gitignore 대상이므로 이 산출물은 로컬 workflow artifact다.
committable evidence가 필요하면 별도 redacted aggregate 산출물로 승격해야 한다.

## Agent Gate Review Surface

`reports/ai_next_actions.html`은 agent용 Markdown을 사람이 읽는 review surface로
투영한 정적 HTML이다. 같은 planner 결과에서 생성되므로 Markdown task brief와
판단 순서가 다르면 안 된다.

ADR 0079 이후 이 화면은 매번 사용자 승인을 받기 위한 human gate가 아니라,
Codex가 보수적 agent gate를 집행하기 위한 evidence board다. 애매한 경우 기본값은
`draft`, `no performance claim`, `follow-up issue`, `fail closed`다.

HTML 화면에서 먼저 볼 항목은 다음 네 가지다. 여기서 `Top task`는 open PR 중
하나를 고르는 값이 아니라, PR corpus 전체에서 합성된 운영 workset이다.

| Area | What to decide |
|---|---|
| Top task | 지금 검토하거나 실행할 workset task |
| Page citation claim | page-level claim을 해도 되는지 여부 |
| Private delta needed | load-bearing 변경의 private delta evidence 필요 여부 |
| Privacy guard | 입력 artifact가 aggregate/redacted boundary를 지켰는지 여부 |

RFP 평가 루프의 환경 축, metric suite, adoption criteria, 종료 조건은
[Agent-Gated RFP Evaluation Loop](../evaluation/agent-gated-rfp-eval-loop.md)를 따른다.

HTML은 로컬 상태판이며 PR 증거(evidence)가 아니다. PR에 인용할 수 있는 것은
HTML 자체가 아니라 source aggregate artifact, 실행 command, diff, ADR/source-of-truth
일치 여부다.

## Overlap Preflight

Codex가 파일을 편집하기 전에 같은 issue/branch/PR/worktree가 이미 진행 중인지
확인한다. 이 check는 report-only이며 branch switch, push, PR 생성/머지/닫기,
issue close, branch delete를 실행하지 않는다. Coordination surface는 Codex와
Claude Code를 분리하지 않는다. 루트 checkout, `.codex/worktrees/*`,
`.claude/worktrees/*`, 그리고 `git worktree list`에 잡히는 외부 worktree는
모두 같은 “다른 세션” 후보로 취급한다.

```bash
python3 scripts/agent_loop.py overlap-preflight \
  --issue <N> \
  --branch <type>/issue-<N>-<slug>
```

`blocked`이면 현재 작업을 시작하지 않는다. 예: 같은 issue의 open PR이 있거나,
다른 worktree가 같은 issue branch를 소유하거나, 현재 checkout이 detached/stale인
경우다. `warn`이면 branch/PR history를 사람이 볼 수 있는 report로 확인하고,
예상 변경 파일이 다른 세션의 dirty/diff 파일과 겹치지 않는다는 근거를 남긴 뒤
진행한다. 근거를 만들 수 없으면 다른 issue를 고른다.

### Orphan Worktree Warnings

pre-push hygiene가 “branch already merged into main, but the worktree was never removed”를 보고해도,
현재 PR과 무관한 다른 세션의 worktree를 opportunistic cleanup하지 않는다. 경고는 push를 막지 않는
soft warning이며, 정리는 전용 경로(`make worktree-cleanup-dry-run` → `make worktree-cleanup`)나
SessionStart hygiene([ADR 0096](../adr/0096-auto-worktree-branch-cleanup.md))에 맡긴다.
즉시 정리해야 한다면 self-skip/clean/merged-confirmed 조건을 확인하고, 원격 branch
삭제는 stacked dependent 확인 없이는 하지 않는다.

## Classification Contract

Planner는 open PR을 선택 후보 목록으로 다루지 않는다. PR의 CI, draft 여부,
review 상태, merge blocker, stale/superseded 신호를 corpus/evidence로 읽고
다음 순서로 active workset을 분류한다. PR별 1:1 task 생성을 기본값으로 삼지
않고, 같은 운영 문제를 공유하는 PR들을 하나의 lane task로 묶는다.

| Classification | Meaning |
|---|---|
| `failed_experiment` | NO-GO 또는 negative experiment 신호가 있는 PR lane을 문서화한다. |
| `close_superseded` | stale/superseded draft PR lane을 cleanup task로 묶는다. |
| `blocked` | requested changes, merge blocker, failing check, missing PR JSON field가 있는 blocked lane을 triage한다. |
| `needs_private_delta` | private delta evidence가 필요한 PR 또는 load-bearing claim lane을 준비한다. |
| `ready_for_review` | blocker-free PR들을 ship/review lane으로 묶는다. |
| `next_experiment_candidate` | draft/measurement 후보들을 다음 workset으로 이어간다. |

각 task brief는 `Source PRs`, `Workset`, `Lane`, `Role Hints`,
`Completion Proof`를 포함한다. `Source PRs`는 근거가 된 PR 번호 목록이며,
그 PR 중 하나를 선택했다는 뜻이 아니다.

## Batch And Role Dispatch

`scripts/agent_loop.py batch-plan`은 `reports/agent_loop/codex_tasks/*.md`를
읽어 workset 단위 JSON을 만든다.

```bash
python3 scripts/agent_loop.py batch-plan
```

`batch_plan.json`의 각 item은 `workset_id`, `lane`, `source_prs`,
`role_hints`, `completion_proof`를 포함한다. lane은 다음 네 종류다.

| Lane | Meaning |
|---|---|
| `serial` | 같은 file/surface/dependency 또는 blocker를 공유해 순차 처리한다. |
| `parallel-safe` | 독립 surface라 병렬 구현 또는 탐색이 가능하다. |
| `review-only` | 구현보다 review/ship evidence 확인이 우선이다. |
| `manual-gated` | 내부적으로는 agent-gated lane이며 private eval, claim, remote mutation 같은 보수 gate를 요구한다. |

`role-dispatch --batch reports/agent_loop/batch_plan.json`은 workset별
Planner, Implementer, Reviewer, CI Reviewer, Benchmark Auditor, Privacy
Auditor, Deep Reviewer prompt source를 만든다. root session은 integration,
validation, ship gate만 맡고, 이 보고서는 subagent를 실행하거나 remote mutation을
하지 않는다.

## Continue Loop

`continue-loop`는 정상 루프에서 사람이 다음 일을 고르지 않도록 상위 command를
제공한다.

```bash
python3 scripts/agent_loop.py continue-loop
```

흐름은 `pr-scan -> next-from-prs -> batch-plan -> role-dispatch ->
draft/apply queue-plan -> loop-state`다. 기본 동작은 내부 agent gate가 통과한
queue/plan draft를 tracked queue/plan docs에 반영한다. 이 command는 push, PR
create/merge/close, issue close, branch delete, force-push, private eval 실행,
benchmark/performance claim 승인을 하지 않는다. remote mutation은 기존 ship
gate와 `make ship-arm` 경로로 넘긴다.

RAG 성능 개선 loop에서는 `continue-loop`를 사람이 다음 일을 고르는 UI가 아니라
agent가 다음 queue/plan/preflight 증거를 만드는 표면으로 본다. 사람의 역할은
실행자가 아니라 claim boundary, conservative gate, merge readiness를 double-check하는
검증자다.

Page citation claim은 readiness summary의 page metadata gate가 `NO-GO`이거나
missing page metadata rate가 `1.0`이면 NO-GO로 취급한다. 이 경우 planner는
page-aware parser/index rebuild 작업을 Codex 후보로 만든다.

## Privacy Boundary

Planner는 raw private content를 렌더링하지 않는다. 입력에서 forbidden raw/private
field가 발견되면 값이나 키 목록을 출력하지 않고, sanitized input이 있었다는
상태만 표시한다. reviewer-facing 문서에는 aggregate 또는 redacted artifact만
사용한다.
