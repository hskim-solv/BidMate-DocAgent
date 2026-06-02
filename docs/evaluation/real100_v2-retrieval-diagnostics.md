# real100_v2 Retrieval Diagnostics

> Paired re-measurement (`T-2026-0029`, issue #1764): the source `real100_v2` index was rebuilt as MiniLM
> page-aware (`real100_v2_checkpoint_minilm_pageaware`). Page-span coverage is now 1.0 (page blocker resolved),
> but doc-level retrieval regressed sharply versus the prior hashing-backed `real100_v2` run. Root-cause
> verification (embedding/index integrity) is tracked as `T-2026-0076`; do not treat this artifact as an
> optimization result.

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
| Input SHA-256 prefix | `5ee09c068105` |

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
| Recall@5 | 0.009191 |
| Recall@10 | 0.009191 |
| Recall@20 | 0.009191 |
| Hit@5 | 0.011029 |
| Hit@10 | 0.011029 |
| All-gold@5 | 0.007353 |
| All-gold@10 | 0.007353 |
| MRR@5 | 0.005637 |
| nDCG@5 | 0.005515 |
| nDCG@10 | 0.005515 |

## Exclusive Retrieval Status

Dominant bucket: `not_observable_limited_depth`

| Bucket | Count |
|---|---:|
| `unanswerable_no_gold` | 28 |
| `no_gold_evidence` | 0 |
| `all_gold_top5` | 2 |
| `all_gold_top10_not_top5` | 0 |
| `all_gold_observed_after_top10` | 0 |
| `partial_candidate_pool` | 1 |
| `not_in_candidate_pool` | 0 |
| `not_observable_limited_depth` | 269 |

## Failure Buckets

| Bucket | Count |
|---|---:|
| `answer_generation_or_abstention` | 0 |
| `boundary_or_window_candidate` | 0 |
| `duplicate_or_near_duplicate_candidate` | 192 |
| `evaluation_label_gap` | 0 |
| `metadata_filter_candidate` | 5 |
| `multi_evidence_failure` | 40 |
| `not_in_candidate_pool` | 0 |
| `page_metadata_blocked` | 0 |
| `ranked_too_low_after_top5` | 1 |
| `verifier_false_negative` | 19 |
| `verifier_false_positive` | 0 |

## Candidate Pool And Evidence Shape

| Signal | Count / Rate |
|---|---:|
| Any gold observed | 3 |
| All gold observed | 2 |
| No gold observed | 269 |
| Partial gold observed | 1 |
| Retrieval depth < 10 | 272 |
| Any-gold observed rate | 0.011029 |
| All-gold observed rate | 0.007353 |
| No-gold observed rate | 0.988971 |
| Multi-chunk same-doc | 27 |
| Multi-chunk multi-doc | 13 |
| Multi-chunk unknown-doc | 0 |

## Duplicate And Metadata Signals

| Signal | Count |
|---|---:|
| Duplicate chunk-id cases | 0 |
| Repeated document in top 5 | 118 |
| Repeated document in top 10 | 74 |
| Metadata candidate cases | 17 |
| Metadata candidate doc misses | 4 |
| Metadata ambiguous cases | 1 |
| Reduced/relaxed filter stage cases | 299 |

## Query Type Slices

| Query type | Cases | Recall@5 | Recall@10 | Hit@5 | MRR@5 | Dominant status |
|---|---:|---:|---:|---:|---:|---|
| `single_doc` | 259 | 0.007722 | 0.007722 | 0.007722 | 0.002059 | `not_observable_limited_depth` |
| `comparison` | 13 | 0.038462 | 0.038462 | 0.076923 | 0.076923 | `not_observable_limited_depth` |
| `abstention` | 28 | None | None | 0.0 | None | `unanswerable_no_gold` |
| `unknown` | 0 | None | None | 0.0 | None | `none` |

## Page Metadata Blocker

| Field | Value |
|---|---|
| Status | `available` |
| Chunks total | 24613 |
| Chunks with page span | 24613 |
| Page-span coverage | 1.0 |
| Coverage reason | `ok` |

Page-span coverage is now 1.0; the prior v2 page-metadata blocker is resolved. Claim-bearing page/citation and section-window work (T-2026-0031) is unblocked for follow-up. No old evidence is substituted.

## Next Task Decision

- Preferred next task: `T-2026-0076`
- Reason: `candidate_pool_collapse_gold_rarely_observed_retrieval_integrity_suspect`
- Blocked task: `None`
- Blocker: `page_metadata_available`
- Signal: `retrieval_integrity_suspect`

## Non-Claims

- No retrieval, reranking, verifier, answer, ingestion, chunking, or eval scoring behavior changed.
- No paired delta was produced.
- No performance improvement is claimed.
- No legacy `real100`/v1/221/kordoc evidence is used.
