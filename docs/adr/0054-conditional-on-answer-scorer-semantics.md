# ADR 0054 — Conditional-on-answer scorer semantics

- Status: Proposed
- Date: 2026-05-18
- Authors: Hyunsoo Kim
- Related: ADR 0001 (naive_baseline invariance), ADR 0003 (answer-contract schema_version=2), ADR 0005 (eval split), ADR 0030 (leaderboard surfaces), ADR 0053 (distinguishing-power floors — **augmented by this ADR, not superseded**)
- Augments: ADR 0053
- Issue: #958

## Context

PR #946 (ADR 0053 Step 5b) shipped `scripts/distinguishing_power.py` and produced the first measurement at `n=221` on the private 100-doc real corpus. The gauge reported **3 of 5 metrics as "signal NOT alive"** — `groundedness`, `citation_precision`, and `answer_format_compliance` all *under-perform* the `random_retrieval` floor:

| metric | default (full) | random_retrieval | gap | signal_alive |
|---|---:|---:|---:|:---:|
| accuracy | 29.66% | 2.54% | **+27.12pp** | ✓ |
| claim_citation_alignment | 96.28% | 88.24% | **+8.04pp** | ✓ |
| groundedness | 25.34% | 36.20% | **−10.86pp** | ❌ |
| citation_precision | 19.02% | 34.84% | **−15.82pp** | ❌ |
| answer_format_compliance | 20.81% | 44.80% | **−23.98pp** | ❌ |

Source: `reports/real100/distinguishing_power.md` at n=221, gauge surfaced 2026-05-17.

### Root cause — the Goodhart trap

`random_retrieval` correctly abstains on **≈89%** of unanswerable cases (the verifier rejects noisy candidates → `status: insufficient`). The pre-fix `eval/scorers/case.py:79-92` branch then assigned **vacuous-truth 1.0** to `groundedness` and `citation_precision` on every (unanswerable AND abstained AND no-evidence) case:

```python
# pre-fix (eval/scorers/case.py:89-91)
else:  # answerable=False
    groundedness = 1.0 if abstained and not evidence else 0.0
    citation_precision = 1.0 if abstained and not evidence else 0.0
    abstention = 1.0 if abstained else 0.0
```

Folding those vacuous 1.0s into the mean **inflated high-abstention runs' quality scores**:

* `random_retrieval` at 89% abstention → groundedness mean dragged up by ~0.89 × 1.0 → reported 36.20% instead of the substantive ~6%.
* `single_chunk` at lower abstention (~7%) → much smaller inflation → reported 8.14% (closer to truth).
* `full` default at moderate abstention → modest inflation, but still less than random's because random abstains far more often.

The flip happens precisely because random abstains more than full does — exactly the regime where the **gauge is supposed to fail loudly**, but the vacuous 1.0 hides the failure.

### Why it's a double-count, not just a definitional quirk

Refusal correctness is **already measured by two complementary signals**:

