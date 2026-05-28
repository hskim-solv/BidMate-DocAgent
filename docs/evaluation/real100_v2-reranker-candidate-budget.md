# real100_v2 Reranker Candidate-Budget Sweep

This report is aggregate-only. It contains no raw questions, answers, evidence text, filenames, local paths, document identifiers, chunk identifiers, or per-case rows. Legacy `real100`, v1, 221, and kordoc evidence is not used.

## Decision

- Overall classification: `latency_regression`
- Selected variant: `-`
- Paired delta valid: `False`
- Subset run: `True`
- Latency hard ceiling ms: `4799.0000`
- Cost status: `not_observable_from_committed_aggregate`

## Control

| Variant | Recall@5 | Recall@10 | MRR@5 | nDCG@5 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| control_no_cross_encoder_top20 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 13700.6600 | 16842.9560 |

## Candidate Variants

| Variant | Pool | top_n | preR@N | postR@N | dMRR | dNDCG@10 | fallback | p95 ms | Classification |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| reranker_budget_pool30_topn10_top20 | 30.0000 | 10.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 149369.5710 | latency_regression |

## Notes

- Candidate-pool recall is measured before cross-encoder reranking; reranker precision is measured as MRR/nDCG movement after reranking.
- `winner` requires material retrieval or reranker-precision gain with no ranking, citation, latency, or fallback regression.
- `paired_delta_valid=false` means this artifact is screening evidence only and must not be used as a headline private eval improvement claim.
