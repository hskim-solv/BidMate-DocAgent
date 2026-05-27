# Agent-Gated RFP Evaluation Loop

이 문서는 폐쇄망(offline)과 비폐쇄망(online) 환경에서 RFP QA 평가(evaluation)를
계속 반복하기 위한 보수적 agent gate 정책이다. 목표는 사람이 매번 승인하지
않아도, 사전 합의된 정책을 Codex가 보수적으로 집행해 최적의 RFP 도메인
평가지표(metric)를 versioned suite로 수렴시키는 것이다.

## Environment Axis

| Environment | Allowed | Required safeguards |
|---|---|---|
| Offline / closed network | 외부 API 불가, 외부 모델 다운로드 가능, GPU 가능, local LLM judge 가능 | 다운로드 모델 id/version, hardware, local judge backend, no external egress 기록 |
| Online / non-closed network | 외부 judge/model/API 가능, private RFP 원문 외부 전송 가능 | provider/model/date, payload class, private-data egress mode, cost/latency, provenance 기록 |

환경 축은 smoke / synthetic / private real-eval 표면(surface)과 독립이다. 모든
claim-bearing 루프는 private real-eval을 포함해야 하며, online-only judge 결과는
offline proxy 또는 rule-based metric과의 관계를 설명해야 한다.

## RFP Success Definition

RFP QA 성공은 단일 accuracy가 아니라 다음 failure를 줄이는 것이다.

1. 필요한 조항, 금액, 날짜, 자격, 제출 조건을 top-k 안에 회수한다.
2. 답변의 각 claim이 실제 근거(evidence)에 연결된다.
3. citation이 관련 문서, chunk, page, region을 가리킨다.
4. 비교 질문에서 모든 대상과 항목을 빠뜨리지 않는다.
5. 근거가 부족하면 보류(abstention)하고 그럴듯한 답을 만들지 않는다.
6. 숫자, 날짜, 조건 slot은 별도 high-risk field로 정확히 검증한다.
7. 답변은 RFP 검토자가 바로 확인할 수 있는 구조를 유지한다.

## Metric Suite

단일 headline score는 triage aid일 뿐 merge/block 기준이 아니다. 채택 단위는
metric suite다.

| Metric family | Purpose |
|---|---|
| Retrieval recall | `chunk_recall@k`, MRR, nDCG로 gold evidence 회수력을 본다. |
| Grounding | answer claim이 retrieved evidence에 의해 지지되는지 본다. |
| Citation precision | citation이 실제 support source를 가리키는지 본다. |
| Claim-citation alignment | claim text와 cited evidence text의 정렬을 본다. |
| Comparison coverage | 비교 대상별 evidence/claim coverage 누락을 본다. |
| Abstention calibration | answerable/unanswerable에서 insufficient 사용이 맞는지 본다. |
| Numeric/date/condition accuracy | 금액, 날짜, 자격, 제출 조건 slot 오류를 별도로 본다. |
| Human/judge agreement | human reviewer 또는 approved judge와의 일치도를 본다. |

## Adoption Criteria

새 metric 또는 metric suite version은 아래 조건을 모두 만족해야 채택한다.

- Private real-eval aggregate에서 반드시 계산된다.
- Offline과 online 양쪽에서 계산 가능하거나, online-only metric은 offline proxy와
  관계가 문서화된다.
- Human review 또는 approved judge signal과 양의 관계가 있다.
- Regression sensitivity가 있다. 실제 failure fixture 또는 historical failure에서
  metric이 움직인다.
- Privacy/provenance가 명확하다. raw private content를 커밋하지 않고, provider,
  model, dataset, config, index provenance를 남긴다.
- 하나의 metric 개선이 grounding, citation, abstention 중 하나의 악화를 가리지
  않는다.
- Claim wording이 표면을 넘지 않는다. synthetic-only 결과로 real RFP quality를
  주장하지 않는다.

## Loop Termination

