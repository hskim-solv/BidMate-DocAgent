# ADR 0059 — Failure-mode classifier as a new measurement surface

- Status: Proposed
- Date: 2026-05-19
- Authors: Hyunsoo Kim
- Related: ADR 0006 (real-data LLM-judge), ADR 0054 (conditional-on-substantive-answer scorer semantics), ADR 0055 (claim_validator PR gate), ADR 0056 (rationality_judge measurement surface)
- Augments: Phase 5 audit (`docs/audits/eval-framework-phase5-audit.md`, PR #992) item 1 supply ("Failure taxonomy 정의 ◐ partial — 3-bin abstention_outcomes 만 존재, 7-category taxonomy 부재")
- Issue: #996

## Context

Phase 5 audit (PR #992 `7e28880`) 의 3-item 표 중 **item 1 진단 = ◐ partial** — `abstention_outcomes` 3-bin (PR #464, `correct_refusal` / `incorrect_answer` / `boundary_partial`) 만 존재하고 7-category failure taxonomy (`retrieval_miss` / `planner_under_decomposition` / `verifier_false_negative` / `verifier_false_positive` / `generator_hallucination` / `context_dilution` / `unknown`) 부재. 3-bin 은 *refusal-axis* 만 분류 — answerable case 의 실패 root-cause stage (retrieval / verifier / generator / context) 추적 0차원.

같은 audit 의 **finding #1** — `verifier_false_negative_on_unanswerable` ≈ 84% (`abstention_outcomes.incorrect_answer == 87` / `(correct_refusal == 16) + 87 = 103`). raw 측정에서 발견됐지만 *어느 stage 가 root cause* 인지 추적할 분류 표면이 없어 supply 2 (dashboard) + supply 3 (regression test) 의 prerequisite 부재 상태.

ADR 0006 의 read-only consumer boundary 가 본 분류기에도 그대로 — production code path 0 변경, eval-time `score_case` 출력의 후처리만.

## Decision

1. **신규 모듈 `eval/scorers/failure_classifier.py`** 도입.
   - 시그니처 `classify_failure(case_result: dict) -> FailureCategory | None`.
   - **7 categories** (`Literal`):
     - `retrieval_miss` — answerable AND expected doc 가 evidence 에 부재.
     - `planner_under_decomposition` — `query_type ∈ {comparison, multi_hop}` AND `len(attempt_latency) ≤ 1`.
     - `verifier_false_negative` — `answerable=False AND not abstained` (Phase 5 finding #1 의 87/103 패턴).
     - `verifier_false_positive` — `answerable=True AND abstained AND term_match=True`.
     - `generator_hallucination` — `claim_citation_alignment < 0.5`.
     - `context_dilution` — **v1 비활성화** (chunk_id → doc_id 매핑 부재; supply 2 dashboard 의 실 분포 보고 v2 정밀화).
     - `unknown` — 위 6 미해당 (boundary_partial 도 v1 에서 여기로).
   - 성공 케이스 정의 `is_failed`:
     - `answerable=True`: `accuracy == 1.0` → 성공.
     - `answerable=False`: `abstained AND not has_evidence` (= correct_refusal) → 성공.

2. **First-match-wins ordering 강제** — finding #1 의 87 case 가 `verifier_false_negative` 로 정확히 누적되도록.
   - 순서: verifier_fn → verifier_fp → retrieval_miss → planner_under_decomposition → generator_hallucination → context_dilution → unknown.
   - integration test (`tests/test_failure_classifier.py::TestAggregateFailureCategoriesIntegration`) 가 contract lock-in.

3. **신규 측정 표면 — additive schema** (`schema_version` bump 없음):
   - `case_results[*].failure_category: str | None` — per-case label.
   - `aggregate.failure_category_counts: dict[str, int]` — 7 키 모두 항상 emit (count 0 가능).

4. **Wiring 은 `eval/run_eval.py` 의 case_results post-process loop** — `score_case` 호출 후 `classify_failure(cr)` 부여. `eval/scorers/case.py` 무수정 (순환 import 회피).

5. **Deterministic — LLM call 0, trace JSON 의존성 0**. 모든 input 이 `case_result` dict 의 기존 필드 (audit doc 의 supply 1 spec 그대로). 결정성 검증은 unit test 9개 + integration 1개.

## Why these specific choices

| 결정 | 근거 |
|---|---|
| Rule-based (LLM 미사용) | audit 의 supply 1 spec 그대로. 7 카테고리가 모두 `case_result` dict 필드의 deterministic 술어로 표현 가능 — LLM 도입 시 비용 + 비결정성 둘 다 ROI 약함. |
| First-match-wins ordering | finding #1 의 87 case 가 silently 다른 카테고리 (e.g. retrieval_miss) 로 빠지면 supply 2/3 모두 wrong baseline 위에서 시작. integration test 가 `verifier_false_negative count == abstention_outcomes.incorrect_answer` 강제. |
| `verifier_false_negative` 가 최우선 | finding #1 = 본 audit 의 raw 측정 신호. 이 카테고리가 다른 branch 에 swallowed 되면 portfolio narrative 의 핵심 신호가 사라짐. |
| `retrieval_miss` > `planner_under_decomposition` | retrieval 실패면 planner 가 단일 attempt 로 끝낸 것도 *result* 일 뿐 *root cause* 아님. retrieval 먼저 진단. |
| `context_dilution` v1 비활성화 | chunk_id → doc_id 매핑이 `case_result` 에 부재 (retrieved_chunk_ids 는 raw string list). audit 의 정의 그대로 wiring 하려면 schema 확장 필요 → v1 scope 외. supply 2 dashboard 의 실 분포 보고 v2 정밀화. |
| `generator_hallucination` threshold = 0.5 | `score_claim_citation_alignment` 의 per-claim 0.5 acceptance threshold (`eval/scorers/alignment.py:89` overlap ≥ 0.5) 와 일관. 실 분포 모르므로 임의 v1; supply 2 분포 보고 조정. |
| Post-process in `run_eval.py` (case.py 무수정) | `case.py → score_case → classify_failure(returned dict)` 는 self-reference. 순환 회피 + `run_eval` 이 case_results loop 의 single owner. |
| Additive schema (no version bump) | ADR 0003 (answer dict) 와 무관 — `case_results` 는 eval-time scorer 출력. 신규 키만 추가 → downstream consumer (compare_eval / check_baseline_provenance) 무영향. |

## Consequences

- **Phase 5 audit item 1 (◐ partial → ✓ present)** 폐쇄. supply 2 (failure_distribution dashboard) + supply 3 (failure-mode-harden-process + ADR 0060) 의 prerequisite 충족.
- Finding #1 의 87 case 가 자동으로 `verifier_false_negative` 카테고리에 누적 → supply 2 가 첫 dashboard render 가능 → supply 3 가 ceiling regression test 가능.
- portfolio narrative 의 5-step cascade ("측정 → 함정 발견 → 함정 fix → 측정 표면 audit → 자동 게이트 도입 → process rationality 측정 도입") 의 다음 step = "root-cause stage 분류 표면 도입" (= 본 ADR).
- 신규 measurement surface 1차원 추가 — `failure_category_counts` aggregate 키 + `failure_category` per-case 키.
- production code path 0 변경 — `rag_*.py`, `api/`, `eval/config.yaml`, `eval/real_config.local.yaml` 모두 무수정.

## Invariance check

- **ADR 0001** (`naive_baseline` byte-identical) — read-only consumer, production 코드 0 변경 → 합성 baseline 영향 없음. 신규 키만 추가되므로 합성 `naive_baseline_top_k.json` golden 무영향.
- **ADR 0003** (answer dict `schema_version=2`) — 변경 없음. 본 PR 의 schema 추가는 `case_results` (eval scorer 출력) 이지 answer contract 와 무관.
- **ADR 0005** (private real / public synthetic 분리) — `reports/real100/baseline.aggregate.json` 의 신규 키 (`failure_category_counts`) 는 기존 aggregate-only 패턴 그대로. per-case `failure_category` 는 trace 와 동일 boundary (per-case eval_summary.json 은 gitignored, aggregate 만 commit).
- **ADR 0006** (LLM-judge real-data only) — 본 분류기는 LLM 미사용 → ADR 0006 의 비용/정직성 contract 무관.
- **ADR 0054** (substantive-only scorer semantics) — `is_failed` 정의가 ADR 0054 의 None-skip semantic 을 그대로 받아 처리 (None accuracy 케이스 = unanswerable, abstention 별도 branch 로 처리).
- **ADR 0055** (claim_validator PR gate) — 향후 `Claim: verifier_false_negative_rate=-X.Xpp` 같은 claim 도 `failure_category_counts` aggregate 으로 paired bootstrap CI 가능.
- **ADR 0056** (rationality_judge) — 본 분류기는 `case_result` consumer, rationality_judge 는 `trace JSON` consumer — 서로 직교 surface.

## Verification

<!-- verifies-key: eval/scorers/failure_classifier.py:def classify_failure -->
<!-- verifies-key: eval/scorers/failure_classifier.py:def aggregate_failure_categories -->
<!-- verifies-key: tests/test_failure_classifier.py:class TestAggregateFailureCategoriesIntegration -->

## Out-of-scope

- **Supply 2** — `scripts/render_failure_distribution.py` + `reports/real100/failure_distribution.{md,aggregate.json}` (~80 LOC). 본 PR 머지 후 즉시.
- **Supply 3** — `docs/operations/failure-mode-harden-process.md` + `tests/test_failure_rate_regression.py` + ADR 0060 (~150 LOC). supply 2 이후.
- **Finding #1 실제 fix** — `rag_verifier.py` unanswerable hardening + 별 ADR. 본 ADR 0059 의 정량화 결과를 before-baseline 으로 사용. 별 PR.
- **`context_dilution` v2 정밀화** — chunk_id → doc_id 매핑 추가 후. supply 2 분포 보고 ROI 판단.
- **`generator_hallucination` threshold 튜닝** — v1 = 0.5 임의값. supply 2 분포 보고 조정.
