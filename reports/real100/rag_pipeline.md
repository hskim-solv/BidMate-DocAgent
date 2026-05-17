# RAG Pipeline EDA

7-axis profile of pipeline dynamics observed in ``eval_summary.json``. ADR 0005 boundary: case-level data (case.id, query, answer, evidence text, retrieved/gold chunk IDs, doc IDs) is read for *numeric aggregation only*. Only means, percentiles, counts, ratios, and Pearson scalars are rendered.

Sources: ``reports/real100/eval_summary.json``, ``reports/real100/baseline.aggregate.json``

## Axis 1 — Retrieval efficiency

- cases: **36** (with gold_chunk_ids: 0)

| metric | n | p10 | p50 | p90 | mean |
|---|---|---|---|---|---|
| recall@5 | 0 | — | — | — | — |
| recall@10 | 0 | — | — | — | — |
| recall@20 | 0 | — | — | — | — |
| MRR | 0 | — | — | — | — |
| NDCG@10 | 0 | — | — | — | — |
| NDCG@20 | 0 | — | — | — | — |

### Selected top_k histogram

| top_k | n |
|---|---|
| 4 | 6 |
| 8 | 21 |

## Axis 2 — Reranker contribution

| metric | n_cases | mean_delta | p50_delta | %_improved | %_unchanged | %_regressed |
|---|---|---|---|---|---|---|
| rerank Δ MRR | 0 | — | — | — | — | — |
| rerank Δ NDCG@10 | 0 | — | — | — | — | — |

## Axis 3 — Verification & retry

- verify_rate (verified / verified+failed): **81.5%**
- breakdown: verified=22, not_verified=5, no_attempts_logged=9

### Attempts distribution

| attempts | n | share |
|---|---|---|
| 1 | 16 | 44.4% |
| 2 | 16 | 44.4% |
| 3+ | 4 | 11.1% |

### Retry trigger reasons (case-level)

| reason | count |
|---|---|
| `missing_comparison_doc` | 21 |
| `missing_comparison_entity` | 21 |
| `topic_not_grounded` | 9 |

_Baseline retry_effectiveness:_ recovery_rate=0.333, residual_failure=—, retry_lift_vs_no_retry=-0.212

## Axis 4 — Stage latency composition

- end-to-end latency_ms (n=36): p50=116.620, p95=284.608, mean=139.748

| stage | n | p50 | p95 | mean | share_of_e2e |
|---|---|---|---|---|---|
| `query_analysis_ms` | 36 | 95.485 | 265.680 | 120.417 | 86.2% |
| `context_resolution_ms` | 36 | 0.000 | 0.013 | 0.003 | 0.0% |
| `retrieve_ms` | 0 | — | — | — | — |
| `verify_ms` | 0 | — | — | — | — |
| `answer_generation_ms` | 36 | 0.450 | 2.295 | 0.778 | 0.6% |

### Cold vs warm e2e latency (ms)

| cohort | n | p50 | p95 | mean |
|---|---|---|---|---|
| cold | 1 | 78.190 | 78.190 | 78.190 |
| warm | 35 | 116.860 | 287.253 | 141.507 |

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
| abstention | 18 | 10 | 55.6% |
| single_doc | 18 | 2 | 11.1% |

### Answer status distribution

| status | n |
|---|---|
| `insufficient` | 12 |
| `partial` | 2 |
| `supported` | 22 |

- overall answer_format_compliance mean: 0.667

## Axis 6 — Evidence quality (recall × citation × groundedness)

- paired cases: n=0 (recall@10≥0.5, citation_precision≥0.5)

| | cite_hi | cite_lo |
|---|---|---|
| recall_hi | — | — |
| recall_lo | — | — |

- Pearson(recall@10, citation_precision) = —
- Pearson(recall@10, groundedness) = —

## Axis 7 — Cold-start vs warm

| cohort | n | e2e_p50 | e2e_p95 | retrieve_p50 |
|---|---|---|---|---|
| cold | 1 | 78.190 | 78.190 | — |
| warm | 35 | 116.860 | 287.253 | — |

- Δ retrieve_ms p50 (cold − warm) = —
- Δ e2e_ms p50 (cold − warm) = -38.670

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

