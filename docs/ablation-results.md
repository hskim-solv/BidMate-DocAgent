# Ablation Results

이 문서는 커밋 가능한 집계 지표만 남긴다. Raw predictions, traces, logs, latency samples, error examples는 `artifacts/benchmarks/` 아래에 생성되며 Git에 커밋하지 않는다.

## Latest Run

- Run ID: `issue28_naive_baseline`
- Suite: `public_synthetic_rfp` / Dataset: `public_synthetic_rfp_v1`
- Git commit: `9c85abd864352a630b144459617c22d862f8f5a7`
- Baseline: `naive_baseline`
- Primary: `full`
- Local manifest: `artifacts/benchmarks/issue28_naive_baseline/run_manifest.json`

## Baseline To Primary

| Metric | Baseline | Primary | Delta |
|---|---:|---:|---:|
| Accuracy | 0.947 | 1.000 | +0.053 |
| Groundedness | 0.731 | 1.000 | +0.269 |
| Citation Precision | 0.519 | 1.000 | +0.481 |
| Format Compliance | 0.731 | 1.000 | +0.269 |
| Abstention | 0.143 | 1.000 | +0.857 |
| Retry Rate | 0.000 | 0.231 | +0.231 |
| Latency p95 | 2.1ms | 1.7ms | -0.410 |

## Ablation Table

| Run | Pipeline | Top-k | Metadata-first | Rerank | Verifier/Retry | Retrieval | Prompt | Accuracy | Groundedness | Citation | Format | Abstention | Retry | Latency p95 |
|---|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| full | agentic_full | auto | on | on | on | flat | structured_grounded_claims | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.231 | 1.7ms |
| hierarchical | agentic_full | auto | on | on | on | hierarchical | structured_grounded_claims | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.231 | 2.4ms |
| naive_baseline | naive_baseline | 4 | off | off | off | flat | minimal_grounded_extractive | 0.947 | 0.731 | 0.519 | 0.731 | 0.143 | 0.000 | 2.1ms |
| no_metadata_first | agentic_full | auto | off | on | on | flat | structured_grounded_claims | 0.947 | 0.962 | 0.750 | 0.962 | 1.000 | 0.000 | 18.1ms |
| no_rerank | agentic_full | auto | on | off | on | flat | structured_grounded_claims | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.231 | 2.9ms |
| no_verifier_retry | agentic_full | auto | on | on | off | flat | structured_grounded_claims | 1.000 | 0.769 | 0.769 | 0.769 | 0.143 | 0.000 | 3.2ms |

## Interpretation

- `naive_baseline`는 fixed chunk + dense top-k만 쓰는 naive control baseline이다.
- `full`는 비교 대상 primary run이다.
- "Retrieval" 컬럼은 `retrieval_mode` (flat / hierarchical) 를 의미한다. ADR 0010 에서 추가한 `retrieval_backend` (dense / hybrid) 는 직교 축이며, 다음 benchmark 스냅샷에서 별도 컬럼 또는 row 로 누적할 예정이다.
- latency와 retry는 품질 지표와 함께 본다. retry가 늘어도 groundedness, citation, abstention 개선이 동반되는지 확인한다.
- 현재 수치는 공개 synthetic RFP 평가셋 기준의 2차 가공 집계이며, 원본 RFP 문서나 raw example output은 포함하지 않는다.

## Pending rows

- **`hybrid_bm25`** (ADR 0010, issue #119): `eval/config.yaml` 에 추가됨. `make eval` 의 ablation 블록에는 이미 채워지지만 (`accuracy=0.906`, `groundedness=0.929` — `full` 과 동일 ceiling), 본 문서의 committed snapshot 은 `make benchmark` 의 manifest 기반이므로 다음 benchmark 실행 후 row 를 추가한다. 실측 차이는 private real-data eval (`make real-eval-delta`) 에서 드러날 가능성이 크다.
- **KO RFP per-axis** (issue #126): `eval/ko_axes.py` 에 `detect_ko_axes()` 가 추가되어 dev 결과 CSV 를 `eval/evaluate_dev_results.py` 로 평가할 때 `summary["by_ko_axes"]` 블록으로 per-axis (`금액단위 / 날짜형식 / 한자 / 사업번호 / 약칭`) accuracy 가 emit 된다. 차기 dev-side run 결과를 본 표에 별도 row 로 누적한다. `eval/run_eval.py` (CI 표면) 으로의 승격은 후속 PR.

## Next Actions

- 평가셋을 늘릴 때는 suite YAML을 추가하고 registry에는 집계 지표만 편입한다.
- private RFP 기반 실험은 local artifact로만 보관하고 문서에는 익명화된 집계 결과만 남긴다.
- citation 검증과 latency/retry 비용 분석은 별도 ablation axis로 분리해 누적한다.
- 다음 benchmark 실행 시 `hybrid_bm25` row 를 위 표에 추가하고 `retrieval_backend` 컬럼을 도입한다.
