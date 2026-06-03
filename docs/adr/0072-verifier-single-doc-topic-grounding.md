# ADR 0072 — 비교 아닌 쿼리는 단일 문서(single-doc) 내 topic grounding 요구

- Status: Accepted
- Implemented: #1008 — `rag_verifier._max_single_doc_topic_matches` + `verify_evidence` 의 non-comparison 분기
- Date: 2026-05-23
- Authors: Hyunsoo Kim
- Related: ADR 0001 (naive_baseline byte-identical), ADR 0003 (answer dict 계약 / abstention 일급), ADR 0004 (partial-topic grounding strict→relaxed 정책), ADR 0005 (private/public eval 분리), ADR 0059 (failure-mode classifier)
- Issue: #1008

> **Current-policy note (2026-06-03)**: this ADR remains an accepted historical
> decision record for the single-doc topic-grounding verifier change. Its legacy
> `real-100` / 221-case motivating measurements are not current claim-bearing
> private-eval evidence. New task, PR, claim, and handoff evidence must use the
> `real100_v2` aggregate-only surface in [Surface Map](../evaluation/surface-map.md),
> unless the maintainer explicitly re-enables another private-eval surface.

## Context

Phase 5 audit finding #1 (`docs/audits/verifier-false-negative-inspection.md`, ADR 0059 / #1001·#1004 가 정량화)은 `verifier_false_negative` 를 real-100(n=221) failure 의 2위 카테고리로 측정했다 — unanswerable(`answerable=False`) 쿼리인데 verifier 가 sufficient 로 판정해 abstain 대신 답변을 emit 한 케이스 (`failure_classifier`: `not answerable and not abstained`).

inspection 의 핵심 신호: false-negative 케이스의 **81.6% 가 multi-doc evidence** 이고, 그중 다수(69.7%)는 expected doc 조차 검색되지 못한 채 **여러 무관 문서에 verification topic 이 산재**한 패턴이었다. 기존 `verify_evidence` 는 모든 evidence chunk 를 하나의 *combined pool* 로 합쳐 topic 등장 여부를 셌다. 따라서 topic A 가 doc1, topic B 가 doc2 에 있으면 "모든 topic 매칭됨"으로 통과 → 답변 emit → false negative. 즉 cross-doc topic spread 가 충분조건을 거짓으로 충족시켰다.

## Decision

1. **`_max_single_doc_topic_matches(analysis, evidence, topics)` 신규 helper** (`rag_verifier.py`).
   - evidence 를 `doc_id` 로 묶어 **단일 문서 내**에서 매칭된 topic 수의 최댓값을 반환.
   - ADR 0004 / issue #687 의 cross-entity guard 동일 계승: `analysis["matched_doc_ids"]` 가 비어있지 않으면 pool 을 target doc 으로 먼저 제한. 빈 pool → 0.

2. **`verify_evidence` 의 non-comparison 분기.** `query_type != "comparison"` 인 쿼리는 full-grounding 판정의 매칭 카운트를 combined-pool 대신 `_max_single_doc_topic_matches` 로 계산. 단일 문서가 모든 topic 을 ground 하지 못하면(cross-doc spread) `topic_not_grounded` → abstain.

3. **partial 회복도 동일 floor 적용.** non-comparison 쿼리의 last-attempt partial 회복(ADR 0004) 도 single-doc 카운트를 쓰므로, cross-doc spread 는 `partial` 로도 회복되지 않는다 — false negative 가 partial 답변으로 새는 경로 차단.

4. **comparison query_type 면제.** 비교 쿼리는 정의상 여러 문서(entity 당 1개)에 근거가 분산되므로 기존 combined-pool 카운트를 유지하고, 이미 존재하는 entity/doc coverage 체크(`missing_comparison_entity` / `missing_comparison_doc`)가 grounding 을 담당한다.

## Why these specific choices

