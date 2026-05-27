# AI Engineering Operating System

이 문서는 BidMate-DocAgent에서 장기 AI-agent 작업을 운영하는 최소 운영체계다.
기존 규칙의 단일 출처(source of truth)는 계속 [`CLAUDE.md`](../../CLAUDE.md),
[`docs/engineering-governance.md`](../engineering-governance.md),
[`docs/adr/README.md`](../adr/README.md)다. 이 문서는 새 규칙을 크게 추가하지
않고, 역할(role) -> 태스크(task) -> 계획(plan) -> 구현(implementation) ->
검토(review) -> 평가(evaluation) 근거(evidence)를 한 흐름으로 연결한다.

## Repository Audit

### 현재 강점

- RFP 문서 인텔리전스라는 도메인 경계가 명확하다. 범용 AI 실험장이 아니라
  ingestion -> 청킹(chunking) -> 검색(retrieval) -> 재순위(reranking) ->
  근거(evidence) -> 답변(answer) -> 평가(evaluation) 파이프라인이다.
- ADR 0001/0003/0005 등 핵심 계약(contract)이 살아 있고,
  [`scripts/_governance.py`](../../scripts/_governance.py)가 load-bearing path와
  여러 governance gate의 단일 출처다.
- CI는 `pytest`, public fixture smoke eval, latency SLO, branch/issue convention,
  baseline provenance, PR §5b real-data delta를 분리해서 검증한다.
- private real-eval은 raw data/per-case output을 커밋하지 않고 aggregate-only
  산출물만 허용하는 경계가 있다.
- [`docs/audits/`](../audits/)와 [`docs/self-review/`](../self-review/)는
  측정이 틀릴 수 있음을 문서화해 과대주장(over-claim)을 줄인다.

### 현재 약점

- AI-agent가 "지금 무엇을 해야 하는가"를 찾는 진입점이 GitHub issue, audit,
  local TODO, PR review에 흩어져 있었다.
- 계획(plan) 문서가 worktree/session 밖으로 항상 남지는 않아 context compaction
  이후 같은 결정을 다시 탐색했다.
- reviewer checklist가 PR 템플릿, ADR, audit 문서에 흩어져 있어 리뷰어 역할을
  맡은 agent가 무엇을 공격적으로 확인해야 하는지 즉시 알기 어려웠다.
- `reports/eval_summary.json`, `reports/real100/eval_summary.json`,
  `artifacts/runs/*/metrics/eval_summary.json`가 모두 존재할 수 있어 잘못된
  산출물을 비교할 위험이 있다.
- `benchmark`, `real-eval`, `smoke`라는 말이 여러 실행 표면(surface)에 걸쳐
  쓰여 장기 agent가 매번 의미를 재구성해야 한다.

### Workflow Bottlenecks

- 장기 작업의 Definition of Ready가 issue/ADR/문서에 분산되어 있다.
- 구현자(implementer)가 plan 없이 큰 범위를 건드리면 `rag_core.py`, `eval/`,
  benchmark 문서가 drift하기 쉽다.
- 리뷰어(reviewer)는 "테스트 통과"와 "claim validity"를 분리해 검토해야 하지만,
  현재 시작점이 명확하지 않다.
- benchmark auditor 역할이 암묵적이라 synthetic-only success나 metric inflation을
  초기에 차단하기 어렵다.

### Likely Failure Modes

- Public fixture smoke 결과를 성능(performance) 주장으로 확대한다.
- Synthetic benchmark 결과를 real-world RFP 성능처럼 표현한다.
- `make real-eval`의 deterministic hashing 경로를 dense/hybrid 검색 품질 근거로
  오해한다. Semantic retrieval claim은 `make real-eval-semantic` 또는 명시적
  semantic index provenance가 필요하다.
- `naive_baseline`, answer dict schema, ADR 0005 privacy boundary 같은 invariant를
  작은 refactor 안에서 조용히 바꾼다.
