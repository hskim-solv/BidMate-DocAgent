# real100_v2 Context Packing Experiment

This report is aggregate-only. It contains no raw case prompts, generated responses, evidence text, filenames, local paths, document identifiers, chunk identifiers, or per-case rows. Legacy `real100`, v1, 221, and kordoc evidence is not used.

## Decision

- Overall classification: `latency_regression`
- Selected variant: `-`
- Paired delta valid: `False`
- Subset run: `True`
- Latency hard ceiling ms: `4799.0000`
- Cost status: `not_observable_from_committed_aggregate`

## Variants

| Variant | Accuracy | Groundedness | Citation precision | Claim alignment | Token status | p95 ms | Classification |
|---|---:|---:|---:|---:|---|---:|---|
| control_context_default | 0.0000 | 0.6667 | 0.0000 | 0.8333 | not_observable_from_prediction_diagnostics | 46589.6620 | control |
| context_evidence_first | 0.0000 | 0.6667 | 0.0000 | 0.8333 | not_observable_from_prediction_diagnostics | 12946.1880 | latency_regression |

## Notes

- Retrieval behavior, reranker behavior, and answer schema are marked unchanged for every variant.
- Citation regression is a no-go even if answer metrics improve.
- `paired_delta_valid=false` means this artifact is screening evidence only and must not be used as a headline private eval improvement claim.
