# 0098: agentic confidence 방출로 abstention calibration 활성화

- **Status**: proposed
- **Date**: 2026-06-02
- **Deciders**: hskim-solv
- **Related**: issue #1820, ADR 0001, ADR 0003, ADR 0005, ADR 0048, ADR 0056

## TL;DR

- agentic 경로(`verifier_retry=True`)만 답변 dict 에 `confidence` ∈ [0,1] 방출. ADR 0048 §50/§56 이 "미래 ADR" 로 연기한 emission 을 fulfill
- semantic = **P(decision correct)** — `eval/run_eval.py:_calibration_correctness` 타겟과 정합 (answerable→정확도, unanswerable→보류 성공). U-shape 매핑: 강한 답변·강한 보류 둘 다 high, 모호한 중간 low
- ADR 0003 additive (schema_version bump 없음, 핀 계약 스냅샷 제외), ADR 0001 baseline 은 naive 가 `verifier_retry=False` 라 confidence 부재 → byte-identical **구조적** 보존

## 배경

ADR 0048 이 `abstention_calibration` aggregate (ECE 10-bin + Brier) 를 추가했으나, 답변 dict 가 `confidence` 를 방출하지 않아 블록이 영구 `null`. §50: "abstention_calibration 블록은 미래 ADR 이 답변 dict (ADR 0003 `schema_version: 2`) 가 `confidence` 필드 방출 의무화할 때까지 null 유지"; §56 (검토한 대안): "즉시 confidence emission 요구: 거부 ... forward-compatible null 이 안전한 단계화". 본 ADR 이 그 단계다.

측정 blindspot: `abstention_outcomes` (#463) 가 보류 rate 는 carry 하나, 검증기 결정의 confidence 가 ground-truth correctness 와 align 하는지 측정 불가. confidence 없으면 "검증기가 50% 보류" 와 "검증기가 *옳은* 50% 에 보류" 가 구분 안 됨.

## 결정

agentic 경로가 검증기의 grounding 결정을 `confidence` ∈ [0,1] 로 방출한다.

1. **Source** — `rag_answer.py:_answer_confidence(status, reasons)` 가 검증기 산출(`status` + `verification_reasons`)을 `P(decision correct)` 로 매핑. 새 모델·LLM 호출 없음, 순수 분기.

2. **Semantic** = `P(decision correct)`. `_calibration_correctness` 정의(answerable→`accuracy==1.0`, unanswerable→`abstention==1.0`)와 일치 — 진짜 unanswerable 쿼리에 대한 확신에 찬 보류는 *옳은* high-confidence 결정. (`P(answer correct)` 는 보류의 정오를 측정 못 해 거부, 아래.)

3. **U-shape 4-tier 매핑** (first-pass 가설):

   | status / reason | confidence | 근거 (RFP 도메인) |
   |---|---|---|
   | `supported` | 0.90 | 근거가 grounded 된 답변 — 결정이 옳을 확률 높음 |
   | `partial` | 0.45 | 일부 entity 만 grounded — 모호한 중간, 틀릴 여지 |
   | `insufficient` + `no_evidence` | 0.85 | "문서에 해당 정보 없음" 의 확신에 찬 보류 — 옳은 거부 |
   | `insufficient` + 기타(`low_top_score`/`topic_not_grounded`) | 0.55 | 약한 근거 보류 — 진짜 답을 놓쳤을 여지, 모호한 중간 |

4. **Emission gate** = agentic-only. naive_baseline 은 검증기를 호출하지 않아(`verifier_retry=False`) confidence signal 이 물리적으로 부재 — gate 는 bolt-on 이 아니라 자연스러운 데이터-흐름 경계. `rag_core.py:_phase_build_answer` 가 `emit_confidence=ctx.verifier_retry` 로 전달.

5. **계약** — additive nullable-optional. `schema_version` 유지(=2). `render_answer_text` *이후* 추가해 답변 텍스트 렌더링 무영향. 핀 계약 스냅샷(`tests/test_answer_contract_snapshot.py` 의 `_extract_contract_subset`)에서 제외 — `analysis`/`plan` 과 동급의 관측(observability) 필드.

## 결과

- **핵심 trade-off: 계약 진화(ADR 0003 additive) ↔ baseline 불변(ADR 0001).** 둘은 additive + agentic-gate 로 양립. confidence 를 핀 계약 스냅샷에서 제외해 ADR 0001 guard test (`test_answer_contract_snapshot.py`) 가 무수정 green — naive_baseline 답변 dict byte-identical.
- ADR 0048 `abstention_calibration` 블록이 agentic run 에서 non-null 로 활성화 *가능*해짐. 실제 활성화(real100_v2 eval 재생성)는 PR-2 이며 ADR 0048 scope.
- naive_baseline byte-identity 는 **구조적** 보존 — 별도 코드 가드가 아니라 "naive 는 검증기 미호출 → confidence signal 부재" 라는 데이터 흐름 사실에서 따라옴.
- 매핑 4값은 first-pass 가설. ECE/Brier 가 well-calibrated 여부를 측정; follow-up 이 데이터로 튜닝(guesswork 아님).
- CI 안전: 새 의존성·LLM 호출 없음, 기존 status/reason 필드 산술.

## 검토한 대안

- **`P(answer correct)` semantic (보류 무시)**: 거부. 보류는 ADR 0003 일급 상태인데 보류 결정의 정오를 측정 못 함. `_calibration_correctness` 가 이미 보류를 채점하므로 semantic mismatch — calibration 이 무의미해짐.
- **모든 경로 방출 (naive 포함)**: 거부. ADR 0001 byte-identity 위반 + naive 는 검증기 signal 부재라 방출할 값이 없음.
- **`schema_version` bump**: 거부. additive nullable-optional 은 기존 reader 무영향 (ADR 0003 forward-compat). bump 는 불필요한 breaking 신호.
- **연속 confidence (검증기 raw score 노출)**: 연기. 현 검증기는 boolean + reason 리스트; raw score 노출은 별도 검증기 리팩터. 4-tier 가 first-pass, calibration 측정 후 재방문.

## Verification

emission 메커니즘은 PR-1 의 코드(`rag_answer.py:_answer_confidence` + `rag_core.py` agentic gate) + 단위 테스트로 reflected:

- `tests/test_confidence_emission_regression.py`: agentic 경로 `confidence` ∈ [0,1] float + 결정성; naive_baseline 답변 dict 에 `confidence` 키 **부재** (ADR 0001 guard); `test_answer_contract_snapshot.py` 무수정 green
- calibration 계산 단위 테스트: known (confidence, correctness) pairs → 정확한 ece/brier/n; confidence 없는 케이스 → `null` path

**proposed → accepted 승격 조건**: real100_v2 eval (PR-2 eval regen) 에서 `abstention_calibration` 블록이 non-null 로 출현 = 측정 표면이 실제 활성화됨을 e2e 입증한 시점.

<!-- verifies-key: rag_answer.py:_answer_confidence -->
<!-- verifies-key: tests/test_confidence_emission_regression.py:confidence -->
<!-- verifies-key: reports/eval_summary.json:abstention_calibration -->
