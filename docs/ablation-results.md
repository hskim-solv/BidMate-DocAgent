# Ablation Results

이 문서는 커밋 가능한 집계 지표만 남긴다. Raw predictions, traces, logs, latency samples, per-example dumps는 `artifacts/benchmarks/` 아래에 생성되며 Git에 커밋하지 않는다.

## Latest Run

- Run ID: `public_synthetic_rfp_20260508T022829Z`
- Suite: `public_synthetic_rfp` / Dataset: `public_synthetic_rfp_v1`
- Git commit: `3657f1efd22e9dd2351afc260a7650c500e5940b`
- Baseline: `naive_keyword`
- Primary: `full`
- Local manifest: `artifacts/benchmarks/public_synthetic_rfp_20260508T022829Z/run_manifest.json`

## Baseline To Primary

| Metric | Baseline | Primary | Delta |
|---|---:|---:|---:|
| Accuracy | 1.000 | 1.000 | +0.000 |
| Groundedness | 0.769 | 1.000 | +0.231 |
| Citation Precision | 0.596 | 1.000 | +0.404 |
| Format Compliance | 0.769 | 1.000 | +0.231 |
| Abstention | 0.143 | 1.000 | +0.857 |
| Retrieval Recall@3 | 0.921 | 1.000 | +0.079 |
| Retrieval MRR | 0.974 | 1.000 | +0.026 |
| Retry Rate | 0.000 | 0.231 | +0.231 |
| Latency p95 | 52.7ms | 217.8ms | +165.090 |

## Ablation Table

| Run | Strategy | Metadata-first | Rerank | Verifier/Retry | Retrieval@3 | MRR | Accuracy | Groundedness | Citation | Format | Abstention | Retry | Latency p95 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| dense_only | dense | off | off | off | 0.947 | 0.947 | 0.947 | 0.731 | 0.615 | 0.731 | 0.143 | 0.000 | 320.7ms |
| full | metadata_rerank | on | on | on | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.231 | 217.8ms |
| hierarchical | hierarchical | on | on | on | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.231 | 160.4ms |
| naive_keyword | naive | off | off | off | 0.921 | 0.974 | 1.000 | 0.769 | 0.596 | 0.769 | 0.143 | 0.000 | 52.7ms |
| no_metadata_first | flat | off | on | on | 1.000 | 0.974 | 1.000 | 1.000 | 0.846 | 1.000 | 1.000 | 0.000 | 131.7ms |
| no_rerank | flat | on | off | on | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.231 | 124.8ms |
| no_verifier_retry | flat | on | on | off | 1.000 | 1.000 | 1.000 | 0.769 | 0.769 | 0.769 | 0.143 | 0.000 | 201.9ms |

## Interpretation

- `naive_keyword`는 metadata/rerank/verifier를 끈 naive baseline이다.
- `full`는 metadata-first, rerank, verifier/retry를 모두 켠 primary run이다.
- Retrieval@3와 MRR은 answer formatting과 별도로 expected document가 검색 후보에 들어왔는지 확인한다.
- latency와 retry는 품질 지표와 함께 본다. retry가 늘어도 groundedness, citation, abstention 개선이 동반되는지 확인한다.
- 현재 수치는 공개 synthetic RFP 평가셋 기준의 2차 가공 집계이며, 원본 RFP 문서나 raw example output은 포함하지 않는다.

## Next Actions

- 평가셋을 늘릴 때는 suite YAML을 추가하고 registry에는 집계 지표만 편입한다.
- private RFP 기반 실험은 local artifact로만 보관하고 문서에는 익명화된 집계 결과만 남긴다.
- citation 검증과 latency/retry 비용 분석은 별도 ablation axis로 분리해 누적한다.