- AI-agent가 새 abstraction을 만들지만 기존 helper/contract를 재사용하지 않는다.
- Long session에서 ADR 번호, PR base, private artifact 위치, pending eval 상태가
  사라져 같은 결정을 반복한다.

### Minimum Viable Intervention

최소 운영체계는 다음 네 가지다.

1. [`tasks/queue.md`](../../tasks/queue.md): 세션을 넘어 읽히는 작은 task queue.
2. [`docs/plans/TEMPLATE.md`](../plans/TEMPLATE.md): 큰 작업을 self-contained하게
   만드는 plan doc 형식.
3. [`docs/reviews/ai-review-checklists.md`](../reviews/ai-review-checklists.md):
   normal/adversarial/benchmark/regression/docs review 체크리스트.
4. [`docs/evaluation/surface-map.md`](../evaluation/surface-map.md): smoke,
   synthetic benchmark, private real-eval의 claim boundary.

이 네 가지가 없으면 미래 agent는 다음 질문에 답하기 어렵다: 다음 작업은 무엇인가,
내 역할은 무엇인가, 어떤 plan을 따라야 하는가, 어떤 근거를 남겨야 하는가,
어떤 claim이 허용되는가, 어떤 checklist가 내 작업을 검토할 것인가.

## Source Of Truth Map

| 관심사 | 단일 출처 | 이 문서의 역할 |
|---|---|---|
| repo-wide agent 규칙 | [`CLAUDE.md`](../../CLAUDE.md), [`AGENTS.md`](../../AGENTS.md) | 긴 작업 시작 시 어디를 읽을지 연결 |
| engineering lifecycle | [`docs/engineering-governance.md`](../engineering-governance.md) | lifecycle에 task/plan/review artifact 추가 |
| multi-agent ownership | [`docs/multi-agent-ownership.md`](../multi-agent-ownership.md) | 역할(role)과 파일 소유권(owner)을 연결 |
| load-bearing path | [`scripts/_governance.py`](../../scripts/_governance.py) | task/plan의 validation 기대치로 참조 |
| eval split | [ADR 0005](../adr/0005-eval-split-public-synthetic-private-local.md), [`docs/evaluation/surface-map.md`](../evaluation/surface-map.md) | claim 허용/금지 정책을 운영 레벨로 노출 |
| active task state | [`tasks/queue.md`](../../tasks/queue.md) | 세션 간 handoff 상태 저장 |
| large-work plan | [`docs/plans/`](../plans/) | context loss 후 이어서 구현 가능한 설계 단위 |
| review gate | [`docs/reviews/ai-review-checklists.md`](../reviews/ai-review-checklists.md) | reviewer/deep reviewer/benchmark auditor가 사용할 기준 |

## Operating Questions

