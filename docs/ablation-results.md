# Ablation Results

이 문서는 커밋 가능한 집계 지표만 남긴다. Raw predictions, traces, logs, latency samples, per-example dumps는 `artifacts/benchmarks/` 아래에 생성되며 Git에 커밋하지 않는다.

## Latest Run

- Run ID: `public_synthetic_rfp_20260502T021448Z`
- Suite: `public_synthetic_rfp` / Dataset: `public_synthetic_rfp_v1`
- Git commit: `7d23eab541bee20fd014d7df0f4827761071de09`
- Baseline: `no_verifier_retry`
- Primary: `full`
- Local manifest: `artifacts/benchmarks/public_synthetic_rfp_20260502T021448Z/run_manifest.json`

## Baseline To Primary

| Metric | Baseline | Primary | Delta |
|---|---:|---:|---:|
| Accuracy | 1.000 | 1.000 | +0.000 |
| Groundedness | 0.769 | 1.000 | +0.231 |
| Citation Precision | 0.769 | 1.000 | +0.231 |
| Format Compliance | 0.769 | 1.000 | +0.231 |
| Abstention | 0.143 | 1.000 | +0.857 |
| Retry Rate | 0.000 | 0.231 | +0.231 |
| Latency p95 | 2.3ms | 3.7ms | +1.428 |

## Ablation Table

| Run | Metadata-first | Rerank | Verifier/Retry | Retrieval | Accuracy | Groundedness | Citation | Format | Abstention | Retry | Latency p95 |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| full | on | on | on | flat | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.231 | 3.7ms |
| hierarchical | on | on | on | hierarchical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.231 | 3.6ms |
| no_metadata_first | off | on | on | flat | 1.000 | 1.000 | 0.846 | 1.000 | 1.000 | 0.000 | 3.5ms |
| no_rerank | on | off | on | flat | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.231 | 2.7ms |
| no_verifier_retry | on | on | off | flat | 1.000 | 0.769 | 0.769 | 0.769 | 0.143 | 0.000 | 2.3ms |

## Interpretation

- `no_verifier_retry`는 verifier/retry를 끈 lightweight baseline이다.
- `full`는 metadata-first, rerank, verifier/retry를 모두 켠 primary run이다.
- latency와 retry는 품질 지표와 함께 본다. retry가 늘어도 groundedness, citation, abstention 개선이 동반되는지 확인한다.
- 현재 수치는 공개 synthetic RFP 평가셋 기준의 2차 가공 집계이며, 원본 RFP 문서나 raw example output은 포함하지 않는다.

## Next Actions

- 평가셋을 늘릴 때는 suite YAML을 추가하고 registry에는 집계 지표만 편입한다.
- private RFP 기반 실험은 local artifact로만 보관하고 문서에는 익명화된 집계 결과만 남긴다.
- citation 검증과 latency/retry 비용 분석은 별도 ablation axis로 분리해 누적한다.
