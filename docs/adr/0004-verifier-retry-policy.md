# 0004: 검증기 주도 retry — strict → relaxed 단계화

- **Status**: accepted
- **Date**: 2026-05-11
- **Related**: [`rag_verifier.py`](../../rag_verifier.py) (`verify_evidence` + partial-topic grounding policy, PR-J1 / issue #465 에서 `rag_core.py:L1843/L2053` 추출), [`docs/agentic/verifier-rules.md`](../agentic/verifier-rules.md) (strict → relaxed staging 을 pseudo-prompt 로 표현; LLM-migration counter-checks), [`docs/real-data/real-data-failure-taxonomy.md`](../real-data/real-data-failure-taxonomy.md), [`docs/eval/grounding-eval-hardening.md`](../eval/grounding-eval-hardening.md)

## TL;DR

- 답변 생성은 `verify_evidence` 가 게이트 — strict → relaxed → abstain 2단계 retry.
- retry 1회 상한 → latency·비용 bound.
- strict/relaxed threshold 는 policy choice (issue #829 sweep 대기).

## 배경

메타데이터 우선 검색(ADR 0002)이 있어도 top-k chunk 가 일부만 on-topic 인 경우가 있다. 첫 검색 결과를 항상 신뢰하면 자신감 있게 들리지만 근거 약한 답이 생긴다 — 이 프로젝트가 가장 피하고 싶은 실패다. 반대 극단(근거 불완전 시 무조건 보류)은 false abstention 폭증을 낳고, `docs/real-data/real-data-failure-taxonomy.md` C6 가 이를 실제 corpus 의 잔여 지배 실패로 식별했다.

*"이 근거 충분한가?"* 를 구조적으로 묻고 아닐 때 한 번 더 시도하되 unbounded loop 나 검증 불가 답변은 피하는 메커니즘이 필요하다.

## 결정

답변 생성은 `verify_evidence` 가 게이트. 검색 루프는 **단계**로 실행:

1. **Strict 단계.** 전체 topic/entity/comparison coverage 검사. 근거가 필요한 모든 신호를 충족하거나 명시 `verification_reasons`(예: `topic_not_grounded`, `missing_comparison_entity:*`)와 함께 실패
2. **Relaxed 단계** (retry 1회). 확장된 파라미터로 검색 재실행; 검증기는 문서화된 약한 기준 충족 시 근거 수용. 완화는 `diagnostics.filter_stage_attempts` 에 기록 — 모든 답변이 자체 근거-품질 trail 을 보유
3. **Abstain.** relaxed 도 실패 시 답변은 `insufficient` (또는 일부 target 만 있는 비교 쿼리는 `partial` — ADR 0003 참조). 3차 retry 없음

knob:

- 파이프라인 프리셋별 `verifier_retry: bool`. `agentic_full` on, `naive_baseline` off, `no_verifier_retry` 는 일급 분석 변형
- strict/relaxed threshold 는 `verify_evidence` + 관련 helper(`rag_core.py`) 에 위치. threshold 이동 변경은 eval delta 업데이트 + PR 에 trade-off 명시 필요

## 결과

**Wins**

- 보류가 audit 가능 — 모든 보류 답변이 `verification_reasons` 보유, 이게 taxonomy 기반 backlog(#69·#70·#72)를 actionable 하게 만듦
- retry 비용 bound (최대 1 검색 추가) — latency/비용 story 단순 유지
- 각 컴포넌트 독립 ablation 가능(`metadata_first`·`rerank`·`verifier_retry`), eval config 가 각각을 named run 으로 노출

**Costs**

- strict vs relaxed threshold 는 policy 결정이지 first principle 도출 아님. issue #69 가 정확히 default policy 가 strict 쪽으로 기울어 실제 데이터에서 false abstention 을 내는 문제 때문에 존재
- 새 실패 모드마다 자체 verification reason 문자열을 원하는 경향. `eval/run_eval.py` 의 `retry_reason_counts` 가 추적 대상 단일 출처

## 측정 갭

`verify_evidence` 의 strict/relaxed threshold 는 policy 선택(위 **Costs** 에 이미 기술), issue #828 까지 ADR 은 변경 정당화 근거를 노출 안 했다. 코드에 묻히는 대신 결정 레이어에 갭이 보이도록 여기 문서화:

- **audit 대상 magic constant**: `PARTIAL_TOPIC_GROUNDING_MIN_FRACTION = 0.5`, `PARTIAL_TOPIC_GROUNDING_MIN_MATCHED = 2` ([`rag_verifier.py:73-75`](../../rag_verifier.py))
- **실행할 sweep** (tracking [#829](https://github.com/hskim-solv/BidMate-DocAgent/issues/829)): grid `MIN_FRACTION ∈ {0.3, 0.4, 0.5, 0.6, 0.7}` × `MIN_MATCHED ∈ {1, 2, 3}` = 15 cell, ADR 0005 의 private-100 + public-synthetic split 에서 채점
- **값 변경 결정 규칙**: real-100 에서 ≥3pp accuracy 개선 + abstention 회귀 ≤2pp. (sweep 랜딩 시 숫자 정제; 그 전까지 현재 값은 `tests/test_partial_topic_grounding.py` 회귀로 방어되는 spike-grade default 로 취급, optimum 도출 아님)
- **sweep 미진행 이유**: real-eval 예산이 eval-set 확장 작업(ADR 0044 / issue #732) 에 게이트. 닫히면 #829 가 다음 게이트

## 검토한 대안

- **검증기 없이 top-k 로 항상 답.** Reject: `naive_baseline` 동작이며 분석 변형용으로만 보존. reviewer-facing 주장에 unsafe
- **score-based stopping 의 unbounded retry.** Reject: latency unbounded, retry 동기인 실패 케이스는 정확히 higher score 가 better grounding 을 의미 안 하는 케이스
- **LLM-as-judge 검증기.** public 경로엔 reject: 외부 의존성 추가, 쿼리당 토큰 비용, 재현 가능 eval 난도 ↑. deterministic 검증기가 천장에 닿으면 재고
