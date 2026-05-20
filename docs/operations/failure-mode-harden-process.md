# Failure-mode harden process

The **monotone-harden** workflow that turns the ADR 0059 failure classifier
+ supply 2 dashboard into a *closed error loop*: every failure mode an audit
surfaces gets a category, eval examples, and a ratcheting ceiling — so the
same regression can never silently recur.

This is Phase 5 audit (#992) item 3. The contract is ADR 0062.

## The loop

```
audit surfaces a failure mode  (e.g. #1005 retrieval_miss, #1020 verifier_false_negative)
        │
        ▼
(a) category exists in failure_classifier.py?  ──no──▶  add category + lock test
        │ yes                                            (tests/test_failure_classifier.py)
        ▼
(b) ≥5 representative examples in real-eval set?  ──no──▶  add hardcase examples
        │ yes                                              (eval/real_config.local.yaml)
        ▼
(c) ceiling set in test_failure_rate_regression.py?  ──no──▶  set ceiling = current rate + margin
        │ yes
        ▼
(d) supply 2 dashboard renders it  (scripts/render_failure_distribution.py)
        │
        ▼
fix lands ──▶ lower committed rate ──▶ TIGHTEN ceiling in same PR ──▶ loop closes tighter
```

The ratchet only turns **one way**: ceilings go down as fixes land, never
up without an explicit `[ALLOW_REGRESSION]` justification.

## Roles of each surface

| surface | file | role |
|---|---|---|
| classifier | `eval/scorers/failure_classifier.py` | 7-category first-match-wins labels (ADR 0059) |
| classifier lock | `tests/test_failure_classifier.py` | pins ordering so Finding #1 stays `verifier_false_negative` |
| dashboard | `scripts/render_failure_distribution.py` | renders distribution + ADR 0059 contract ✓ (supply 2) |
| **regression gate** | `tests/test_failure_rate_regression.py` | **ratcheting ceilings on the committed baseline (ADR 0062)** |
| baseline | `reports/real100/baseline.aggregate.json` | committed aggregate the gate reads (ADR 0005 boundary) |

## Adding a newly-surfaced failure mode

1. **Confirm the category.** If the mode fits an existing 7-category label,
   skip to step 3. If it's genuinely new, add it to `FAILURE_CATEGORIES`
   and `classify_failure()` in `failure_classifier.py`, respecting the
   first-match-wins ordering (ADR 0059). Add a unit test in
   `tests/test_failure_classifier.py`.

2. **Add ≥5 examples.** Add at least 5 representative hardcase queries that
   exhibit the mode to `eval/real_config.local.yaml` (gitignored, ADR 0005).
   This gives the rate a stable denominator signal.

3. **Set the ceiling.** Regen the baseline (`make real-eval` +
   `make real-eval-baseline-update STRICT=1`), read the new category's
   committed rate, and add it to `CEILING_RATE_BY_CATEGORY` in
   `tests/test_failure_rate_regression.py` at `current_rate + margin`. The
   margin absorbs the cross-HEAD variance the variance audit (#1025)
   measured — set it generously on first introduction, then tighten.

4. **Verify the dashboard renders it.** Re-run
   `scripts/render_failure_distribution.py`; the new category appears in
   `reports/real100/failure_distribution.md`.

## Tightening a ceiling after a fix

When a fix PR lowers a gated rate:

1. Regen the baseline at the fix's HEAD.
2. Lower the category's entry in `CEILING_RATE_BY_CATEGORY` to the new
   `current_rate + small_margin` **in the same PR**.
3. `test_ceilings_are_monotone_sane` guards against setting a ceiling
   *below* the current rate (an inverted ratchet).

## Why rates, not absolute counts

The variance audit (#1025) found absolute counts are deterministic *per
HEAD* but vary cross-HEAD (`verifier_false_negative` ranged 49 ↔ 65 ↔ 76
across PR #1001 / #1004 / #1018, while same-HEAD N=3 runs were
byte-identical). Rates with a documented margin absorb that cross-HEAD
variance; genuine regressions beyond historical variance still fire the
gate. Always compare before/after a fix **on the same commit** — cross-HEAD
comparisons confound the fix with intervening changes (e.g. the ADR 0058
hybrid switch).

## Worked examples (audits that fed this loop)

| audit | mode | committed rate | ceiling |
|---|---|---:|---:|
| #1020 | `verifier_false_negative` | 0.344 (76/221) | 0.40 |
| #1005 | `retrieval_miss` | 0.290 (64/221) | 0.34 |
| — | total failures | 0.814 (180/221) | 0.86 |

Each audit's follow-up fixes (Issue F verifier hardening, Issue A top_k
ablation, …) target lowering these rates, then tightening the ceiling.
