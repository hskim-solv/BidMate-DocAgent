# RAG 실패 모드 케이스 스터디 (리뷰어용)

이 문서는 RFP 문서 RAG 에서 실제로 발생하는 **대표 실패 모드 5가지**를, 증상 → 근본 원인 → 설계 대응 → 회귀 가드 → 리뷰어 시사점 순으로 정리한 리뷰어 진입점이다. RAG 데모를 "구현"한 것이 아니라, 실패 모드를 **정의하고 측정 가능하게 막은** 시스템 소유(system ownership) 증거를 보이는 것이 목적이다.

본 문서는 요약이며, 정본(canonical) 데이터는 다음을 참조한다 (중복 서술하지 않음):

- [`docs/real-data/real-data-failure-taxonomy.md`](../real-data/real-data-failure-taxonomy.md) — real100 기반 6-카테고리(C1–C6) 정본 분류
- [`docs/agentic/agent-failure-modes-analysis.md`](../agentic/agent-failure-modes-analysis.md) — LangGraph 오케스트레이션 실패 패턴
- [`docs/operations/failure-mode-harden-process.md`](../operations/failure-mode-harden-process.md) — monotone-ratchet 하드닝 프로세스
- [ADR 0059](../adr/0059-failure-mode-classifier-as-measurement-surface.md) (failure classifier) · [ADR 0062](../adr/0062-failure-rate-regression-contract.md) (회귀 ceiling 계약)

아래 5개 모드는 정본 taxonomy 의 C1–C6 에 대응한다 (A=C2, B=C1/C2, C=C6, D=C4, E=C5).

---

## A. Comparison query starvation (비교 질의 한쪽 문서 기아)

- **Symptom**: 비교 질의(`query_type == "comparison"`)에서 글로벌 top-k 가 score 높은 한 기관/문서로 슬롯을 과점 → 다른 비교 대상 문서의 evidence 가 누락된다.
- **Root cause**: 단순 global top-k cut 은 비교 대상이 둘 이상이라는 질의 의도를 무시한다. 한쪽 문서가 검색 점수를 독식하면 반대쪽 근거가 잘려 나간다.
- **Design response**: comparison-aware **balanced top-k** — Query Analyzer 가 추출한 비교 target 별로 `min_per_target ≥ 1` evidence 를 보장하고, 남은 슬롯만 글로벌 score 순으로 채운다. 단일 문서 질의에서는 no-op(추가 비용 0). 설계: [`docs/retrieval/comparison-ranking.md`](../retrieval/comparison-ranking.md).
- **Regression guard**: [`tests/test_fuzzy_retrieval.py`](../../tests/test_fuzzy_retrieval.py) — asymmetric corpus 에서 균등 보장, disabled 시 global ordering 보존, single-doc no-op 을 회귀로 고정.
- **Reviewer takeaway**: 일반 RAG 튜토리얼에 없는 **RFP 도메인 특화 검색 결정**. 실패 패턴을 먼저 발견하고 ranking 전략으로 구조적으로 막은 뒤 테스트로 잠갔다.

## B. Metadata ambiguity (기관·사업명 모호성)

- **Symptom**: 발주기관/사업명이 유사한 substring 을 공유해 여러 문서가 동시에 매칭 → 시스템이 잘못된 문서로 답할 위험 (정본 taxonomy C2; C1 엔터티 정규화와 인접).
- **Root cause**: 한국 공공/B2B RFP 는 기관·사업명이 길고 부분 중복이 많아, 단순 substring/유사도 매칭만으로는 정답 문서를 단일 확정할 수 없다.
- **Design response**: 메타데이터 우선 검색([ADR 0002](../adr/0002-metadata-first-retrieval.md))으로 후보를 좁히고, 모호도가 임계 이내로 근접하면 답을 강행하지 않고 **clarification** 으로 분기한다 — [`rag_clarification.py`](../../rag_clarification.py) 의 `metadata_clarification_answer` / `make_metadata_clarification_result`.
- **Regression guard**: [`tests/test_single_turn_ambiguity.py`](../../tests/test_single_turn_ambiguity.py) — 모호 질의가 잘못된 후보로 fallback 하지 않고 clarification 경로를 타는지 고정.
- **Reviewer takeaway**: "근접 후보가 둘이면 추측보다 되묻는다" 는 정책을 코드 경로로 명시. 잘못된 문서 기반 자신만만한 오답을 구조적으로 차단.

