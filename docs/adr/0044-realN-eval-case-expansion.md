# ADR 0044 — real100 Eval Case Expansion: In-Place n-Increase Policy

| Field       | Value                                     |
|-------------|-------------------------------------------|
| **Status**  | Accepted                                  |
| **Date**    | 2026-05-14                                |
| **Issue**   | #732                                      |
| **Authors** | hskim-solv                                |
| **Tags**    | eval, real-data, dataset-cardinality      |

## Context

The real100 private eval surface (`eval/real_config.local.yaml`,
`reports/real100/`) indexes 100 private RFP documents but evaluates
only **n = 21 cases**. At n = 21 the statistical signal is weak:

- Pool-recall 100% confidence interval is ±21 pp (Wilson 95%).
- Single-case accuracy flip swings the headline by +4.8 pp.
- Silence threshold `max(5e-4, 0.5 / n_min)` (ADR 0030) resolves
  to 0.024 — far larger than intended convergence signal.

All 100 documents are already ingested into `data/index/real100/`;
the gap is cases, not documents. Expanding n using the existing corpus
is low-risk and high-signal.

## Decision

**Expand the case set in-place** (same `reports/real100/` series,
same `eval/real_config.local.yaml` path) rather than starting a new
parallel eval series.

Rationale:

1. **Same corpus, same index.** The 100-document corpus and index are
   unchanged. Cardinality refers to _cases_ (queries), not documents.
   Adding cases does not invalidate historical retrieval measurements —
   it improves their statistical power.

2. **`num_predictions` tracks n.** Every `eval_summary.json` snapshot
   already records `num_predictions`, which is the authoritative n for
   any baseline comparison. The `reports/real100/baseline.aggregate.json`
   also records `num_predictions` at commit time, so delta comparisons
   are always n-aware.

3. **Silence threshold self-adjusts.** ADR 0030 defines
   `δ_silence = max(5e-4, 0.5 / n_min)`. Increasing n automatically
   tightens the threshold without config changes.

4. **ADR 0005 boundary preserved.** Case definitions (queries +
   expected answers referencing private RFP content) stay in
   `eval/real_config.local.yaml` (gitignored). Only aggregate
   statistics are committed publicly per ADR 0005. This ADR records
   the expansion decision; the operator applies case additions locally.

## Target Cardinality

**n ≥ 30** as the near-term target (from n = 21). At n = 30:

- Wilson 95% CI on recall narrows from ±21 pp → ±18 pp.
- Single-case flip swings headline by +3.3 pp (vs +4.8 pp at n = 21).
- Silence threshold tightens to 0.017 (vs 0.024).

Longer-term target: n ≥ 50 (silence threshold ≤ 0.010, CI ≤ ±14 pp).

## Case Selection Criteria

New cases must satisfy:

1. **Verifiable expected terms** — the expected_terms must appear
   verbatim in indexed chunk text (not synthesized or paraphrased).
2. **Diverse query types** — include single_doc, comparison, and
   abstention cases to balance the distribution.
3. **Document coverage** — prefer documents not yet covered by
   existing cases to maximize corpus utilization.
4. **Stable ground truth** — expected answers must be factual (budget
   amounts, dates, technical requirements) rather than subjective.

## Consequences

- `reports/real100/eval_summary.json` will show higher `num_predictions`
  after each expansion run. Downstream scripts (leaderboard, delta
  reports) automatically read `num_predictions` from the summary.
- The committed `reports/real100/baseline.aggregate.json` must be
  updated via `make real-eval-baseline-update` after each expansion
  run to record the new n in the public provenance chain.
- Historical baselines with lower n remain valid for sign-comparison
  (direction of delta) but not for magnitude comparison — reviewers
  should note the n-change in PR descriptions when baseline is bumped.

## Alternatives Considered

**New separate series (`reports/real30/`)**: Rejected. Splits the
leaderboard time-series without benefit; the 100-doc corpus is shared
so retrieval measurements are directly comparable.

**Increase only via private data expansion** (new documents):
Deferred. New document ingestion requires ADR 0005 review + index
rebuild. Case expansion within the existing 100-doc corpus is a
lower-friction immediate improvement.

## References

- ADR 0001 — naive_baseline invariant (unaffected; public synthetic eval)
- ADR 0005 — eval split boundary (private data stays gitignored)
- ADR 0030 — leaderboard silence threshold + n-aware formula
- Issue #732 — implementation tracking
