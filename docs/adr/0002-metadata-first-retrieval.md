# 0002: 메타데이터 우선 검색 전략

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`rag_core.py`](../../rag_core.py), [`docs/design-background.md`](../design-background.md), [`docs/real-data/real-data-failure-taxonomy.md`](../real-data/real-data-failure-taxonomy.md)

## TL;DR

- 콘텐츠 유사도 ranking 전에 메타데이터(기관/사업/섹션) target 을 먼저 해결한다.
- 메타데이터 모호 시 silent 추측 대신 모호성 표면화.
- `agentic_full` 만 `metadata_first=true` — `no_metadata_first` 분석 변형으로 기여 측정 가능.

## 배경

RFP 쿼리는 보통 *특정 기관/사업/섹션* 에 대한 것이다(예: "기관 A의 보안 통제 요구사항"). 일반 dense 또는 BM25 검색은 lexical 유사 chunk 를 corpus 전반에서 가져와 잘못된 기관의 내용을 정답 기관 콘텐츠와 자주 섞는다. 실패가 silent — 잘못된 문서를 인용하면서 답변은 그럴듯해 보인다. 이는 reviewer 가 수용 불가한 정확히 그 양상이다.

반면 corpus 는 `agency`·`project`·`section`·문서 타입 등 신뢰 가능한 메타데이터를 보유한다. 그 facet 에 검색을 먼저 anchor 하는 것이 가장 싼 큰 승리다.

## 결정

기본 검색 전략은 콘텐츠 유사도 ranking **전** 메타데이터 target(기관/사업/섹션)을 해결한다. 메타데이터 해결 가능 시 해당 슬라이스로 검색을 필터링하고 그 안에서만 콘텐츠 점수를 사용한다. 모호 시 silent 선택 대신 모호성을 표면화한다. 메타데이터 신호가 없을 때만 콘텐츠-only ranking 으로 fallback.

knob: 파이프라인 프리셋의 `metadata_first` 플래그. `agentic_full` 은 `true`, `naive_baseline` 은 `false` — `no_metadata_first` 분석 변형으로 기여 측정 가능.

## 결과

**Wins**

- 비교/단일-doc 쿼리 타입에서 지배적이던 cross-agency 오염이 급감
- 메타데이터 무지 검색에 페널티를 주던 `citation_doc_precision` 지표가 noise floor 가 아닌 품질 신호로 활용 가능
- reviewer 산출물(`outputs/answer.json`, `reports/eval_summary.json`)에 메타데이터 해결 진단 블록 포함 — 쿼리 재실행 없이 디버그 가능

**Costs**

- 검색 품질이 메타데이터 추출 품질에 bound 됨. 메타데이터가 불완전하면 평균화 대신 피해가 집중됨
- 새 실패 카테고리 등장 — *메타데이터 모호성* (issue #72). 추측 대신 모호성 표면화가 필요해 답변 계약(ADR 0003) 복잡도 증가

## 검토한 대안

- **콘텐츠-only + reranker.** Reject default: 가장 중요한 쿼리에서 여전히 기관 혼합. 비교용 분석 변형(`naive_baseline`·`no_metadata_first`)으로 보존
- **메타데이터 보너스 항 hybrid scoring.** Reject: 추론 난도 ↑, ablation clean 분리 난도 ↑, 보너스 오튜닝 시 silent 실패 위험
