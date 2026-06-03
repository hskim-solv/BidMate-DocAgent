# ADR 0093 — Comparison groundedness 를 per-target 측정 표면으로

- Status: Accepted
- Date: 2026-05-23
- Authors: Hyunsoo Kim
- Related: ADR 0001 (naive_baseline byte-identical), ADR 0003 (answer dict 계약), ADR 0005 (public/private eval 분리), ADR 0054 (conditional-on-substantive scorer semantics), ADR 0059 (failure-mode classifier 측정 표면), ADR 0070 (content-grounded gold), ADR 0072 (verifier single-doc topic grounding — comparison 을 명시적으로 면제)
- Issue: #1399

## Context

핵심 포트폴리오 주장 = "agentic_full 이 비교(comparison) 질의 품질에서 naive_baseline 을 이긴다". 그러나 이 주장을 **측정할 표면 자체가 없다.**

현재 `groundedness` ([eval/scorers/case.py](../../eval/scorers/case.py)) 는 답변 + **전체** evidence 텍스트를 한 덩어리(`combined_text`)로 합친 뒤 `contains_all_terms(combined_text, expected_terms)` 로 전역 substring 검사를 한다. 2-target 비교 질의 (예: "기관 A와 기관 B의 AI 요구사항 차이") 에서 이 지표는 다음 둘을 **구분하지 못한다**:

- 양쪽 대상이 *각자의* evidence 로 독립 근거됨 (의도된 상태)
- 한쪽만 근거되고, 다른 쪽의 expected_term 은 공유 풀(pool)에 그냥 **누출(leak)** 됨

즉 진짜 per-target 근거를 보상하지도, 한쪽짜리 답변을 벌하지도 못한다 — 프로젝트가 개선했다고 주장하는 바로 그 품질을 측정 불가.

전체 비교 경로를 추적한 결과 **검색(retrieval)은 병목이 아니다**: 실측 `comparison_target_recall` 은 이미 1.0 (양쪽 대상 문서 다 검색됨). target 정체성은 답변 구성까지 보존된다 (`build_comparison_claims` 가 대상별 1 claim 생성). 병목은 **측정 표면의 부재** — per-target 근거를 볼 수 없으니 하류 시스템 수정(answer-builder claim 선택)의 효과도 보이지 않는다.

