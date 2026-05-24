# Naive RAG Benchmark v1 Results

## TL;DR

- Run `naive-rag-benchmark-v1-20260524T083455Z` is the first runnable Naive RAG benchmark v1 result built from the frozen corpus chunk JSONL.
- The benchmark exposes real naive-baseline failures: failed abstention is 15/15 unanswerable questions, citation chunk accuracy is 0.4500, and Recall@5 is 0.8625.
- This benchmark is useful for failure discovery and next-experiment selection, but it is not sufficient for production performance claims.

## Run Metadata

| field | value |
|---|---|
| `run_id` | `naive-rag-benchmark-v1-20260524T083455Z` |
| benchmark config | `configs/eval/benchmark_naive_rag_v1.yaml` |
| corpus chunks | `data/eval/benchmark/corpus_chunks_v1.jsonl` |
| index path | `data/eval/benchmark/index_v1` |
| artifacts | `experiments/runs/naive-rag-benchmark-v1-20260524T083455Z/` |
| benchmark type | `naive_rag_benchmark` |
| benchmark version | `v1` |
| `not_ci_smoke` | `true` |

## Dataset Counts

| field | value |
|---|---:|
| corpus size | 6 docs |
| chunk count | 72 |
| question count | 55 |
| answerable count | 40 |
| unanswerable count | 15 |
| `top_k` | 10 |
| `chunk_count / top_k` | 7.2 |
| gold evidence count | 47 |
| explicit gold evidence items | 47 |
| unique gold chunks | 35 |
| distractor chunks | 37 |

`distractor chunks` here means corpus chunks not referenced by explicit gold evidence. The corpus does not yet carry a separate human-labeled distractor-chunk field.

## Retrieval Metrics

These metrics are computed from explicit `gold_evidence_v1.jsonl` chunk ids, not from `expected_terms`.

| metric | mean | n | missing |
|---|---:|---:|---:|
| `recall_at_5` | 0.8625 | 40 | 15 |
| `recall_at_10` | 0.9625 | 40 | 15 |
| `mrr_at_5` | 0.6854 | 40 | 15 |
| `ndcg_at_5` | 0.7104 | 40 | 15 |

## Citation/Page Metrics

| metric | mean | n | missing |
|---|---:|---:|---:|
| `citation_chunk_accuracy` | 0.4500 | 40 | 15 |
| `citation_page_coverage` | 0.7750 | 40 | 15 |
| `citation_page_precision` | 0.5000 | 40 | 15 |
| `missing_page_number_rate` | 0.0000 | 40 | 15 |
| `page_metadata_coverage` | 1.0000 | 72 | 0 |

## Rule-Based Answer Metrics

These are rule-based/provisional checks. They are not judge-based faithfulness or answer relevancy metrics.

| metric | mean | n | missing |
|---|---:|---:|---:|
| `rule_based_groundedness` | 1.0000 | 40 | 15 |
| `term_coverage_accuracy` | 0.7254 | 40 | 15 |
| `failed_abstention_rate` | 1.0000 | 15 | 40 |
| `unsafe_answer_rate` | 0.4182 | 55 | 0 |
| `rule_based_hallucination_rate` | 0.2000 | 40 | 15 |

## Failed Abstention / Unsafe Answers

| item | value |
|---|---:|
| unanswerable questions | 15 |
| failed abstentions | 15 |
| failed abstention rate | 1.0000 |
| unsafe answer rate | 0.4182 |
| rule-based hallucination rate on answerable questions | 0.2000 |

All unanswerable questions received supported answers instead of `insufficient`. Treat this as the clearest benchmark failure in this run.

## Latency Metrics

| metric | mean | p50 | p95 | n |
|---|---:|---:|---:|---:|
| `warm_query_latency_ms` | 16.30 | 15.75 | 32.19 | 55 |
| `retrieval_latency_ms` | 4.30 | 2.05 | 11.51 | 55 |
| `generation_latency_ms` | null | null | null | 0 |

## Latency Scope Warning

Latency excludes index loading, ingestion, parsing, chunking, and index build costs. External generation latency is not measured, so these numbers are not end-to-end RAG latency.

The observed index load was 1.15 ms, but it is explicitly excluded from the benchmark latency headline.

## Failure Summary

| failure type | count |
|---|---:|
| `answer_failure.failed_to_abstain` | 15 |
| `citation_failure.citation_does_not_support_claim` | 5 |
| `retrieval_failure.gold_evidence_ranked_too_low` | 5 |
| `retrieval_failure.gold_evidence_not_in_top_k` | 1 |
| `retrieval_failure.multi_chunk_evidence_missing` | 1 |

## Validity Warnings

- The dataset is synthetic-public and still small.
- Answer metrics are rule-based/provisional; do not read them as semantic faithfulness or answer relevancy.
- Failed abstention is a first-order failure, not a retrieval performance improvement opportunity by itself.
- Retrieval metrics are not saturated, but the corpus is still too small for production or real-world performance claims.
- Latency excludes setup costs and external generation.

## Known Limitations

- The corpus is cleaner than real procurement PDFs/HWP documents.
- The benchmark uses deterministic hashing embeddings and dense retrieval only.
- The answer scorer uses lexical/citation rules rather than a semantic judge.
- `distractor_chunk_count` is inferred from non-gold chunks, not independently labeled distractor chunks.
- The run does not measure ingestion, parsing, chunking, index build, index load, or external generation latency.

## Performance-Claim Suitability

This benchmark is not sufficient for performance claims and is not enough to choose a production optimization strategy. It is sufficient to identify the next failure-focused experiments for the naive baseline.

## Next Experiment Candidates

1. Add failed-abstention / unsafe-answer control for unanswerable questions, because 15/15 unanswerable questions failed to abstain.
2. Harden citation selection or citation verification, because `citation_chunk_accuracy` is 0.4500 and 5 primary failures are unsupported citations.
3. Add harder retrieval diagnostics for ranked-too-low cases, because 5 cases had gold evidence in top 10 but not top 5.
4. Expand benchmark v1 with more questions and independently labeled distractor chunks before using it to compare optimization approaches.
5. Add a later optional semantic-judge or RAGAS adapter as a cross-check after the rule-based metrics stop being the only answer-quality surface.
