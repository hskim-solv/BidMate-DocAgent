# v0 Metric Suite Inventory

This document closes the v0-a inventory milestone from the
[Agent-Gated RFP Evaluation Loop](./agent-gated-rfp-eval-loop.md). It classifies
which private real-eval aggregate surfaces already expose each metric family and
which gaps remain before a v0 metric-suite report can claim coverage.

This is an aggregate-only inventory. It is not a performance claim, does not run
private real-eval, and does not compare deltas.

## Status Vocabulary

| Status | Meaning |
|---|---|
| Present | A committed aggregate-only private real-eval artifact already exposes the metric family with enough structure to include it in a v0 report shell. |
| Partial | Related aggregate fields exist, but the current surface is too narrow, null, non-canonical, or missing a subdimension required by the metric family. |
| Missing | No dedicated aggregate-only metric exists for the family. |

## Inventory

| Metric family | Status | Current aggregate evidence | Gap / smallest next step |
|---|---|---|---|
| Retrieval recall | Present | `reports/real100_v2/baseline.aggregate.json` exposes `chunk_recall_at_5`, `chunk_recall_at_10`, `chunk_recall_at_20`, `chunk_mrr`, and `chunk_ndcg_at_*` under aggregate slices. `reports/real100/embedding_ablation_retrieval.aggregate.json` is a retrieval-only aggregate surface. | v0-c should choose the canonical primary source and render retrieval metrics with dataset/config/index provenance. |
| Grounding | Partial | `reports/real100_v2/baseline.aggregate.json` and `reports/real100/baseline.aggregate.json` expose answer-level `groundedness` with CI blocks. `eval/scorers/citation.py` also defines page/region `citation_grounding`, but the committed baseline aggregate keeps that field null. | v0-c should report answer-level groundedness as present, keep it separate from trajectory rationality, and leave page/region grounding marked partial until gold page/region metadata is populated. |
| Citation precision | Present | `reports/real100_v2/baseline.aggregate.json` and `reports/real100/baseline.aggregate.json` expose `citation_precision`; `reports/private_real_eval_summary.redacted.json` also carries legacy citation aggregate fields. | v0-c should standardize on `citation_precision` naming and avoid mixing legacy `citation_accuracy` with the metric-suite label unless semantics are restated. |
| Claim-citation alignment | Present | `reports/real100_v2/baseline.aggregate.json` and `reports/real100/baseline.aggregate.json` expose `claim_citation_alignment`; [Citation Grounding Evaluation](../eval/citation-grounding-eval.md) defines the report field. | v0-c should include claim-level error counts when available, but the core family is already measurable. |
| Comparison coverage | Partial | Top-level CI blocks include `comparison_target_recall` and `comparison_pool_recall`, and `by_query_type` has a `comparison` slice. | The comparison slice does not yet expose per-target evidence/claim coverage in the report shell. Add a comparison-specific aggregate that reports target, evidence, and claim coverage with enough cases to interpret gaps. |
| Abstention calibration | Partial | Aggregate files expose `abstention` and `abstention_outcomes`; some slices carry an `abstention_calibration` key. | `abstention_calibration` is not yet a populated canonical metric. Add an explicit calibration aggregate for answerable vs unanswerable cases, including correct refusal and incorrect-answer buckets. |
| Numeric/date/condition accuracy | Partial | `reports/real100_v2/question_distribution.aggregate.json` classifies amount/date/score/question types, and `reports/real100/difficulty_profile.aggregate.json` exposes date-like and amount-like diagnostic slices. | There is no dedicated slot exactness metric for amount, date, eligibility, submission condition, or score fields. Add a field-level scorer before treating this family as present. |
| Human/judge agreement | Partial | `eval/judges/judge_agreement.py` defines judge-human agreement aggregation, and ADR 0016 defines the private-label boundary. `reports/self_review_agreement/*.json` are committed agreement examples, but they are self-review governance artifacts rather than RFP QA metric-suite outputs. | Add a private real-eval agreement aggregate for an approved judge or human reviewer signal; keep per-case CSV labels local-only. |

## v0 Readiness Verdict

v0-a is complete because every metric family has been classified against current
aggregate artifacts. The broader v0 exit condition is not complete yet:
grounding page/region coverage, comparison coverage, abstention calibration,
numeric/date/condition accuracy, and human/judge agreement still need follow-up
metric work before the suite can be treated as fully adopted.

## Privacy And Claim Boundary

- Use only aggregate files committed under allowlisted report paths.
- Do not commit raw private questions, answers, evidence text, document IDs,
  chunk IDs, filenames, exact local paths, parsed Markdown, per-case rows, or raw
  eval summaries.
- Do not describe this inventory as an improvement, regression fix, or quality
  result. It is a coverage map for the next metric-suite PRs.
- Any future performance claim still requires private real-eval aggregate,
  dataset/config/index provenance, and wording scoped to the measured surface.

## Recommended Follow-Ups

| Milestone | Follow-up |
|---|---|
| v0-b offline/online run manifest | Reuse the metric family list here and add run-environment provenance fields for each aggregate source. |
| v0-c metric suite report | Render one report shell that includes all present families and explicitly marks partial or missing families. |
| v1 failure sensitivity | Use this inventory to pick at least three failure modes with observable metric movement. |
| v2 agreement calibration | Promote human/judge agreement from partial to present with private-label aggregate evidence. |
