# Ablation Results

이 문서는 커밋 가능한 집계 지표만 남긴다. 원시 예측, 진단 로그, 지연시간 샘플, 오류 예시는 `artifacts/benchmarks/` 아래에 생성되며 Git에 커밋하지 않는다.

## Latest Run

- Run ID: `public_synthetic_rfp_20260511T101606Z`
- Suite: `public_synthetic_rfp` / Dataset: `public_synthetic_rfp_v1`
- Git commit: `3ee1796f2869cc8176fa99156d7e84316283cba1`
- Baseline: `naive_baseline`
- Primary: `full`
- Local manifest: `artifacts/benchmarks/public_synthetic_rfp_20260511T101606Z/run_manifest.json`

## Baseline To Primary

| Metric | Baseline | Primary | Delta |
|---|---:|---:|---:|
| Accuracy | 0.844 | 0.906 | +0.062 |
| Groundedness | 0.714 | 0.929 | +0.214 |
| Citation Precision | 0.512 | 0.905 | +0.393 |
| Citation Page Precision | N/A | N/A | N/A |
| Citation Region Precision | N/A | N/A | N/A |
| Citation Grounding | N/A | N/A | N/A |
| Format Compliance | 0.667 | 0.905 | +0.238 |
| Abstention | 0.300 | 1.000 | +0.700 |
| Retry Rate | 0.000 | 0.310 | +0.310 |
| Latency p95 | 2.9ms | 3.0ms | +0.063 |

## Ablation Table

| Run | Pipeline | Top-k | Metadata-first | Rerank | Verifier/Retry | Retrieval | Backend | Prompt | Accuracy | Groundedness | Citation | Citation Grounding | Format | Abstention | Retry | Latency p95 |
|---|---|---:|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| full | agentic_full | auto | on | on | on | flat | dense | structured_grounded_claims | 0.906 | 0.929 | 0.905 | N/A | 0.905 | 1.000 | 0.310 | 3.0ms |
| hierarchical | agentic_full | auto | on | on | on | hierarchical | dense | structured_grounded_claims | 0.906 | 0.929 | 0.905 | N/A | 0.905 | 1.000 | 0.310 | 2.9ms |
| hybrid_bm25 | agentic_full | auto | on | on | on | flat | hybrid | structured_grounded_claims | 0.906 | 0.929 | 0.905 | N/A | 0.905 | 1.000 | 0.310 | 3.1ms |
| naive_baseline | naive_baseline | 4 | off | off | off | flat | dense | minimal_grounded_extractive | 0.844 | 0.714 | 0.512 | N/A | 0.667 | 0.300 | 0.000 | 2.9ms |
| no_metadata_first | agentic_full | auto | off | on | on | flat | dense | structured_grounded_claims | 0.844 | 0.881 | 0.679 | N/A | 0.857 | 1.000 | 0.000 | 3.0ms |
| no_rerank | agentic_full | auto | on | off | on | flat | dense | structured_grounded_claims | 0.906 | 0.929 | 0.905 | N/A | 0.905 | 1.000 | 0.310 | 3.2ms |
| no_verifier_retry | agentic_full | auto | on | on | off | flat | dense | structured_grounded_claims | 0.906 | 0.762 | 0.762 | N/A | 0.714 | 0.300 | 0.000 | 2.8ms |

## Hard-case Slices

| Category | Cases | Accuracy | Groundedness | Citation | Citation Grounding | Format | Abstention | Retry |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| alias_entity | 2 | 1.000 | 1.000 | 1.000 | N/A | 1.000 | N/A | 0.000 |
| ambiguous_follow_up | 3 | N/A | 1.000 | 1.000 | N/A | 1.000 | 1.000 | 0.000 |
| answer_schema_v2 | 1 | 1.000 | 1.000 | 1.000 | N/A | 1.000 | N/A | 1.000 |
| chunk_boundary | 3 | 1.000 | 1.000 | 1.000 | N/A | 1.000 | N/A | 0.000 |
| follow_up_context | 1 | 1.000 | 1.000 | 1.000 | N/A | 1.000 | N/A | 0.000 |
| noisy_entity | 1 | 1.000 | 1.000 | 1.000 | N/A | 1.000 | N/A | 0.000 |
| one_sided_comparison | 3 | 0.000 | 0.000 | 0.000 | N/A | 0.000 | N/A | 1.000 |
| partial_comparison | 1 | 1.000 | 1.000 | 1.000 | N/A | 1.000 | N/A | 1.000 |
| retrieval_hardening | 5 | 1.000 | 1.000 | 1.000 | N/A | 1.000 | 1.000 | 0.000 |

## Interpretation

- `naive_baseline`는 fixed chunk + dense top-k만 쓰는 naive control baseline이다.
- `full`는 비교 대상 primary run이다.
- `Retrieval` 컬럼은 `retrieval_mode` (flat / hierarchical, ADR 0002), `Backend` 컬럼은 `retrieval_backend` (dense / hybrid, ADR 0010) 를 의미하며 두 축은 직교한다.
- latency와 retry는 품질 지표와 함께 본다. retry가 늘어도 groundedness, citation, abstention 개선이 동반되는지 확인한다.
- 현재 수치는 공개 synthetic RFP 평가셋 기준의 2차 가공 집계이며, 원본 RFP 문서나 raw example output은 포함하지 않는다.

## Next Actions

- 평가셋을 늘릴 때는 suite YAML을 추가하고 registry에는 집계 지표만 편입한다.
- private RFP 기반 실험은 local artifact로만 보관하고 문서에는 익명화된 집계 결과만 남긴다.
- citation 검증은 document/chunk precision과 page/region grounding을 분리해 누적한다.
- latency/retry 비용 분석은 별도 ablation axis로 분리해 누적한다.
