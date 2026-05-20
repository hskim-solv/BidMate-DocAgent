# 0062: Failure-rate regression contract (Phase 5 supply 3)

- Status: proposed
- Date: 2026-05-19
- Deciders: Hyunsoo Kim
- Related: ADR 0059 (failure-mode classifier), Phase 5 audit (#992) item 3, supply 2 dashboard (PR #1004), audits #1005 / #1020 / #1025, issue #1066

## Context

ADR 0059 (PR #1001) introduced the 7-category `failure_classifier.py` and
the supply 2 dashboard (PR #1004) renders the distribution. Three audits
then quantified the dominant modes — `retrieval_miss=83` (#1005),
`verifier_false_negative=76` (#1020), and the cross-HEAD variance source
(#1025). But the Phase 5 audit (#992) item 3 "closed error loop" stays
**absent**: nothing *prevents silent regression* of those modes. As the
audit put it (`docs/audits/eval-framework-phase5-audit.md`), a finding
"어디에도 누적 안 됨 — 다음 분기에 같은 신호가 나와도 다시 raw inspection으로
발견" — the signal isn't ratcheted, so the same regression can recur
undetected.

The variance audit (#1025) also established that absolute failure counts
are deterministic *per HEAD* but vary cross-HEAD (verifier_false_negative
ranged 49 ↔ 65 ↔ 76 across PR #1001 / #1004 / #1018). Any ceiling contract
must absorb that documented cross-HEAD variance rather than flap on every
baseline regen.

## Decision

Introduce a **failure-rate regression contract** in two parts:

1. `tests/test_failure_rate_regression.py` reads the committed
   `reports/real100/baseline.aggregate.json` (aggregate-only, ADR 0005
   boundary) and asserts each gated category's failure RATE
   (`count / num_predictions`) stays under a **monotone-ratchet ceiling**.
   Gated today: `total_failure_rate ≤ 0.86`,
   `verifier_false_negative ≤ 0.40`, `retrieval_miss ≤ 0.34`. Ceilings
   carry a margin over the current committed rate to absorb the cross-HEAD
   variance #1025 measured. They may only ratchet **down** as Issue
   F/G/A-class fixes land — a baseline regen that worsens a gated rate
   beyond its ceiling must tighten-or-justify (the test fails, forcing
   acknowledgment), never silently regress.

2. `docs/operations/failure-mode-harden-process.md` documents the
   monotone-harden workflow: when an audit surfaces a new failure mode →
   (a) add/confirm its category in `failure_classifier.py` + lock test,
   (b) add ≥5 representative examples to the real-eval set, (c) set or
   tighten its ceiling in `test_failure_rate_regression.py`, (d) the
   supply 2 dashboard renders it. This is the closed loop.

The test also re-asserts the ADR 0059 first-match contract
(`verifier_false_negative == abstention_outcomes.incorrect_answer`) so a
future ordering tweak that breaks it fails the regression gate too.

No production code path changes (`rag_*.py`, `api/`, `eval/config.yaml`
untouched). The test is a read-only consumer of the committed baseline;
it runs in CI without private data.

## Consequences

- **Phase 5 audit item 3 (✗ absent → ✓ present)** — closed error loop:
  the dominant failure modes are now gated, not just measured. A silent
  regression of `verifier_false_negative` or `retrieval_miss` past its
  ceiling reds the Pytest gate.
- The Phase 5 supply trilogy (1 classifier / 2 dashboard / 3 regression
  contract) is complete; the portfolio narrative closes the "측정 → 분류
  → dashboard → ceiling 잠금" loop.
- Future fix PRs (Issue F verifier hardening / Issue A top_k ablation /
  Issue G multi-doc topic spread) have a concrete ratchet target: lower
  the committed rate, then tighten the ceiling in the same PR.
- Cost: a baseline regen that worsens a gated rate now requires either a
  fix or an explicit `[ALLOW_REGRESSION]` ceiling bump — slightly more
  friction on regen PRs, by design.
- ADR 0001 (naive_baseline byte-identical) / 0003 (answer dict) / 0005
  (eval-split aggregate-only) / 0059 (classifier additive) invariance all
  preserved.

## Alternatives considered

- **Gate on absolute counts** — rejected: the variance audit (#1025)
  showed counts shift cross-HEAD; rates with documented margin are stabler.
- **Gate every category** — rejected for v1: planner/generator/context
  categories are near-zero and noisy; gating the 2 dominant modes + total
  is the high-signal subset. Add categories as audits surface them (that
  IS the harden process).
- **Run real-eval in the test** — rejected: private data can't enter CI
  (ADR 0005). Reading the committed aggregate keeps the gate CI-runnable
  and deterministic.

## Verification

<!-- verifies-key: tests/test_failure_rate_regression.py:CEILING_RATE_BY_CATEGORY -->
<!-- verifies-key: tests/test_failure_rate_regression.py:def test_gated_category_rates_under_ceiling -->
<!-- verifies-key: tests/test_failure_rate_regression.py:def test_adr_0059_first_match_contract -->
<!-- verifies-key: docs/operations/failure-mode-harden-process.md:monotone-harden -->
