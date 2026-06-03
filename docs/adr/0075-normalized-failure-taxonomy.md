# 0075: Normalized failure taxonomy for private baseline reporting

- **Status**: accepted
- **Date**: 2026-05-24
- **Deciders**: hskim
- **Related**: [ADR 0001](./0001-preserve-naive-baseline.md), [ADR 0005](./0005-eval-split-public-synthetic-private-local.md), [ADR 0054](./0054-conditional-on-answer-scorer-semantics.md), [ADR 0059](./0059-failure-mode-classifier-as-measurement-surface.md), [ADR 0062](./0062-failure-rate-regression-contract.md), [ADR 0069](./0069-retrieval-aggregate-and-citation-coverage-surface.md)
- **Supersedes**: ADR 0059 category names, while preserving the `failure_category_counts` measurement surface and first-match verifier-false-negative contract.

## Context

ADR 0059 introduced a deterministic failure classifier so private real-eval
failures could be reported as aggregate counts under the ADR 0005 boundary.
That v1 taxonomy left a large residual `unknown` bucket in the private
baseline reports (roughly 31-35 cases depending on the snapshot).

The large residual bucket made the top failure table less actionable. Many
`unknown` cases were not unknowable; they were abstention boundary cases,
citation/page metadata gaps, answer synthesis failures, label issues, or
parse/metadata surface problems that the existing `case_result` metrics
already exposed.

## Decision

Replace the ADR 0059 primary category names with a normalized taxonomy:

1. `retrieval_miss`
2. `citation_or_page_metadata_issue`
3. `verifier_false_negative`
4. `verifier_false_positive`
5. `answer_synthesis_issue`
6. `abstention_failure`
7. `evaluation_label_issue`
8. `parse_or_metadata_issue`
9. `unknown`

`unknown` remains only as a residual fallback. Classification is deterministic
and uses only fields already present in `case_result`: booleans, numeric
metrics, closed enum-like reasons, and ID-set cardinality/coverage. It does not
copy raw query text, answer text, evidence text, doc IDs, or chunk IDs into
committed artifacts.

The first-match contract is preserved: `verifier_false_negative` must equal
`abstention_outcomes.incorrect_answer`. This keeps the Phase 5 finding #1
signal stable while decomposing the old residual bucket.

## Consequences

- `case_results[*].failure_category` and `failure_category_counts` keep the
  same interface names, but the allowed category set changes.
- `scripts/render_failure_distribution.py`,
  `scripts/render_failure_slices.py`, `scripts/run_real_eval_delta.py`, and
  variance/baseline reporting helpers must whitelist the new category set.
- Runtime RAG behavior is unchanged. `rag_core.py`, retrieval, verifier,
  answer, ingestion, API, and preset defaults are not part of this decision.
- Private raw content remains local-only. Committed reports contain aggregate
  counts and closed buckets only.
- Current private-eval evidence for new tasks, PRs, claims, and agent handoffs
  must use the `real100_v2` aggregate-only surface. The v1 taxonomy/baseline
  context above, plus legacy real100/v1/221/kordoc aggregate wording, is
  archive-only unless the maintainer explicitly re-enables a named private-eval
  surface through a later ADR and Surface Map update that list allowed paths,
  commands, and the aggregate-only boundary.

## Verification

<!-- verifies-key: eval/scorers/failure_classifier.py:FailureCategory -->
<!-- verifies-key: eval/scorers/failure_classifier.py:def classify_failure -->
<!-- verifies-key: scripts/render_failure_distribution.py:SAFE_CATEGORIES -->
<!-- verifies-key: scripts/run_real_eval_delta.py:SAFE_FAILURE_CATEGORY_KEYS -->
<!-- verifies-key: tests/test_failure_classifier.py:class NormalizedCategoryTest -->
