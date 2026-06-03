# Multi-Chunk Retrieval Strategy Decision

This report is aggregate-only. It uses counts from `reports/real100/multi_chunk_evidence_failures.aggregate.json` and does not include raw questions, answers, document IDs, chunk IDs, paths, sections, or source text.

> **Archive-only note (2026-06-03)**: the source aggregate is a legacy `real100` / 221-prediction artifact. It is historical context, not current claim-bearing private eval evidence. New task, PR, claim, and handoff decisions must use the `real100_v2` aggregate-only surface in [Surface Map](./surface-map.md), or regenerate a matching `real100_v2` multi-chunk aggregate before reusing this strategy.

## Source Provenance

| Field | Value |
|---|---|
| Input artifact | `reports/real100/multi_chunk_evidence_failures.aggregate.json` |
| Source basename | `eval_summary.json` |
| Source SHA-256 prefix | `714c08f9996d` |

Freshness boundary: this decision applies only to the aggregate above. If a newer private index or eval surface exists, render the matching multi-chunk aggregate before choosing a retrieval change.

## Recommendation

- Recommended next strategy: `defer_until_page_metadata_recovery`
- Run order: `after_page_metadata_recovery`
- Decision reasons: `evidence_split_unknown_dominant`

The next retrieval strategy should run after page metadata recovery. The current aggregate cannot distinguish same-document multi-chunk failures from multi-document failures because the document split is unknown for the full multi-chunk population.

## Aggregate Counts

| Metric | Count |
|---|---:|
| Predictions | 221 |
| Multi-chunk gold cases | 99 |
| Top-10 evidence failures | 97 |
| Top-10 evidence failure rate | 0.979798 |

## Retrieval Outcomes

| k | all | partial | none | not observable |
|---:|---:|---:|---:|---:|
| 5 | 2 | 35 | 57 | 5 |
| 10 | 2 | 0 | 14 | 83 |
| 20 | 2 | 0 | 14 | 83 |

## Evidence Split

| Bucket | Count | Ratio |
|---|---:|---:|
| `same_doc` | 0 | 0.0 |
| `multi_doc` | 0 | 0.0 |
| `unknown` | 99 | 1.0 |

## Strategy Assessment

| Strategy | Aggregate verdict | Key count |
|---|---|---:|
| `candidate_pool_expansion` | `not_supported` | 0 |
| `same_doc_neighbor_expansion` | `not_assessable_without_doc_split` | 0 |
| `section_expansion` | `not_assessable_without_same_doc_split` | 0 |
| `query_decomposition` | `not_assessable_without_doc_split` | 0 |
| `reranker` | `insufficient_basis_without_gold_in_candidate_pool` | 0 |

## Structured-Data Overlap

| Signal | Count |
|---|---:|
| table-heavy top-10 failures | 0 |
| structured metadata-field top-10 failures | 0 |
| source format `other` top-10 failures | 97 |

## Boundary

- No retrieval, verifier, prompt, chunking, reranker, answer generation, or runtime behavior changes are implied by this report.
- The recommendation is based on aggregate counts only.
- Re-run this report after page metadata recovery before choosing a concrete retrieval change.
