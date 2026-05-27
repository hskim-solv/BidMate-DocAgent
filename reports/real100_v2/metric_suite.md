# v0 Metric Suite Report

This is an aggregate-only metric-suite coverage report, not a performance claim.

| Family | Status | Metrics | Notes |
|---|---|---|---|
| `retrieval_recall` | `present` | `chunk_recall_at_5`, `chunk_recall_at_10`, `chunk_mrr`, `chunk_ndcg` | N/A |
| `grounding` | `present` | `groundedness` | page_region_grounding_not_populated |
| `citation_precision` | `present` | `citation_precision` | N/A |
| `claim_citation_alignment` | `present` | `claim_citation_alignment` | N/A |
| `comparison_coverage` | `present` | `comparison_target_recall`, `comparison_pool_recall` | N/A |
| `abstention_calibration` | `present` | `abstention`, `abstention_outcomes` | confidence_calibration_not_populated |
| `numeric_date_condition_accuracy` | `present` | `numeric_date_condition_accuracy`, `numeric_date_condition_slot_count`, `numeric_date_condition_type_counts`, `question_type_counts` | N/A |
| `human_judge_agreement` | `partial` | N/A | requires_private_label_csv_or_approved_judge_aggregate |

## Readiness

- present: 7
- partial: 1
- missing: 0
- all_present: `false`

Private raw questions, answers, evidence, document IDs, chunk IDs, filenames, paths, and per-case rows are omitted.