ADR 0072 는 non-comparison 질의에 single-doc topic grounding floor 를 도입하면서 comparison 을 정의상 면제했고, "남은 chunk-level alignment (가설 #4) 는 별 ADR" 로 미뤘다. 본 ADR 은 그 comparison 측정 공백의 **계측(measurement) 절반** 을 채운다 (시스템 수정은 loop #2).

마침 **per-target gold 는 이미 존재**한다: `expected_claim_citations` (target + expected_doc_ids + expected_terms) 는 비교 케이스에 이미 있고, alignment scorer ([eval/scorers/alignment.py](../../eval/scorers/alignment.py)) 가 이미 대상별로 소비 중이다. 신규 gold 필드 0.

ADR 0059 의 read-only consumer boundary 가 본 지표에도 그대로 — production code path 0 변경, eval-time scorer 출력만 확장.

## Decision

1. **신규 per-case 지표 `comparison_groundedness`** ([eval/scorers/case.py](../../eval/scorers/case.py) `score_comparison_groundedness`) 를 기존 pooled `groundedness` 와 **나란히** 추가. 기존 `groundedness` 무수정 (ADR 0001 연속성 + 회귀 baseline 보존).

2. **정의 (결정론적, 오프라인):** 비교 케이스의 각 `expected_claim_citations` spec 에 대해, 대상은 *grounded* 이다 ⟺ `doc_id ∈ spec.expected_doc_ids` 인 evidence chunk 중 그 spec 의 `expected_terms` 를 모두 담은 것이 존재. per-case 점수 = (grounded target 수) / (target spec 수). 기존 `contains_all_terms` ([eval/scorers/_shared.py](../../eval/scorers/_shared.py)) 재사용.

3. **제외(None) 규칙** — ADR 0054 의 conditional-on-substantive semantic 을 그대로 미러:
   - `query_type != comparison` → `None` (denominator 제외)
   - `expected_claim_citations` 의 target spec 이 2개 미만 (단일 대상 "비교" 케이스 포함) → `None`
   - `answerable=False` → `None`
   - `answerable=True AND abstained` → `0.0` (답변 가능한 비교를 거부한 것은 벌점, None 아님 — pooled groundedness 의 answerable-but-refused 경로와 일관)

4. **Aggregation wiring** ([eval/run_eval.py](../../eval/run_eval.py) `metric_block`) — non-None 점수를 모아 `comparison_target_recall` 의 조건부 패턴 그대로 `block` + `ci_block` (bootstrap CI 95%) 에 추가. 공유 `metric_block` 경유로 `by_query_type.comparison` 슬라이스에 자동 전파.

5. **Additive schema (`schema_version` bump 없음)** — per-case `comparison_groundedness: float | None` + aggregate `comparison_groundedness: float` (비교 케이스 존재 시만, 조건부). downstream consumer (compare_eval / check_baseline_provenance) 는 신규 키 무시.

## Why these specific choices

| 결정 | 근거 |
|---|---|
| 기존 pooled `groundedness` 와 병행 (교체 아님) | ADR 0001 byte-identity + 기존 leaderboard/baseline 연속성. 교체는 모든 committed aggregate 재생성 강제 + 회귀 비교 단절. |
| per-target = doc_id 필터 + term 매칭 | gold 가 이미 그 구조 (`expected_claim_citations`). alignment scorer 와 동일 gold 소비 → 일관성. 신규 gold 0. |
| target spec < 2 → None | 본 지표의 구조적 목표 = *multi-target* 비교 근거. 단일 대상 "비교" 케이스는 일반 groundedness 로 충분 — 희석 방지. |
| abstained(answerable) → 0.0, not None | pooled groundedness 와 동일 처리 (answerable 질의를 거부하면 품질 0.0). over-abstention 이 per-target 지표를 부풀리지 않도록. |
| LLM 미사용 (결정론) | 모든 입력이 `case`/`evidence` dict 의 기존 필드. 기본 eval 경로의 결정론·오프라인 불변 (ADR 0005/0012 데이터 경계 무관). |
| `metric_block` 조건부 emit (target_recall 패턴 재사용) | 신규 집계 코드 0 — 검증된 None-filter + conditional-key 패턴 그대로. |

## Consequences

- 비교 그라운드니스의 진짜 agentic_full−naive_baseline 델타가 드러난다 — pooled 지표가 가렸던 신호. 결과가 유리하면 핵심 주장 방어, 불리하면 그것이 곧 loop #2 (answer-builder per-target claim 선택 수정) 를 정당화하는 데이터.
- 신규 measurement surface 1차원 추가 — `comparison_groundedness` per-case + aggregate 키.
- production code path 0 변경 — `rag_*.py`, `api/`, `eval/config.yaml` 무수정. naive_baseline 합성 산출물 byte-identical.
- **실측(real-100) 한계**: ADR 0070 이 정량화한 catalog-gold construct-validity 결함 (committed `expected_terms` 가 본문 부재) 이 본 지표에도 그대로 상속됨 — `contains_all_terms` 기반이므로. 따라서 본 loop 의 load-bearing 신호는 공개 합성 (expected_terms 가 합성 본문에 존재) 비교 슬라이스이며, 실측 비교 슬라이스는 ADR 0070 content-grounded gold 의 comparison 확장 (follow-up) 이후에 의미를 갖는다.
- **Current private-eval boundary**: 이 ADR 의 `real-100` / 실측 비교 슬라이스 언급은 당시 historical measurement context 이다. 현재 claim-bearing private-eval 근거는 `real100_v2` aggregate-only 표면으로 한정하며, legacy real-100/n=221/kordoc aggregate wording 은 archive-only 로 취급한다.

## Invariance check

- **ADR 0001** (naive_baseline byte-identical) — read-only scorer 확장, production 코드 0 변경 → 합성 baseline 영향 없음. 신규 키만 추가.
- **ADR 0003** (answer dict `schema_version=2`) — 변경 없음. 본 확장은 `case_results` (eval scorer 출력) 이지 answer 계약과 무관.
- **ADR 0005** (private/public 분리) — aggregate-only commit 패턴 그대로. 실측 비교 슬라이스는 n=1 (issue #1399 의 후속 데이터 확장 범위 밖) — 본 loop 의 load-bearing 신호는 공개 합성. 현재 private-eval claim 은 `real100_v2` aggregate-only 근거가 필요하다.
- **ADR 0054** (substantive-only semantics) — None/0.0 규칙이 ADR 0054 의 conditional-on-answer semantic 을 그대로 계승.
- **ADR 0070** (content-grounded gold) — 본 지표는 채점기(scorer) 측 확장, ADR 0070 은 gold 구성 측 — 직교. 단 real-100 상속 한계는 위 Consequences 에 명시.
- **ADR 0072** (verifier single-doc grounding) — comparison 면제로 남긴 측정 공백을 본 지표가 계측 측면에서 보완. verifier 동작 무변경.

## Verification

<!-- verifies-key: eval/scorers/case.py:def score_comparison_groundedness -->
<!-- verifies-key: tests/test_scorers_comparison_groundedness.py:class TestOneSidedLeakage -->
<!-- verifies-key: tests/test_scorers_comparison_groundedness.py:class TestMetricBlockAggregation -->

## Out-of-scope

- **Answer-builder per-target claim 선택 수정** — `build_comparison_claims` 의 first-match-only (`entity_evidence[0]`) + target-blind `best_sentence` ([rag_answer.py](../../rag_answer.py)). 본 지표가 드러내는 신호로 정당화되는 loop #2 별 PR (ADR 0072 의 "가설 #4" 계열).
- **실측 비교 케이스 n=1 → ≥10 확장 + content-grounded comparison gold** — ADR 0070 의 comparison 확장 (follow-up). 현재 정책에서는 `real100_v2` aggregate-only private-eval 경계(ADR 0005/0052 및 current project policy) 안에서만 claim 근거로 사용할 수 있다.
- **Verifier graded scoring** — 현재 binary pass/fail. 별 ADR.
- **Citation↔target alignment assertion** — `make_citation` 의 대상-인용 정합성 검사. 별 follow-up.
