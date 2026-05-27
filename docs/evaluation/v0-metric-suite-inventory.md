# v0 Metric Suite Inventory

This document closes the v0-a inventory milestone from the
[Agent-Gated RFP Evaluation Loop](./agent-gated-rfp-eval-loop.md). It classifies
which private real-eval aggregate surfaces already expose each metric family and
which gaps remain before a v0 metric-suite report can claim coverage.

This is an aggregate-only inventory. It is not a performance claim, does not run
private real-eval, and does not compare deltas.

Issue #1544 adds the first v0 report renderer:
`scripts/render_v0_metric_suite_report.py`. It consumes aggregate-only private
real-eval artifacts plus an optional local judge/human agreement CSV, and emits
a report surface without raw private payloads.

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
| Grounding | Present | `reports/real100_v2/baseline.aggregate.json` and `reports/real100/baseline.aggregate.json` expose answer-level `groundedness` with CI blocks. The v0 report renderer treats answer-level grounding as the adopted family metric and keeps page/region grounding as a named note when not populated. | Populate page/region grounding later when gold page/region metadata is available; do not block the v0 answer-level grounding family on that optional subdimension. |
| Citation precision | Present | `reports/real100_v2/baseline.aggregate.json` and `reports/real100/baseline.aggregate.json` expose `citation_precision`; `reports/private_real_eval_summary.redacted.json` also carries legacy citation aggregate fields. | v0-c should standardize on `citation_precision` naming and avoid mixing legacy `citation_accuracy` with the metric-suite label unless semantics are restated. |
| Claim-citation alignment | Present | `reports/real100_v2/baseline.aggregate.json` and `reports/real100/baseline.aggregate.json` expose `claim_citation_alignment`; [Citation Grounding Evaluation](../eval/citation-grounding-eval.md) defines the report field. | v0-c should include claim-level error counts when available, but the core family is already measurable. |
| Comparison coverage | Present | Top-level CI blocks include `comparison_target_recall` and `comparison_pool_recall`, and issue #1544 exposes comparison recall/full-coverage scalars through the aggregate extractor and v0 report renderer. | Later work can add per-target claim coverage, but target/pool comparison coverage is now a reportable v0 family. |
| Abstention calibration | Present | Aggregate files expose `abstention` and `abstention_outcomes`; the v0 report renderer treats outcome buckets as the canonical answerable/unanswerable refusal metric and surfaces `abstention_calibration` when confidence scores are available. | Confidence ECE/Brier remains optional until answer dicts consistently emit confidence; outcome buckets remain the v0 family metric. |
| Numeric/date/condition accuracy | Partial | Issue #1544 adds `eval/scorers/slot_metrics.py`, wires `numeric_date_condition_accuracy` into `eval/run_eval.py`, and allowlists the aggregate in `scripts/run_real_eval_delta.py`. Existing committed baselines predate the scorer. | Regenerate the private real-eval aggregate to populate `numeric_date_condition_accuracy`, slot counts, and type counters before marking this family present in committed artifacts. |
| Human/judge agreement | Partial | `eval/judges/judge_agreement.py` defines judge-human agreement aggregation, ADR 0016 defines the private-label boundary, and the v0 report renderer accepts a local `--judge-agreement-csv` input that emits aggregate-only κ/ρ/confusion output. | Run the private label CSV for an approved judge or human reviewer signal; keep per-case CSV labels local-only. |

## v0 Readiness Verdict

v0-a is complete because every metric family has been classified against current
aggregate artifacts. Issue #1544 implements the v0-c report shell and resolves
the comparison and abstention report gaps. The broader v0 exit condition is not
complete until a private real-eval regeneration populates
`numeric_date_condition_accuracy` and a private judge/human agreement pass
supplies aggregate κ/ρ evidence.

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
| v0-b offline/online run manifest | Reuse the metric family list here and add [run-environment provenance](./offline-online-run-manifest.md) fields for each aggregate source. |
| v0-c metric suite report | Use `scripts/render_v0_metric_suite_report.py` to render one report shell that includes all present families and explicitly marks data-dependent partial families. |
| v1 failure sensitivity | Use this inventory to pick at least three failure modes with observable metric movement. |
| v2 agreement calibration | Promote human/judge agreement from partial to present with private-label aggregate evidence. |
