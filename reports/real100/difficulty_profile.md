# Real100 difficulty profile (aggregate-only, n=221)

This report is aggregate-only. It distinguishes a hard benchmark from an invalid benchmark; raw questions, answers, evidence text, IDs, filenames, paths, and case rows are intentionally excluded.

## Required conclusions

1. Overall status: `hard_benchmark_not_invalid`; too hard overall: `true`.
2. Easy single-doc/single-chunk answerable cases solvable: `true` (n=19, recall@10=26.3%, citation_precision=5.3%).
3. Failure-dominant slices: gold_doc_cardinality=single_doc (199), score_like_question=false (190), similar_clause_distractor_proxy=false (160), date_like_question=false (159), amount_like_question=false (139)
4. Split benchmark recommended: `true` into easy sanity, standard real, and hard stress subsets.
5. Next improvement justified: `page_metadata_recovery`.

## Overall outcomes

| metric | mean | n | missing |
|---|---:|---:|---:|
| `accuracy` | 8.5% | 118 | 103 |
| `recall_at_5` | 6.4% | 118 | 103 |
| `recall_at_10` | 7.7% | 118 | 103 |
| `mrr_at_5` | 10.5% | 118 | 103 |
| `ndcg_at_5` | 6.8% | 118 | 103 |
| `citation_precision` | 5.1% | 118 | 103 |
| `abstention` | 6.8% | 103 | 118 |

## Difficulty axes

| axis | bucket | n | failure_rate | recall@10 | citation_precision |
|---|---|---:|---:|---:|---:|
| `amount_like_question` | `false` | 145 | 95.9% | 6.7% | 6.8% |
| `amount_like_question` | `true` | 76 | 85.5% | 10.0% | 1.4% |
| `answerability` | `answerable` | 118 | 91.5% | 7.7% | 5.1% |
| `answerability` | `unanswerable` | 103 | 93.2% | n/a | n/a |
| `date_like_question` | `false` | 173 | 91.9% | 7.0% | 5.7% |
| `date_like_question` | `true` | 48 | 93.8% | 9.9% | 3.3% |
| `expected_terms_count` | `0` | 103 | 93.2% | n/a | n/a |
| `expected_terms_count` | `1` | 11 | 72.7% | 27.3% | 0.0% |
| `expected_terms_count` | `2_3` | 30 | 93.3% | 12.1% | 8.3% |
| `expected_terms_count` | `4_plus` | 77 | 93.5% | 3.2% | 4.5% |
| `gold_chunk_cardinality` | `multi_chunk` | 99 | 93.9% | 4.1% | 5.1% |
| `gold_chunk_cardinality` | `none` | 103 | 93.2% | n/a | n/a |
| `gold_chunk_cardinality` | `single_chunk` | 19 | 78.9% | 26.3% | 5.3% |
| `gold_chunk_length` | `0_500` | 87 | 89.7% | 7.2% | 5.7% |
| `gold_chunk_length` | `501_1200` | 31 | 96.8% | 9.1% | 3.2% |
| `gold_chunk_length` | `missing` | 103 | 93.2% | n/a | n/a |
| `gold_doc_cardinality` | `multi_doc` | 2 | 100.0% | 2.8% | 50.0% |
| `gold_doc_cardinality` | `single_doc` | 215 | 92.6% | 7.8% | 4.3% |
| `gold_doc_cardinality` | `unknown` | 4 | 75.0% | n/a | n/a |
| `gold_evidence_count` | `0` | 103 | 93.2% | n/a | n/a |
| `gold_evidence_count` | `1` | 19 | 78.9% | 26.3% | 5.3% |
| `gold_evidence_count` | `2_3` | 25 | 96.0% | 7.3% | 2.0% |
| `gold_evidence_count` | `4_plus` | 74 | 93.2% | 3.0% | 6.1% |
| `lexical_overlap` | `high` | 80 | 92.5% | 9.2% | 5.0% |
| `lexical_overlap` | `medium` | 35 | 91.4% | 2.0% | 5.7% |
| `lexical_overlap` | `missing` | 103 | 93.2% | n/a | n/a |
| `lexical_overlap` | `none` | 3 | 66.7% | 33.3% | 0.0% |
| `score_like_question` | `false` | 205 | 92.7% | 8.2% | 5.0% |
| `score_like_question` | `true` | 16 | 87.5% | 1.7% | 5.6% |
| `similar_clause_distractor_proxy` | `false` | 174 | 92.0% | 7.4% | 4.6% |
| `similar_clause_distractor_proxy` | `true` | 47 | 93.6% | 8.2% | 6.0% |
| `table_like_evidence` | `false` | 111 | 93.7% | 18.8% | 0.0% |
| `table_like_evidence` | `true` | 110 | 90.9% | 6.9% | 5.5% |

## Next-improvement signals

| lever | signal_count |
|---|---:|
| `page_metadata_recovery` | 208 |
| `reranker` | 118 |
| `abstention_verifier_tuning` | 96 |
| `multi_chunk_expansion` | 93 |
| `hybrid_sweep` | 21 |

## Privacy boundary

The profiler may compute lexical overlap from private text locally, but only bucket counts and aggregate means are rendered. Hard benchmark does not mean invalid benchmark; invalidity is reserved for missing gold/index references or unobservable metrics dominating the population.
