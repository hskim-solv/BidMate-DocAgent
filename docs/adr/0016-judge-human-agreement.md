# 0016: Judge-Human Agreement as Calibration Gate on Real-Data Eval

- **Status**: proposed
- **Date**: 2026-05-12
- **Deciders**: hskim
- **Related**: [#169](https://github.com/hskim-solv/BidMate-DocAgent/issues/169), [ADR 0006](./0006-llm-judge-on-real-data-only.md)

## Context

[ADR 0006](./0006-llm-judge-on-real-data-only.md) introduced an LLM
judge on the real-data eval surface that reports
`judge.agreement_with_verifier` — i.e. judge ↔ deterministic
verifier agreement (`scripts/llm_judge.py`). External code review
flagged this as a *closed loop*: same RAG, same fixtures, same
judge prompt. The metric does not validate that the judge's verdict
matches a human reviewer's verdict, so a regression that hides in
both the verifier and the judge would not surface as a drop.

The closed-loop risk is concrete on the private-100 surface: a
high `judge.agreement_with_verifier` (≈ 0.95) is consistent with
spot-check disagreements between the verifier and a human
reviewer. The shipped metric flagged neither.

## Decision

Treat **judge ↔ human agreement** as the calibration gate for the
LLM judge. The mechanism:

- Human spot-labels a stratified subset of cases (20–30 out of the
  42-case real-data surface) across `single_doc`, `comparison`,
  `follow_up`, and `abstention` query types. One labeler per pass
  is sufficient for the first iteration (inter-annotator κ is
  deferred).
- [`eval/judge_agreement.py`](../../eval/judge_agreement.py)
  takes a side-by-side CSV (`case_id, judge_status, human_status`)
  and reports **Spearman ρ** and **Cohen's κ** along with the
  per-class confusion matrix. The status vocabulary is the same
  `(supported, partial, insufficient)` triple as ADR 0006's
  `judge_status` field.
- **Threshold: κ ≥ 0.6** ("substantial agreement", Landis & Koch
  1977). κ below threshold means the judge's verdict on that pass
  is not trustworthy as a quality signal; the reviewer either
  re-runs the judge with a refined prompt or falls back to direct
  human review.
- The calibration is a *gate on trusting the judge for that
  run-window*, not a CI step — labels are scarce and the threshold
  call is reviewer judgment, not automation.

The labels themselves live on the **private** side of ADR 0005
(human review of private RFP cases) and are git-ignored. Only the
aggregate κ + ρ are surfaced in the PR / case-study narrative;
the per-case CSV stays in `reports/real100/judge_agreement.local.csv`.

## Consequences

- Closes the closed-loop loophole: a verifier-judge co-regression
  cannot pass undetected once a calibration pass is run.
- Adds human labeling cost (~30 minutes per 30-case pass).
  Mitigated by running calibrations only when the judge prompt,
  judge model, or verifier policy changes.
- Locks `(supported, partial, insufficient)` as the agreement
  axis — same vocabulary as ADR 0006. Other axes (citation
  precision, evidence completeness) are out of scope here.
- Depends on the existing `commit_sha + config_sha256`
  reproducibility fields in
  [`eval/run_eval.py:compute_run_manifest`](../../eval/run_eval.py),
  so a labeled CSV is always tied to a specific judge run. That
  wiring is already in place (#169 deliverable, landed earlier).

## Alternatives considered

- **Keep ADR 0006 as-is.** Accepts the Goodhart risk. Rejected
  because external review specifically flagged the closed loop and
  the private-100 spot-check supports the concern.
- **Replace the LLM judge with a different model.** Higher cost
  and still does not certify against human ground truth.
  Replacing the judge does not eliminate the closed-loop problem;
  it relocates the loop's centre.
- **Multi-labeler inter-annotator κ.** Stronger guarantee, but
  defers the first calibration pass on labeler availability.
  Deferred to a follow-up — can be layered later without changing
  the agreement metric.
