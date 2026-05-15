# RAG Pipeline EDA

7-axis profile of pipeline dynamics observed in ``eval_summary.json``. ADR 0005 boundary: case-level data (case.id, query, answer, evidence text, retrieved/gold chunk IDs, doc IDs) is read for *numeric aggregation only*. Only means, percentiles, counts, ratios, and Pearson scalars are rendered.

Sources: ``reports/eval_summary.json``, ``reports/real100/baseline.aggregate.json``

## Axis 1 — Retrieval efficiency

- cases: **105** (with gold_chunk_ids: 82)

| metric | n | p10 | p50 | p90 | mean |
|---|---|---|---|---|---|
| recall@5 | 82 | 0.275 | 1.000 | 1.000 | 0.864 |
| recall@10 | 82 | 0.275 | 1.000 | 1.000 | 0.864 |
| recall@20 | 82 | 0.275 | 1.000 | 1.000 | 0.864 |
| MRR | 82 | 0.250 | 1.000 | 1.000 | 0.825 |
| NDCG@10 | 82 | 0.315 | 1.000 | 1.000 | 0.816 |
| NDCG@20 | 82 | 0.315 | 1.000 | 1.000 | 0.816 |

### Selected top_k histogram

| top_k | n |
|---|---|
| 4 | 92 |

## Axis 2 — Reranker contribution

| metric | n_cases | mean_delta | p50_delta | %_improved | %_unchanged | %_regressed |
|---|---|---|---|---|---|---|
| rerank Δ MRR | 0 | — | — | — | — | — |
| rerank Δ NDCG@10 | 0 | — | — | — | — | — |

## Axis 3 — Verification & retry

- verify_rate (verified / verified+failed): **100.0%**
- breakdown: verified=92, not_verified=0, no_attempts_logged=13

### Attempts distribution

| attempts | n | share |
|---|---|---|
| 1 | 105 | 100.0% |

_Baseline retry_effectiveness:_ recovery_rate=0.333, residual_failure=—, retry_lift_vs_no_retry=-0.212

## Axis 4 — Stage latency composition

- end-to-end latency_ms (n=105): p50=2.010, p95=3.406, mean=2.136

| stage | n | p50 | p95 | mean | share_of_e2e |
|---|---|---|---|---|---|
| `query_analysis_ms` | 105 | 1.150 | 2.556 | 1.314 | 61.5% |
| `context_resolution_ms` | 105 | 0.000 | 0.008 | 0.001 | 0.0% |
| `retrieve_ms` | 0 | — | — | — | — |
| `verify_ms` | 0 | — | — | — | — |
| `answer_generation_ms` | 105 | 0.270 | 0.418 | 0.247 | 11.6% |

### Cold vs warm e2e latency (ms)

| cohort | n | p50 | p95 | mean |
|---|---|---|---|---|
| cold | 1 | 2.640 | 2.640 | 2.640 |
| warm | 104 | 2.010 | 3.417 | 2.131 |

## Axis 5 — Answer synthesis & confidence

- confidence (n=0): p10=—, p50=—, p90=—, mean=—

### Confidence histogram

| bin | n |
|---|---|
| [0.0,0.2) | 0 |
| [0.2,0.4) | 0 |
| [0.4,0.6) | 0 |
| [0.6,0.8) | 0 |
| [0.8,1.0) | 0 |

### Abstention by query_type

| query_type | n | abstained | rate |
|---|---|---|---|
| abstention | 22 | 5 | 22.7% |
| comparison | 25 | 0 | 0.0% |
| follow_up | 22 | 6 | 27.3% |
| single_doc | 36 | 2 | 5.6% |

### Answer status distribution

| status | n |
|---|---|
| `insufficient` | 13 |
| `supported` | 92 |

- overall answer_format_compliance mean: 0.619

## Axis 6 — Evidence quality (recall × citation × groundedness)

- paired cases: n=82 (recall@10≥0.5, citation_precision≥0.5)

| | cite_hi | cite_lo |
|---|---|---|
| recall_hi | 75.6% | 13.4% |
| recall_lo | 0.0% | 11.0% |

- Pearson(recall@10, citation_precision) = 0.552
- Pearson(recall@10, groundedness) = 0.681

## Axis 7 — Cold-start vs warm

| cohort | n | e2e_p50 | e2e_p95 | retrieve_p50 |
|---|---|---|---|---|
| cold | 1 | 2.640 | 2.640 | — |
| warm | 104 | 2.010 | 3.417 | — |

- Δ retrieve_ms p50 (cold − warm) = —
- Δ e2e_ms p50 (cold − warm) = 0.630

## Figures

- `real100_rag_cold_warm.png`
- `real100_rag_cold_warm.svg`
- `real100_rag_confidence.png`
- `real100_rag_confidence.svg`
- `real100_rag_evidence_joint.png`
- `real100_rag_evidence_joint.svg`
- `real100_rag_rerank_delta.png`
- `real100_rag_rerank_delta.svg`
- `real100_rag_retrieval_recall.png`
- `real100_rag_retrieval_recall.svg`
- `real100_rag_retry_reasons.png`
- `real100_rag_retry_reasons.svg`
- `real100_rag_stage_latency.png`
- `real100_rag_stage_latency.svg`