| 질문 | 답하는 문서 |
|---|---|
| What should I work on next? | [`tasks/queue.md`](../../tasks/queue.md)의 `Ready Order` |
| What role am I acting as? | 이 문서의 [Agent Role Model](#agent-role-model) |
| What plan should I follow? | task의 plan link 또는 [`docs/plans/TEMPLATE.md`](../plans/TEMPLATE.md) |
| What evidence must I produce? | task의 `Evidence Required`와 plan의 `Validation Strategy` |
| What claims am I allowed to make? | [`docs/evaluation/surface-map.md`](../evaluation/surface-map.md) |
| What review checklist will be used? | [`docs/reviews/ai-review-checklists.md`](../reviews/ai-review-checklists.md) |
| How do I continue after context loss? | [`docs/operations/long-session-workflow.md`](./long-session-workflow.md) |
| How do I avoid corrupting evals? | ADR 0005, `surface-map.md`, Benchmark Validity Audit |

## Definition Of The Minimum Viable Operating System

Minimum viable operating system은 다음 조건을 만족하면 충분하다.

- Agent가 [`tasks/queue.md`](../../tasks/queue.md)를 읽고 다음 실행 가능한 task를
  찾을 수 있다.
- Task가 큰 범위면 [`docs/plans/TEMPLATE.md`](../plans/TEMPLATE.md)를 따른 plan
  doc가 있고, plan이 acceptance criteria와 validation command를 포함한다.
- Implementer는 task와 plan의 scope/non-goals 밖으로 나가지 않는다.
- Reviewer는 [`docs/reviews/ai-review-checklists.md`](../reviews/ai-review-checklists.md)의
  checklist로 test pass theater, fake abstraction, benchmark contamination,
  unverifiable claim을 공격적으로 확인한다.
- Evaluation 관련 claim은 [`docs/evaluation/surface-map.md`](../evaluation/surface-map.md)의
  surface별 허용 claim을 따른다.
- Long session은 [`docs/operations/long-session-workflow.md`](./long-session-workflow.md)의
  handoff block을 남긴다.

## Agent Role Model

| Role | 책임 | 입력 | 출력 | 하지 말아야 할 것 | Handoff |
|---|---|---|---|---|---|
| Planner | self-contained work를 정의하고 scope를 줄인다 | issue/idea, audits, ADR, current queue | task entry, plan doc, acceptance criteria | 구현 시작, 성능 claim 작성 | queue row + plan link + validation expectations |
| Implementer | plan 범위 안에서 변경하고 evidence를 남긴다 | ready task, plan doc, repo rules | code/docs patch, tests, local validation summary | plan 없이 load-bearing 변경, scope creep, unrelated refactor | changed files + commands + residual risk |
| Reviewer | diff가 task/plan/contract를 만족하는지 확인한다 | PR/diff, plan, validation output | findings, required fixes, approve/needs-work verdict | 새 기능 구현, benchmark claim 검증 생략 | checklist 결과 + blocking/non-blocking findings |
| Deep Reviewer | architecture drift와 hidden coupling을 찾는다 | large/load-bearing diff, ADR, module map | architecture findings, required ADR/test changes | 단순 style review에 머무르기 | risk-ranked findings with file refs |
| Benchmark Auditor | benchmark/eval validity와 claim boundary를 검증한다 | eval config, dataset/provenance, reports, PR claims | allowed/disallowed claim verdict, missing evidence | synthetic-only 성공을 real claim으로 승인 | surface classification + evidence table |
| Maintainer | merge readiness와 repo coherence를 결정한다 | task, plan, reviews, CI, eval evidence | merge-ready decision, follow-up issues | 모든 구현 세부를 직접 소유하기 | final acceptance or explicit follow-up |

## Work Lifecycle

```text
idea / issue
  -> task queue entry
  -> plan doc when required
  -> ready task
  -> implementation
  -> local validation
  -> review
  -> deep review / benchmark audit when required
  -> merge-ready evidence
  -> done
```

### Granularity Guardrails

Agent에게 맡기는 work package는 충분히 커야 하지만, review surface는 작고
검증 가능해야 한다. 이 저장소에서 "scope를 키운다"는 말은 senior engineer가
며칠에서 몇 주 걸릴 목표를 task와 plan으로 self-contained하게 만든다는 뜻이지,
여러 concern을 한 PR에 섞는다는 뜻이 아니다.

- Task/plan은 큰 outcome을 잡는다: 목표, non-goals, affected interfaces,
  validation strategy, handoff를 한곳에 둔다.
- PR은 한 concern만 담는다: eval scorer 변경, retrieval algorithm 변경, ADR
  상태 변경, docs narrative rewrite를 같은 PR에 섞지 않는다.
- 긴 session은 transcript가 아니라 queue, plan, handoff로 유지한다. context
  compaction이 일어나도 새 agent가 같은 결정을 다시 추측하지 않아야 한다.
- Reviewer/Benchmark Auditor/Deep Reviewer는 Implementer가 직접 수행하지 않은
  독립 검증 역할이다. 자동화가 PR 생성, 테스트 실행, CI 확인을 대신해도
  claim boundary와 merge readiness 판단은 evidence로 남긴다.
- Detached HEAD, issue 없는 branch, plan 없는 load-bearing diff는 validation
  command가 통과해도 PR-ready가 아니다.
- `loop-state`의 `continuation` block은 detached HEAD, stale manifest, task
  linkage 누락을 감지해 다음 복구 command를 machine-readable하게 제공한다.

### Planning Required

Plan doc가 필요한 경우:

- >1 파일 또는 >50 LOC가 예상되는 non-trivial 변경.
- `rag_core.py`, `rag_retrieval.py`, `rag_verifier.py`, `rag_answer.py`,
  `rag_query.py`, `ingestion.py`, `visual_ingestion.py`, `eval/`, `api/`,
  `docs/adr/`, `scripts/build_index.py` 등 load-bearing path 변경.
- 새 eval surface, benchmark, metric, scorer, dataset, artifact를 추가하거나
  기존 claim boundary를 바꾸는 작업.
- ADR threshold에 닿을 가능성이 있는 기준선(baseline), answer schema, eval split,
  privacy boundary 변경.
- 여러 AI-agent 또는 여러 worktree가 같은 목표를 나눠 수행하는 작업.

Plan doc를 생략할 수 있는 경우:

- 오타, broken link, 단일 문서의 짧은 clarification.
- 테스트 expectation의 명백한 mechanical update.
- artifact 경로나 README 링크처럼 동작/평가 claim이 변하지 않는 1-file 문서 정리.

Plan을 생략해도 task entry에는 validation command와 evidence required를 적는다.

### Review Escalation

Benchmark Auditor가 필수인 경우:

- `eval/`, `benchmarks/`, `harness/`, `configs/eval/`, `reports/real100/`,
  `docs/evaluation/`, `docs/eval/`의 claim-bearing 변경.
- 성능 개선, regression, benchmark, accuracy, recall, nDCG, latency, cost frontier,
  hardcase 결과를 PR 본문이나 docs에 언급하는 변경.
- synthetic benchmark 또는 private real-eval aggregate를 생성/수정하는 변경.

Deep Reviewer가 필수인 경우:

- load-bearing path 변경.
- answer dict schema, pipeline preset, baseline, retrieval backend default,
  scoring semantics, privacy boundary 변경.
- 하나의 PR이 여러 ownership role을 건드리는 경우.

### Merge-Ready Evidence

Merge-ready evidence는 최소한 다음을 포함한다.

- 관련 task id와 plan link.
- 변경 파일 목록과 scope/non-goals 확인.
- 실행한 validation command와 실제 결과.
- load-bearing 변경이면 PR §5b real-data delta 또는 "검색/검증 path 동작 변화 없음"
  같은 명시적 escape.
- eval/benchmark claim이면 dataset/config/index/provenance/command/result artifact.
- reviewer checklist 결과와 남은 risk.

## Task Queue Usage

Queue는 [`tasks/queue.md`](../../tasks/queue.md)가 canonical이다. 상태(status)는
`backlog`, `ready`, `running`, `blocked`, `review`, `done`만 사용한다.

운영 규칙:

- Planner는 backlog task를 ready로 옮길 때 acceptance criteria와 validation command를
  비워두지 않는다.
- Implementer는 시작 시 status를 `running`으로 바꾸고 owner role을 명시한다.
- Review 요청 전 status는 `review`가 되고 evidence required 항목이 채워져야 한다.
- 완료 후 status는 `done`이 되며 PR/commit/evidence link가 남아야 한다.
- Queue는 GitHub issue를 대체하지 않는다. 세션 간 운영 상태와 AI-agent handoff를
  작게 저장하는 repo-local index다.

## Plan Doc Usage

Plan doc는 [`docs/plans/TEMPLATE.md`](../plans/TEMPLATE.md)를 복사해서 작성한다.
파일명은 `docs/plans/<task-id>-<slug>.md` 형식이 좋다.

Plan은 다음을 반드시 포함한다.

- 문제(problem)와 현재 동작(current behavior).
- 원하는 동작(desired behavior)과 non-goals.
- architecture impact와 affected interfaces.
- task breakdown.
- acceptance criteria.
- validation strategy.
- rollback strategy.
- failure modes.
- eval/benchmark impact.
- reviewer notes.

좋은 plan은 새 AI session이 읽고 바로 이어서 구현할 수 있어야 한다. "조사 필요",
"적절히 수정"처럼 검증 불가능한 문장은 plan의 핵심 항목으로 쓰지 않는다.

## Reviewer System

리뷰는 "테스트가 통과했는가"가 아니라 "claim이 검증 가능한가"를 확인한다.
체크리스트는 [`docs/reviews/ai-review-checklists.md`](../reviews/ai-review-checklists.md)를
사용한다.

기본 원칙:

- Normal review는 scope, tests, dead code, duplicated logic, contract drift를 본다.
- Adversarial review는 AI-agent failure mode를 일부러 찾는다.
- Benchmark audit는 dataset/config/provenance/metric semantics/claim wording을 본다.
- Regression review는 이전 failure mode가 다시 열렸는지 본다.
- Documentation/governance review는 source-of-truth drift와 stale links를 본다.

## Evaluation Governance

세 평가 표면(surface)을 섞지 않는다.

| Surface | 허용 claim | 금지 claim |
|---|---|---|
| Public fixture smoke | wiring, schema, deterministic regression, latency budget | real-world model quality, production performance |
| Synthetic benchmark | controlled failure discovery, ablation setup, reproducible comparison within synthetic data | real RFP performance, customer/procurement quality |
| Private real-eval | aggregate-only real-world evidence, hardcase stress, paired delta | raw case disclosure, unreproducible headline without provenance |

세부 정책은 [`docs/evaluation/surface-map.md`](../evaluation/surface-map.md)를 따른다.

## Long-Session Workflow

Long session은 중간 handoff를 필수 산출물로 본다. 세션 종료, context compaction,
review 요청, blocking 상태 전환 시 [`docs/operations/long-session-workflow.md`](./long-session-workflow.md)의
handoff block을 남긴다.

최소 handoff:

- branch/worktree/issue/PR/base.
- active role.
- task id와 plan link.
- touched surfaces.
- decisions made.
- commands run and results.
- next safe command.
- pending review/eval/ADR risks.

## Migration Strategy

기존 문서를 대체하지 않는다.

1. `CLAUDE.md`와 `AGENTS.md`는 짧은 pointer만 추가한다.
2. 새 작업부터 `tasks/queue.md`와 plan doc를 사용한다.
3. 기존 open PR/issue를 모두 이 시스템으로 retro-fit하지 않는다.
4. eval/benchmark claim이 있는 새 PR부터 Benchmark Auditor checklist를 적용한다.
5. 불편한 항목만 automation으로 승격한다. 처음부터 새 CI gate를 만들지 않는다.

## Incremental Rollout

| 단계 | 적용 범위 | 성공 신호 |
|---|---|---|
| 1 | 새 multi-session 작업에 queue + plan 사용 | context loss 후 재개 가능 |
| 2 | eval/benchmark PR에 benchmark audit checklist 사용 | synthetic/real claim 혼동 감소 |
| 3 | load-bearing PR에 deep review checklist 명시 | architecture drift 발견률 증가 |
| 4 | 반복 누락 항목만 hook/CI로 자동화 | 문서 규칙이 실제 gate로 승격 |

## Risks And Tradeoffs

- 문서가 늘어나는 비용이 있다. 그래서 task queue, plan, review, eval map만 최소로
  추가하고, 새 code automation은 만들지 않는다.
- Queue가 GitHub issue와 중복될 수 있다. Queue는 issue tracker가 아니라 AI-agent
  handoff index로 한정한다.
- Checklist가 형식적으로 채워질 위험이 있다. Reviewer는 checklist의 "N/A" 사유가
  검증 가능한지 확인해야 한다.
- Private real-eval은 로컬 산출물이라 외부 reviewer가 raw 재현을 할 수 없다.
  따라서 aggregate-only provenance와 claim wording을 더 엄격히 유지한다.
