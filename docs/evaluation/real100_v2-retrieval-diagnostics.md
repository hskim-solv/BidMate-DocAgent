# real100_v2 Retrieval Diagnostics

> Invalidated for optimization claims by `T-2026-0047`: the source `real100_v2`
> index is hashing-backed and has 0.0 chunk page metadata coverage. Use this
> artifact only as historical context until a MiniLM page-aware v2 index is
> rebuilt and remeasured.

Issue: [#1622](https://github.com/hskim-solv/BidMate-DocAgent/issues/1622)

Task: `T-2026-0029`

Status: aggregate-only diagnostic report; no runtime behavior change and no performance-improvement claim.

## Boundary

This report uses only `real100_v2` local private eval diagnostics and emits aggregate counts. It does not include raw questions, answers, evidence text, filenames, local paths, document IDs, chunk IDs, sections, or per-case rows. Legacy `real100`/v1/221/kordoc evidence is not used.

## Source Provenance

| Field | Value |
|---|---|
| Input artifact | `external_private/real100_v2_eval_summary` |
| Input redacted | `True` |
| Input SHA-256 prefix | `355da92b368c` |

## Population

| Metric | Count |
|---|---:|
| Predictions | 300 |
| Answerable | 272 |
| Unanswerable | 28 |
| Single-chunk gold | 232 |
| Multi-chunk gold | 40 |
| No gold evidence | 28 |

## Retrieval Metrics

| Metric | Value |
|---|---:|
| Coverage cases | 272 |
| Recall@5 | 0.369485 |
| Recall@10 | 0.433824 |
| Recall@20 | 0.433824 |
| Hit@5 | 0.375 |
| Hit@10 | 0.441176 |
| All-gold@5 | 0.363971 |
| All-gold@10 | 0.426471 |
| MRR@5 | 0.25674 |
| nDCG@5 | 0.282578 |
| nDCG@10 | 0.304372 |

## Exclusive Retrieval Status

Dominant bucket: `not_observable_limited_depth`

| Bucket | Count |
|---|---:|
| `unanswerable_no_gold` | 28 |
| `no_gold_evidence` | 0 |
| `all_gold_top5` | 99 |
| `all_gold_top10_not_top5` | 17 |
| `all_gold_observed_after_top10` | 0 |
| `partial_candidate_pool` | 4 |
| `not_in_candidate_pool` | 0 |
| `not_observable_limited_depth` | 152 |

## Failure Buckets

| Bucket | Count |
|---|---:|
| `answer_generation_or_abstention` | 3 |
| `boundary_or_window_candidate` | 3 |
| `duplicate_or_near_duplicate_candidate` | 199 |
| `evaluation_label_gap` | 0 |
| `metadata_filter_candidate` | 43 |
| `multi_evidence_failure` | 40 |
| `not_in_candidate_pool` | 0 |
| `page_metadata_blocked` | 300 |
| `ranked_too_low_after_top5` | 21 |
| `verifier_false_negative` | 17 |
| `verifier_false_positive` | 2 |

## Candidate Pool And Evidence Shape

| Signal | Count / Rate |
|---|---:|
| Any gold observed | 120 |
| All gold observed | 116 |
| No gold observed | 152 |
| Partial gold observed | 4 |
| Retrieval depth < 10 | 272 |
| Any-gold observed rate | 0.441176 |
| All-gold observed rate | 0.426471 |
| No-gold observed rate | 0.558824 |
| Multi-chunk same-doc | 27 |
| Multi-chunk multi-doc | 13 |
| Multi-chunk unknown-doc | 0 |

## Duplicate And Metadata Signals

| Signal | Count |
|---|---:|
| Duplicate chunk-id cases | 0 |
| Repeated document in top 5 | 146 |
| Repeated document in top 10 | 53 |
| Metadata candidate cases | 77 |
| Metadata candidate doc misses | 42 |
| Metadata ambiguous cases | 1 |
| Reduced/relaxed filter stage cases | 297 |

## Query Type Slices

| Query type | Cases | Recall@5 | Recall@10 | Hit@5 | MRR@5 | Dominant status |
|---|---:|---:|---:|---:|---:|---|
| `single_doc` | 259 | 0.388031 | 0.453668 | 0.393822 | 0.269627 | `not_observable_limited_depth` |
| `comparison` | 13 | 0.0 | 0.038462 | 0.0 | 0.0 | `not_observable_limited_depth` |
| `abstention` | 28 | None | None | 0.0 | None | `unanswerable_no_gold` |
| `unknown` | 0 | None | None | 0.0 | None | `none` |

## Page Metadata Blocker

| Field | Value |
|---|---|
| Status | `blocked_for_page_and_window_claims` |
| Chunks total | 21800 |
| Chunks with page span | 0 |
| Page-span coverage | 0.0 |
| Coverage reason | `index_lacks_page_region_metadata` |

Claim-bearing page/citation or section-window work remains blocked while the v2 page metadata ready rate is 0.0. This report preserves that blocker instead of substituting old evidence.

## Next Task Decision

- Preferred next task: `T-2026-0032`
- Reason: `ranked_too_low_signal_points_to_candidate_budget_or_reranker_measurement`
- Blocked task: `T-2026-0031`
- Blocker: `claim_bearing_page_or_window_work_blocked`

## Non-Claims

- No retrieval, reranking, verifier, answer, ingestion, chunking, or eval scoring behavior changed.
- No paired delta was produced.
- No performance improvement is claimed.
- No legacy `real100`/v1/221/kordoc evidence is used.
