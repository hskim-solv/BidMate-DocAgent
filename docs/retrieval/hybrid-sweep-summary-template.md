# Private Hybrid Retrieval Sweep Summary Template

This template is for privacy-safe aggregate reporting only. Do not include raw
questions, generated answers, evidence text, `doc_id`, `chunk_id`, filenames,
local paths, or document identifiers.

## Run Metadata

- Aggregate artifact: `reports/retrieval/hybrid_sweep_<timestamp>/aggregate.json` (local only, not for commit)
- Config fingerprint: `<sha256>`
- Index fingerprint: `<sha256>`
- Variant count: `28`
- Case count: `<n>`
- Top K: `20`

## Comparison

Baseline: `full_dense_top20`

Candidate family: `hybrid_bm25_dense_v1`

| Variant | RRF k | Dense pool | BM25 pool | Recall@5 | Recall@10 | MRR@5 | nDCG@5 | Retrieval miss rate | Citation/chunk guardrail | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| `<variant>` | `<k>` | `<n>` | `<n>` | `<aggregate>` | `<aggregate>` | `<aggregate>` | `<aggregate>` | `<aggregate>` | `<aggregate summary>` | `<aggregate>` | `<aggregate>` |

## Notes

- This is private-local aggregate measurement, not a public performance claim.
- Verifier, prompt, chunking, reranker, and answer generation must match the
  `full_dense` control path except for retrieval fusion parameters.
- Weighted fusion is intentionally out of scope unless a separate PR adds it
  with its own measurement contract.
