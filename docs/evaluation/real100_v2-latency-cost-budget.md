# real100_v2 Latency And Cost Budget

> Invalidated for optimization claims by `T-2026-0047`: the source baseline was
> produced from a hashing-backed `real100_v2` index with 0.0 chunk page metadata
> coverage. Rebuild and rerender from a MiniLM page-aware v2 index before using
> this as a latency/cost budget.

Issue: [#1626](https://github.com/hskim-solv/BidMate-DocAgent/issues/1626)

Task: `T-2026-0030`

Status: aggregate-only budget envelope; no runtime behavior change and no performance-improvement claim.

## Boundary

This report uses only committed `real100_v2` aggregate latency fields. It does not include raw questions, answers, evidence, filenames, local paths, document IDs, chunk IDs, or per-case rows. Legacy `real100`/v1/221/kordoc evidence is not used.

## Source Provenance

| Field | Value |
|---|---|
| Input artifact | `reports/real100_v2/baseline.aggregate.json` |
| Input redacted | `False` |
| Input SHA-256 prefix | `a73a99987064` |

## Baseline Population

| Field | Value |
|---|---|
| Predictions | 300 |
| Pipeline | `agentic_full` |
| Primary run | `full` |
| Prompt profile | `structured_grounded_claims` |

## Overall Latency Envelope

| Metric | Value |
|---|---:|
| Mean ms | 2206.346667 |
| p50 ms | 2216.985 |
| p95 ms | 3199.0625 |
| p99 ms | None |
| Soft ceiling ms | 3999.0 |
| Hard no-go ceiling ms | 4799.0 |

p99 is named but not observed in the committed source aggregate.

## Stage Latency Envelope

| Stage | Mean | p50 | p95 | p99 | Soft ceiling | Hard ceiling |
|---|---:|---:|---:|---:|---:|---:|
| `query_analysis_ms` | 160.83699 | 116.77 | 388.67 | None | 486.0 | 584.0 |
| `context_resolution_ms` | 0.018227 | 0.02 | 0.03 | None | 1.0 | 1.0 |
| `retrieve_ms` | 995.162387 | 1036.72 | 1553.274 | None | 1942.0 | 2330.0 |
| `verify_ms` | 19.963689 | 19.14 | 34.561 | None | 44.0 | 52.0 |
| `answer_generation_ms` | 1.366187 | 1.14 | 3.536 | None | 5.0 | 6.0 |

## Cost Envelope

| Field | Value |
|---|---|
| Status | `not_observable_from_committed_aggregate` |
| Synthesis cost present | `False` |
| Synthesis tokens present | `False` |
| Paid API rule | paid or external reranker/synthesis cost must be reported separately before claim |
| Local CPU rule | local reranker latency must be counted even when direct API cost is zero |

## Guardrail Rules

- Soft regression: variant p95 above soft_ceiling_ms requires explicit reviewer justification
- Hard no-go: variant p95 above hard_ceiling_ms cannot be called a winner
- Quality-only no-go: quality gain without latency and cost evidence is not sufficient
- p99 rule: p99 must be added when the source aggregate exposes it; currently not observed

## Caveats

- Scope: `local private real100_v2 baseline aggregate`
- Warm/cold status: `not_split_in_committed_aggregate`
- Production SLO claim: `False`

## Downstream Use

`T-2026-0032` and later candidate-pool, query rewrite, and context-packing experiments can cite this envelope. A quality-only gain is no-go unless latency stays under the hard ceiling and cost evidence is present or explicitly not applicable.

## Non-Claims

- No runtime retrieval, reranking, verifier, answer, ingestion, chunking, or eval scoring behavior changed.
- No paired delta was produced.
- No performance improvement is claimed.
- No legacy `real100`/v1/221/kordoc evidence is used.