이 루프는 영구 종료가 아니라 versioned adoption으로 닫는다.

| Version | Exit condition |
|---|---|
| v0 | Offline/online 양쪽에서 같은 private real-eval case family에 대해 metric suite aggregate가 생성된다. |
| v1 | 세 개 이상의 주요 RFP failure mode를 분리 설명하고, suite가 그 failure를 감지한다. |
| v2 | human/judge agreement가 기준선보다 높고, regression fixture에서 민감하게 반응한다. |
| operating | 최근 변경 N회에서 false pass가 없고, 새 failure는 follow-up metric 또는 ratchet으로 흡수된다. |

## Next Milestones

| Milestone | Smallest next PR | Evidence required |
|---|---|---|
| v0-a metric inventory | 현재 private real-eval aggregate에 이미 있는 metric과 없는 metric을 [표로 분류한다](./v0-metric-suite-inventory.md). | aggregate-only inventory, no performance claim |
| v0-b offline/online run manifest | offline/online 실행 환경, provider/model, payload class, egress mode를 같은 schema로 기록한다. | manifest schema + privacy test |
| v0-c metric suite report | `scripts/render_v0_metric_suite_report.py`로 retrieval, grounding, citation, comparison, abstention, numeric/date/condition, judge agreement를 한 report shell에 모은다. | private real-eval aggregate + provenance |
| v1 failure sensitivity | 세 개 이상의 RFP failure mode에 대해 metric이 실제로 움직이는지 확인한다. | before/after or historical failure replay |
| v2 agreement calibration | human 또는 approved judge signal과 suite metric의 agreement를 측정한다. | agreement aggregate, no raw private text |

## Agent Gate

기존 human gate 자리에 Codex는 보수적 agent gate를 집행한다.

- 애매하면 `draft`, `no performance claim`, `follow-up issue`, `fail closed`를 고른다.
- Private real-eval은 claim-bearing loop의 필수 표면으로 둔다.
- Online private-data egress는 허용되지만 provenance와 payload class를 남긴다.
- 성능 주장(performance claim)은 private real-eval aggregate와 provenance가 있을 때
  좁은 범위로만 자동 작성한다.
- Architecture / ADR / issue close / branch delete / force-with-lease는 실행 가능하지만
  audit trail, dependent check, rollback note를 남긴다.
- CLI에 남아 있는 `human-gated-*` 이름은 legacy compatibility 이름이다. 의미는
  "explicit conservative gate acknowledgment"로 해석한다.

## Role Dispatch Policy

역할(role) 분리는 `role-dispatch` report로 먼저 산출한다. 이 report는 Codex
서브에이전트(subagent)를 실제 실행하지 않고, root session이 어떤 역할을 병렬
또는 직렬로 보낼지 정하는 prompt source다.

- 기본 체인: `Planner -> Implementer -> Reviewer`.
- Eval/benchmark 표면: `Benchmark Auditor`를 자동 추가한다.
- Private-data / real-eval 표면: `Privacy Auditor`와 `Benchmark Auditor`를 자동
  추가한다.
- Product runtime / ADR 표면: `Deep Reviewer`를 자동 추가한다.
- 병렬 실행은 read-only 역할 또는 disjoint write scope일 때만 허용한다.
- 같은 파일을 쓰는 역할은 직렬화한다.
- 최대 12개 role subagent, depth 2(`root session -> role subagents`)를 넘기지
  않는다.
- Private real-eval 해석, benchmark/performance claim, remote mutation 실행은
  서브에이전트에 위임하지 않는다. 서브에이전트는 evidence와 recommendation만
  남기고, root session이 최종 agent gate를 집행한다.

## Related

- [ADR 0079](../adr/0079-agent-gated-offline-online-rfp-eval-loop.md)
- [Evaluation Surface Map](./surface-map.md)
- [Private Real-Eval Workflow](./private_real_eval_workflow.md)
- [AI Codex Workflow](../operations/ai-codex-workflow.md)