* `abstention` rate (`eval/run_eval.py:597`) — fraction of unanswerable cases where the model correctly refused.
* `abstention_outcomes` 3-bin (`eval/run_eval.py:377-411`, PR #464) — `correct_refusal` / `incorrect_answer` / `boundary_partial` decomposition.

Folding the same correct-refusal signal a third time into `groundedness` / `citation_precision` / `answer_format_compliance` is double-counting that biases every aggregate toward whichever pipeline abstains most. ADR 0053's gauge surfaced this; ADR 0054 fixes the scorer that produced it.

`answer_format_compliance` has the same shape — `score_answer_format` (`eval/scorers/format.py:64-82`) treats `status=insufficient`, `claims=[]`, `min_claims=0` as *all checks pass* → 1.0. On the same correct_refusal cases, this trivially-true 1.0 inflates the high-abstention run's format-compliance mean.

## Decision

1. **Quality metrics are conditional on a substantive answer attempt.** `accuracy`, `groundedness`, `citation_precision`, and `answer_format_compliance` are measured **only** where the model produced (or attempted to produce) a substantive answer. The non-substantive paths return `None` and are excluded from the mean denominator.

   Concretely in `eval/scorers/case.py`:

   ```python
   # post-fix
   if answerable:
       accuracy = 1.0 if doc_match and term_match and not abstained else 0.0
       groundedness = 1.0 if term_match and evidence and not abstained else 0.0
       citation_precision = citation_doc_precision if citation_term_match else 0.0
       abstention = None
   else:
       accuracy = None                  # was already None — unchanged
       groundedness = None              # was vacuous 1.0 — now None
       citation_precision = None        # was vacuous 1.0 — now None
       abstention = 1.0 if abstained else 0.0
   # post-process: format_compliance is also vacuously 1.0 on the
   # (unanswerable AND abstained AND no-evidence) path → None there too.
   if not answerable and abstained and not evidence:
       answer_format_payload["answer_format_compliance"] = None
   ```

2. **Refusal correctness is measured exclusively** by `abstention` (rate) + `abstention_outcomes` (3-bin, PR #464). No quality metric carries any refusal-correctness component.

3. **`metric_block` denominator is automatic.** `eval/run_eval.py:470-516` already has the None-filter pattern across all 5 metrics (`[r[m] for r in case_results if r[m] is not None]`); no patch needed there. Same pattern carries through `by_query_type`, `by_hardcase_category`, `by_slice`, `by_metadata_field` (all call `metric_block`).

4. **Distinguishing-power gauge gains transparency, not new logic.** `scripts/distinguishing_power.py` adds `_safe_abstention(run)` that surfaces per-run `abstention_rate` + `num_predictions` + `effective_n` (= num_predictions − sum of `abstention_outcomes` bins) into the gauge JSON + markdown. `signal_alive` remains computed strictly from the GAUGED_METRICS — the scorer fix is the *primary* defense, the gauge transparency the *secondary* one.

## Why these semantics, not the alternatives

| Alternative | Why rejected |
|---|---|
| Keep vacuous 1.0 and tighten `signal_alive` thresholds | Treats the symptom, not the disease. Any downstream consumer (README headline, eval-delta CI gate, by_query_type aggregates) still inherits the inflated means. The fix has to be at the scorer. |
| Return `0.0` instead of `None` for non-substantive cases | Replaces one double-count direction with another — high-abstention runs would now be artificially deflated. `None` correctly says "this metric does not apply to this case." |
| Define `groundedness` to include "correct refusal counts as grounded" | Conflates two genuinely-different success surfaces (substantive grounding vs. refusal correctness). The whole reason `abstention_outcomes` 3-bin exists is to surface refusal correctness on its own axis. |
| Patch `eval/scorers/format.py` directly | Requires duplicating the `answerable AND abstained AND not evidence` predicate inside the format scorer (which doesn't otherwise see those fields). Cleaner to post-process in `case.py` where all three are already in scope. |

## Consequences

### Positive

- **Distinguishing-power gauge regains its signal.** Quality metric means on each ablation run now reflect substantive-answer performance only. The 3 false-negative gauge verdicts (groundedness / citation_precision / answer_format_compliance) are expected to flip after the n=221 regen — *whether they do is verified by re-measurement*, not asserted here.
- **Eliminates the implicit Goodhart pressure** to abstain more (which pre-fix would silently inflate every quality mean except accuracy).
- **Aligns the leaderboard's narrative** with how a senior reviewer reads it: "quality on attempts, refusal on abstentions, never both at once."
- **Portfolio narrative**: PR #946 surfaced the trap → this PR fixes it. One-PR closed loop, ready to cite in interviews.

### Negative

- **`baseline.aggregate.json` shifts by design.** Quality means on the high-abstention runs will drop (vacuous 1.0s removed). `[ALLOW_REGRESSION: ADR 0054 metric-semantics shift]` PR tag required to pass `pr-eval.yml:185`.
- **Pre-fix metric values in any committed report (README headlines, blog posts, `reports/real100/baseline.aggregate.json` history) are now stale.** README L12 headline + `distinguishing_power.md` re-render captured in this PR; downstream portfolio narrative updates are out-of-scope for engineering repo (private `BidMate-DocAgent-portfolio` repo).
- **By-query-type / by-hardcase-category subsets** lose denominator in slices where every case is non-substantive (no answerable cases, or all answerable cases abstained). Those slices now report the metric as `None` rather than a misleading 0.0/1.0. Surfaced naturally in `metric_block` aggregates.

### Invariance check

- **ADR 0001 (naive_baseline preset, byte-identical determinism)**: preserved. `tests/test_eval_reproducibility_regression.py` asserts byte-identity *across two runs of the same config*, NOT absolute metric values — the deterministic None-fix still yields identical run1 vs. run2 output.
- **ADR 0003 (answer-contract schema_version=2)**: unchanged. The patch is at the scorer layer only; prediction dict shape and answer payload contract are untouched.
- **ADR 0005 (eval split public/private)**: unchanged. Aggregate-only artifacts (`baseline.aggregate.json`, `distinguishing_power.{md,aggregate.json}`) remain the only items crossing the commit boundary.
- **ADR 0044 / 0052 (real-eval n trajectory)**: unchanged. n=221 stays the measurement scale; only the per-case scoring rule shifts.
- **ADR 0052 (real-eval hardcase expansion)**: unchanged. Same 221 cases, re-scored under conditional semantics.
- **ADR 0053 (distinguishing-power floor ablations)**: **augmented**. Gauge formula `(default − floor) / (1 − floor)` unchanged. New transparency block (`abstention_rate` / `effective_n` per run) is added without altering `signal_alive` logic.

## Out of scope

- **Re-tuning answer LLM abstention thresholds** to chase a specific gauge gap. Measurement-layer fix only; pipeline tuning is Phase 3.
- **Adding synthetic unanswerable abstention cases to `eval/config.yaml`** — already has 23 such cases (`abstention_missing_*` prefix). No new synthetic surface in this PR.
- **`gauge` definition itself** (the `(default − floor) / (1 − floor)` formula). If the post-fix measurement still shows false negatives, that's a Phase 3 ADR 0055 candidate — gauge tightening or per-metric weighting.
- **Per-case data export for the gauge**. ADR 0005 boundary preserved; gauge stays aggregate-only.

## Verification

<!-- verifies-key: eval/scorers/case.py:groundedness = None -->
<!-- verifies-key: eval/scorers/case.py:citation_precision = None -->
<!-- verifies-key: eval/scorers/case.py:answer_format_payload -->
<!-- verifies-key: scripts/distinguishing_power.py:_safe_abstention -->
<!-- verifies-key: tests/test_scorers_case_abstention.py:TestUnanswerableCorrectRefusal -->
<!-- verifies-key: tests/test_scorers_case_abstention.py:TestMetricBlockExcludesNoneFromSubstantiveMean -->

## References

- ADR 0053 (`docs/adr/0053-distinguishing-power-floor-ablations.md`) — the gauge that surfaced this trap.
- PR #946 — first n=221 measurement, source of the table at the top of this ADR.
- PR #464 — `abstention_outcomes` 3-bin (the other half of refusal-correctness measurement).
- `eval/scorers/case.py:79-92` — the patched branch.
- `eval/run_eval.py:470-516` — `metric_block` None-filter (already in place).
- `scripts/distinguishing_power.py` — the gauge that consumed the inflated values pre-fix.
- `reports/real100/distinguishing_power.md` — pre-fix and (after regen) post-fix gauge output.