| 결정 | 근거 |
|---|---|
| combined-pool → single-doc max (non-comparison 한정) | 단일 문서 질문의 답은 한 문서 안에 있어야 한다. cross-doc 산재를 full grounding 으로 본 것이 false-negative 81.6% multi-doc 신호의 직접 원인. |
| comparison 면제 | 비교는 entity 당 다른 문서가 정당. single-doc 강제 시 정상 비교 답변을 over-abstain → false positive. 비교는 별도 coverage 계약 보유. |
| `matched_doc_ids` target 제한 계승 | issue #687 cross-entity guard 와 정합 — relaxed 단계에서 무관 기관 문서가 끌려와도 target 밖이면 grounding 불인정. |
| partial 경로도 single-doc | false negative 가 strict 를 막아도 partial 로 통과하면 여전히 `not abstained` → count 미감소. 두 경로 모두 동일 floor 라야 실제로 abstain. |
| recall 보존 우선 (보수적) | single-doc max 는 정답 문서가 검색됐으면 그 문서가 모든 topic 을 ground → 기존과 동일 통과. cross-doc 산재(=정답 문서 부재 다수)만 떨어뜨림. abstention(ADR 0003)은 일급 상태이므로 진짜 근거 부족은 abstain 이 정답. |

## Consequences

- Historical real-100(n=221) A/B (동일 hashing 인덱스, main vs 본 변경): `verifier_false_negative` **76 → 68** (−8, −10.5%). 8건 전부 `incorrect_answer → correct_refusal` 로 전환. **accuracy 0.161 무변** (정답 손실 0), **`verifier_false_positive` 0 유지** (근거 충분한 answerable 쿼리의 잘못된 거부 0), abstention 0.262 → 0.340 (의도된 상승, 이슈 본문 `[ALLOW_REGRESSION]` 범주).
- 남은 68 의 다수는 audit 의 "expected doc 은 검색됐는데 verifier 실패"(28.9%) — *문서는 맞지만 그 안에 답이 없는* chunk-level 의미 불일치로, single-doc grounding 으로는 못 잡는다. chunk-level claim alignment(audit 가설 #4) 는 별 issue/ADR 범위.
- production 답변 계약(ADR 0003) 무변 — verified 판정만 강화, answer dict shape/`schema_version` 불변.

## Invariance check

- **ADR 0001** (`naive_baseline` byte-identical) — naive_baseline 은 `verify_evidence` 미호출(`verified = bool(evidence)`, `rag_core.py`). 본 변경은 `verifier_retry` arm(agentic_full/metadata_first) 한정. `tests/test_naive_baseline_ranking_invariance.py` 통과.
- **ADR 0003** (answer dict 계약, abstention 일급) — 진짜 근거 부족은 그대로 `status: insufficient`. 본 변경은 cross-doc spread 라는 *거짓 충분* 만 제거하므로 abstention semantic 강화이지 위반 아님.
- **ADR 0004** (partial-topic grounding) — partial 회복의 fraction/matched floor 와 #687 cross-entity guard 를 그대로 계승, single-doc 차원만 추가. `tests/test_partial_topic_grounding.py` 전 케이스 통과.
- **ADR 0005** (private/public 분리) — 당시 측정은 gitignored local config(real-100) 기반, 신규 커밋 데이터 0. aggregate 수치만 본 ADR 에 인용(per-case 텍스트 미노출). 현재 신규 claim-bearing evidence 는 위 current-policy note 의 `real100_v2` aggregate-only 경계를 따른다.

## Verification

<!-- verifies-key: rag_verifier.py:def _max_single_doc_topic_matches -->
<!-- verifies-key: rag_verifier.py:def verify_evidence -->
<!-- verifies-key: tests/test_verifier_singledoc_grounding_regression.py:class CrossDocSpreadRejectedTest -->
<!-- verifies-key: tests/test_verifier_singledoc_grounding_regression.py:class ComparisonExemptionTest -->

## Out-of-scope

- **chunk-level claim alignment** (audit 가설 #4) — 정답 문서는 검색됐으나 그 안에 답이 없는 28.9% 케이스. 큰 surface, 별 ADR.
- **query specificity numeric-presence rule** (audit 가설 #1 / Issue F) — RFP evidence 의 숫자 편재로 효과가 약해 본 PR 에서 채택하지 않음. 필요 시 topic-숫자 근접(chunk-level)과 결합한 별 검토.
- **run-to-run variance source 진단** (audit 가설 #6) — 49↔65↔76 변동의 원인(검색 tie-break / embedding state). 별 issue.
