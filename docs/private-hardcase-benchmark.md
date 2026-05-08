# Private Hard-case Benchmark

이 문서는 이슈 #24의 private hard-case benchmark 운영 기준을 정리한다. 목적은 공개 synthetic benchmark를 대체하는 것이 아니라, scanned PDF, rotated/skewed page, table-heavy page, mixed layout, noisy OCR 조건에서 parser/retrieval/answer failure가 얼마나 늘어나는지 aggregate로 비교하는 것이다.

## Commit Boundary

커밋 가능한 항목은 benchmark template, 익명 case id, aggregate metric, failure taxonomy, 실행 절차뿐이다.

커밋하지 않는 항목은 다음과 같다.

- 원본 private RFP 문서
- 원본 파일명, 기관명, 사업명처럼 출처를 복원할 수 있는 식별자
- raw private predictions, traces, per-example dumps
- OCR로 추출된 원문 snippet을 포함한 private artifact

로컬 입력은 `.gitignore` 대상인 `data/files/`, `data/data_list.csv`, `eval/*.local.yaml`을 사용한다. 실행 산출물은 `artifacts/benchmarks/` 아래에만 둔다.

## Case List

`eval/private_hardcase.example.yaml`을 `eval/private_hardcase.local.yaml`로 복사한 뒤 로컬 환경에서만 채운다. 각 case는 익명 ID와 difficulty slice만 남긴다.

지원하는 기본 slice는 다음과 같다.

- `scanned_pdf`
- `rotated_or_skewed`
- `table_heavy`
- `mixed_layout`
- `noisy_ocr`

한 case는 여러 slice에 속할 수 있다. `eval/run_eval.py`는 `by_hardcase_category`를 생성해 전체 평균뿐 아니라 slice별 accuracy, groundedness, citation precision, answer format, abstention, retry를 함께 보고한다.

## Running Locally

private suite template은 그대로 실행하지 않고 로컬 파일로 복사해 경로를 맞춘다.

```bash
cp eval/private_hardcase.example.yaml eval/private_hardcase.local.yaml
cp benchmarks/suites/private_hardcase_rfp.example.yaml benchmarks/suites/private_hardcase_rfp.local.yaml
```

v1 text ingestion과 v2 visual parsing을 비교하려면 같은 익명 case list를 사용하고 index build command만 바꾼 suite를 각각 실행한다.

```bash
python3 scripts/run_benchmark.py \
  --suite benchmarks/suites/private_hardcase_rfp.local.yaml \
  --ablations benchmarks/ablations/rag_quality_axes.yaml
```

생성된 `artifacts/benchmarks/<run_id>/run_manifest.json`을 확인한 뒤 aggregate만 registry/docs에 반영한다.

```bash
python3 scripts/summarize_benchmark.py \
  --manifest artifacts/benchmarks/<run_id>/run_manifest.json
```

## Failure Analysis

parser-stage 분석은 `eval/run_parser_eval.py`의 taxonomy를 사용한다. gold YAML도 private local 파일로만 유지하고, `hardcase_categories`를 문서 단위로 기록하면 report의 `summary.by_hardcase_category`에서 OCR/layout/table/field/bbox failure count가 slice별로 집계된다.

```bash
python3 eval/run_parser_eval.py \
  --artifact_dir data/index-private-hardcase/visual_artifacts \
  --gold eval/private_parser_gold.local.yaml \
  --output_dir reports \
  --run_name private_visual_v2 \
  --parser_version 2
```

분석 문서에는 public synthetic benchmark와 private hard-case slice의 aggregate 차이만 적는다. 예를 들어 public에서는 citation precision이 유지되지만 `table_heavy`에서 table cell F1과 citation precision이 같이 떨어지면 table reconstruction failure가 grounded answer 품질에 미치는 영향으로 분류한다.

## Aggregate Comparison Report

실제 private 문서가 저장소에 없기 때문에 이 저장소에는 실측 private 수치를 커밋하지 않는다. private run 이후에는 아래 형식으로 aggregate만 남긴다.

| Slice | Public primary | Private hard-case primary | Delta | Likely failure stage |
|---|---:|---:|---:|---|
| overall accuracy | public aggregate | private aggregate | private - public | parser/retrieval/answer |
| citation precision | public aggregate | private aggregate | private - public | retrieval/citation grounding |
| table_heavy citation precision | N/A or public proxy | private aggregate | N/A | table/parser |
| noisy_ocr groundedness | N/A or public proxy | private aggregate | N/A | OCR/retrieval |
| rotated_or_skewed bbox alignment | N/A or parser fixture | private aggregate | N/A | bbox/layout |

failure increase는 `summary.by_hardcase_category`, `by_hardcase_category`, `failure_counts`, `retry_reason_counts`를 함께 보고 분류한다. private aggregate가 public 대비 악화되었지만 parser failure count가 늘지 않았다면 retrieval/rerank/answer policy 쪽을 우선 의심한다.
