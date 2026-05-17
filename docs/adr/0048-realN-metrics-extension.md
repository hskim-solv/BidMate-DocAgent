# 0048: realN 메트릭 확장 — 필드별 accuracy + abstention calibration

- **Status**: accepted
- **Date**: 2026-05-15
- **Deciders**: hskim-solv
- **Related**: issue #870, ADR 0001, ADR 0003, ADR 0005, ADR 0030, ADR 0039, ADR 0044, ADR 0046

## TL;DR

- `eval_summary.json` 에 두 aggregate 추가: `by_metadata_field` (4개 단일-doc 필드 per-필드 정확도) + `abstention_calibration` (ECE + Brier)
- 두 aggregate 는 forward-compatible (태그/`confidence` 없는 케이스는 자동 제외 또는 `null`)
- ADR 0005 aggregate-only allowlist 준수, ADR 0001 baseline bit-identical

## 배경

ADR 0044 가 real100 케이스를 n=21 → n≥30 (장기 n≥50) 으로 확장했지만 메트릭 표면 미변경. aggregate 레벨에 측정 blindspot 두 개 잔존:

1. **Per-field 정확도가 collapse.** `data/data_list.csv` 가 92–100% fill rate 의 4개 단일-doc 메타데이터 필드 carry (`발주 기관` 100%, `사업명` 100%, `사업 금액` 99%, `입찰 참여 마감일` 92%). 네 개 모두 [`eval/run_eval.py:metric_block`](../../eval/run_eval.py) 의 단일 `accuracy` 숫자로 collapse; 운영자가 검증기가 deadline vs 예산 vs 기관 struggle 인지 구분 못 함. `by_hardcase_category` aggregate ([`eval/run_eval.py:682`](../../eval/run_eval.py)) 가 bucket-by-tag 패턴 작동 입증 — 같은 접근법이 4개 메타데이터 필드에 지금까지 decline.

2. **보류는 count 있으나 calibration 없음.** `abstention_outcomes` (#463, [`eval/run_eval.py:_abstention_outcomes`](../../eval/run_eval.py)) 가 3개 boundary bucket split, `abstention` 은 0/1 rate, 그러나 검증기 confidence 가 ground-truth correctness 와 align 하는지 측정하는 calibration 메트릭 (ECE / Brier) 없음. 없으면 "검증기가 50% 보류" 가 "검증기가 옳은 50% 에 보류" 와 구분 불가.

`by_hardcase_category` + `abstention_outcomes` 가 이미 ADR 0005 aggregate-only allowlist (PR #849, closes #845) 에 있음. ADR 0044 의 n=50 기준선 re-cut 전 두 aggregate 키 추가가 최소 incremental 측정 표면.

## 결정

`metric_block` 당 `eval_summary.json` 에 두 aggregate 추가:

1. **`by_metadata_field`**: per-필드 블록 (4개 단일-doc 메타데이터 필드 `by_hardcase_category` / `by_query_type` 와 같은 모양). 각 케이스가 config 에 `metadata_field: <agency|project|budget|deadline>` 설정해 opt-in; 키 없는 케이스는 per-필드 aggregate 에서 단순 제외 (forward-compatible).

   허용 값은 [`eval/scorers/_shared.py`](../../eval/scorers/_shared.py) 에 `METADATA_FIELD_KEYS = ("agency", "project", "budget", "deadline")` 로 pin. `eval/run_eval.py::load_config` 가 미지 `metadata_field` 케이스 reject.

2. **`abstention_calibration`**: 단일 dict 가 carry:
   - `ece`: `[0, 1]` 의 10개 fixed-width bin 으로 Expected Calibration Error
   - `brier`: Brier score (confidence 와 correctness 의 mean squared error)
   - `n`: 기여 케이스 수 (`prediction.answer` 에 numeric `confidence` ∈ `[0, 1]` 있는 것들)

   `confidence` carry 케이스 없으면 전체 블록을 `{ece: 0.0, ...}` 아닌 `null` 로 emit. 본 ADR 전 생산된 기존 스냅샷은 forward-compatible, `null` 로 render.

   `score_case` 가 `prediction.answer.confidence` 에서 케이스 결과로 `confidence` pass; aggregator 가 결과에서 읽음. `correctness` 신호는 보류 케이스의 `1 - abs(abstained - answerable_is_false)` (정확 refusal score 1, 부정확 답변 score 0).

두 aggregate 모두 aggregate-only allowlist 에 land; per-case payload 가 ADR 0005 경계 cross 안 함.

## 결과

- `reports/eval_summary.json` 가 `by_metadata_field` (dict, 비어있을 수 있음) + `abstention_calibration` (dict 또는 null) 키 획득. 둘 다 `reports/real100/baseline.aggregate.json` 스냅샷으로 flow
- 리더보드 (ADR 0030) 가 real100 케이스 태깅 후 두 새 컬럼 render 가능: per-필드 정확도 strip (4셀) + ECE/Brier (2셀). 본 ADR 은 리더보드 변경 안 함; 스택의 PR3 가 함
- ADR 0001 불변량: 파이프라인 동작 미변경. 두 aggregate 모두 `run_rag_query` 다운스트림 계산. 케이스셋 미변경 한 `naive_baseline` row 가 pre-0048 run 과 bit-identical
- ADR 0044 in-place 확장: `metadata_field` 태깅된 새 케이스가 `by_metadata_field` 자동 populate. 태그 없는 기존 21개 케이스는 헤드라인 `accuracy` 만 유지
- ADR 0039 영향 없음: 본 ADR 은 `by_metadata_field` 키 추가 (per RFP 필드), `by_hardcase_category` 키 (per HWP 구조 실패 모드) 와 평행하지만 구별
- `abstention_calibration` 블록은 미래 ADR 이 답변 dict (ADR 0003 `schema_version: 2`) 가 `confidence` 필드 emit 의무화할 때까지 `null` 유지. 본 ADR 은 emission 요구 안 함; rollout 단계화 가능하도록 aggregator 측 계약만 정의
- CI 안전: 새 의존성 없음, LLM 호출 없음, 모든 logic 이 기존 케이스 결과 필드 산술

## 검토한 대안

- **Per-필드를 `by_query_type.single_doc` 내 sub-key 로**: 거부. `by_query_type` 는 `query_type ∈ {single_doc, comparison, follow_up, abstention}` 으로 이미 완전; `single_doc` 내 4-way split 중첩은 shadow. peer-level `by_metadata_field` aggregate 가 `by_hardcase_category` 와 평행이고 기존 read 패턴 매치
- **즉시 `confidence` emission 요구**: 거부. 답변 dict 계약 (ADR 0003) 가 아직 confidence 필드 spec 안 함, 본 PR 에서 모든 파이프라인에 강제하면 두 결정 mix. forward-compatible null 이 안전한 단계화
- **Platt-scaled ECE 또는 quantile binning 사용**: 연기. Fixed-width 10-bin ECE 가 first-pass calibration 측정 표준 + 현재 small-n 체제 (n=30–50) 매치. Quantile binning 은 n≥200 에서 흥미

## Verification

`by_metadata_field` 와 `abstention_calibration` aggregate 가 PR3 (n=50 re-measurement) land 시 committed real100 기준선에 flow. 그 전까지 키가 smoke run 의 `reports/eval_summary.json` 에 출현 필수.

<!-- verifies-key: reports/eval_summary.json:by_metadata_field -->
<!-- verifies-key: reports/eval_summary.json:abstention_calibration -->
<!-- verifies-key: eval/scorers/_shared.py:METADATA_FIELD_KEYS -->
