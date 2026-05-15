# 0048: realN metrics extension — per-field accuracy + abstention calibration

- **Status**: accepted
- **Date**: 2026-05-15
- **Deciders**: hskim-solv
- **Related**: issue #870, ADR 0001, ADR 0003, ADR 0005, ADR 0030, ADR 0039, ADR 0044, ADR 0046

## Context

ADR 0044 expanded real100 cases from n=21 toward n≥30 (and n≥50 long-term) but kept the metric surface unchanged. Two measurement blindspots remain at the aggregate level:

1. **Per-field accuracy is collapsed.** `data/data_list.csv` carries four single-doc metadata fields at 92–100% fill rate (`발주 기관` 100%, `사업명` 100%, `사업 금액` 99%, `입찰 참여 마감일` 92%). All four collapse into one `accuracy` number in [`eval/run_eval.py:metric_block`](../../eval/run_eval.py); operators cannot tell whether the verifier struggles with deadlines vs budgets vs agencies. The `by_hardcase_category` aggregate ([`eval/run_eval.py:682`](../../eval/run_eval.py)) demonstrates the bucket-by-tag pattern works — the same approach has been declined for the four metadata fields until now.

2. **Abstention has counts but no calibration.** `abstention_outcomes` (#463, [`eval/run_eval.py:_abstention_outcomes`](../../eval/run_eval.py)) splits the 3 boundary buckets, and `abstention` is a 0/1 rate, but no calibration metric (ECE / Brier) measures whether the verifier's confidence aligns with ground-truth correctness. Without it, "the verifier abstained 50% of the time" is indistinguishable from "the verifier abstained on the right 50%."

`by_hardcase_category` and `abstention_outcomes` are already on the ADR 0005 aggregate-only allowlist (PR #849, closes #845). Adding two more aggregate keys is the minimum incremental measurement surface needed before ADR 0044's n=50 baseline is re-cut.

## Decision

Add two aggregates to `eval_summary.json` per `metric_block`:

1. **`by_metadata_field`**: per-field block (same shape as `by_hardcase_category` / `by_query_type`) for the four single-doc metadata fields. Each case opts in by setting `metadata_field: <agency|project|budget|deadline>` in its config; cases without the key are simply excluded from the per-field aggregate (forward-compatible).

   Allowed values pinned in [`eval/scorers/_shared.py`](../../eval/scorers/_shared.py) as `METADATA_FIELD_KEYS = ("agency", "project", "budget", "deadline")`. `eval/run_eval.py::load_config` rejects any case with an unknown `metadata_field`.

2. **`abstention_calibration`**: a single dict carrying:
   - `ece`: Expected Calibration Error with 10 fixed-width bins on `[0, 1]`
   - `brier`: Brier score (mean squared error between confidence and correctness)
   - `n`: number of cases that contributed (those with a numeric `confidence` ∈ `[0, 1]` in `prediction.answer`)

   When no case carries `confidence`, the entire block is emitted as `null` rather than `{ece: 0.0, ...}`. Existing snapshots produced before this ADR are forward-compatible and render as `null`.

   `score_case` passes `confidence` through from `prediction.answer.confidence` to the case result; the aggregator reads it from results. The `correctness` signal is `1 - abs(abstained - answerable_is_false)` for abstention cases (i.e., a correct refusal scores 1, an incorrect answer scores 0).

Both aggregates land in the aggregate-only allowlist; no per-case payload crosses the ADR 0005 boundary.

## Consequences

- `reports/eval_summary.json` gains `by_metadata_field` (dict, possibly empty) and `abstention_calibration` (dict or null) keys. Both flow through to `reports/real100/baseline.aggregate.json` snapshots.
- Leaderboard (ADR 0030) can render two new columns once real100 cases are tagged: per-field accuracy strip (4 cells) and ECE/Brier (2 cells). This ADR does not change the leaderboard; PR3 of the stack does.
- ADR 0001 invariant: pipeline behavior is unchanged. Both aggregates are computed downstream of `run_rag_query`. `naive_baseline` row is bit-identical to pre-0048 runs as long as the case set is unchanged.
- ADR 0044 in-place expansion: new cases tagged with `metadata_field` populate `by_metadata_field` automatically. Existing 21 cases without the tag stay in the headline `accuracy` only.
- ADR 0039 unaffected: this ADR adds `by_metadata_field` keys (per RFP field), parallel to but distinct from `by_hardcase_category` keys (per HWP structural failure mode).
- `abstention_calibration` block stays `null` until a future ADR mandates that the answer dict (ADR 0003 `schema_version: 2`) emits a `confidence` field. This ADR does not require that emission; it only defines the aggregator side of the contract so the rollout can be staged.
- CI safe: no new dependencies, no LLM calls, all logic is arithmetic over existing case-result fields.

## Alternatives considered

- **Per-field as a sub-key inside `by_query_type.single_doc`**: rejected. `by_query_type` is already complete with `query_type ∈ {single_doc, comparison, follow_up, abstention}`; nesting a four-way split inside `single_doc` would shadow it. A peer-level `by_metadata_field` aggregate is parallel to `by_hardcase_category` and matches existing reading patterns.
- **Require `confidence` emission immediately**: rejected. The answer dict contract (ADR 0003) does not yet specify a confidence field, and forcing it onto every pipeline in this PR would mix two decisions. Forward-compatible null is the safer staging.
- **Use Platt-scaled ECE or quantile binning**: deferred. Fixed-width 10-bin ECE is the standard for first-pass calibration measurement and matches the small-n regime we are in (n=30–50). Quantile binning becomes interesting at n≥200.

## Verification

The `by_metadata_field` and `abstention_calibration` aggregates flow through into the committed real100 baseline once PR3 (n=50 re-measurement) lands. Until then, the keys must appear in the smoke run's `reports/eval_summary.json`.

<!-- verifies-key: reports/eval_summary.json:by_metadata_field -->
<!-- verifies-key: reports/eval_summary.json:abstention_calibration -->
<!-- verifies-key: eval/scorers/_shared.py:METADATA_FIELD_KEYS -->