## C. Unsupported / out-of-scope question (근거 없는 질의)

- **Symptom**: 사용자가 evidence 에 존재하지 않는 정보를 요구 → 생성형이라면 hallucination, 추출형이라도 약한 근거로 답할 위험 (정본 taxonomy C6).
- **Root cause**: 검색이 관련 evidence 를 못 찾았는데도 파이프라인이 "무언가" 답하려 하면 근거 없는 응답이 나온다.
- **Design response**: verifier/retry + **abstention(보류)** — 근거가 불충분하면 bounded 재시도 후, 일급 응답 상태 `status: insufficient` 로 보류한다([ADR 0003](../adr/0003-structured-answer-citation-contract.md) · [ADR 0004](../adr/0004-verifier-retry-policy.md)). 보류는 fallback/error 가 아니라 **의도된 답변 상태**다.
- **Regression guard**: [`tests/test_scorers_case_abstention.py`](../../tests/test_scorers_case_abstention.py) — abstention 케이스의 quality metric 처리(보류 시 accuracy=none) 를 고정.
- **Reviewer takeaway**: README 메트릭에서 `agentic_full` 의 **abstention accuracy +57.1pp** 가 이 설계의 정량 증거. raw answer rate 를 일부 내주고 "모르면 모른다" 의 신뢰성을 산다.

## D. Follow-up query resolution (후속 질문 문맥 소실)

- **Symptom**: "그 사업", "거기 일정은?" 같은 암시적 지시어가 직전 문맥(active document)을 필요로 하는데, 이를 해소하지 못해 엉뚱한 문서로 검색된다 (정본 taxonomy C4).
- **Root cause**: 멀티턴에서 직전 턴의 entity 가 현재 질의에 명시되지 않으면, 검색기는 지시어만으로 정답 문서를 찾지 못한다.
- **Design response**: [`rag_conversation_state.py`](../../rag_conversation_state.py) 가 대화 상태를 유지하고, 해소된 entity 를 질의에 주입(`resolve_conversation_context` → `inject_entities_into_query`)해 검색 anchor 를 보강한다.
- **Regression guard**: [`tests/test_followup_entity_injection.py`](../../tests/test_followup_entity_injection.py) — `test_resolved_query_contains_entity_anchor` 등으로 해소된 질의가 entity anchor 를 포함하는지 고정.
- **Reviewer takeaway**: 단일 질의 정확도만 본 RAG 와 달리, **세션 상태를 일급으로 다뤄** 실무 대화형 사용에서의 문맥 소실을 막는다.

## E. Citation drift / unsupported claims (인용 표류)

- **Symptom**: 답변이 citation 을 달고 있지만 그 claim 이 실제 evidence chunk 와 정합하지 않는다 — 인용처럼 보이는 비근거 답변 (정본 taxonomy C5).
- **Root cause**: claim 과 citation 의 정렬을 강제하지 않으면, 출처를 붙였더라도 본문이 출처를 실제로 지지하지 않을 수 있다.
- **Design response**: 구조화 답변 스키마([`rag_answer_schema.py`](../../rag_answer_schema.py), [ADR 0003](../adr/0003-structured-answer-citation-contract.md))로 `claims` ↔ `citations` 정렬을 계약화하고, claim-citation alignment 를 평가 지표로 측정한다.
- **Regression guard**: [`tests/test_citation_coverage_regression.py`](../../tests/test_citation_coverage_regression.py) — claim·page·region coverage 정합을 회귀로 고정.
- **Reviewer takeaway**: README 메트릭의 **citation precision +18.0pp** + claim-citation alignment 가 이 계약의 정량 증거. "출처 있어 보임" 이 아니라 "출처가 실제로 지지함" 을 측정한다.

---

## 실패 → 하드닝 → 회귀 차단의 폐루프

위 대응들은 일회성 fix 가 아니라 **monotone-ratchet 프로세스**로 운영된다: 감사로 실패 표면 식별 → 카테고리 lock → hardcase 예제 추가 → ceiling 회귀 게이트 → fix → ceiling tighten. 프로세스: [`docs/operations/failure-mode-harden-process.md`](../operations/failure-mode-harden-process.md). 측정 표면·회귀 계약: [ADR 0059](../adr/0059-failure-mode-classifier-as-measurement-surface.md) · [ADR 0062](../adr/0062-failure-rate-regression-contract.md). PR 마다 [pr-eval.yml](../../.github/workflows/pr-eval.yml) 이 회귀를 게이트한다.
