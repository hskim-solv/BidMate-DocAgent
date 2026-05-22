"""ADR 0062 — failure-rate regression contract (Phase 5 supply 3).

Closes the Phase 5 audit (#992) item 3 "closed error loop" gap: the
ADR 0059 classifier (PR #1001) labels failures and the supply 2 dashboard
(PR #1004) renders them, but nothing *prevents silent regression* of the
dominant failure modes the audits surfaced (#1005 retrieval_miss=67,
#1020 verifier_false_negative=76, #1025 variance source).

This test reads the committed ``reports/real100/baseline.aggregate.json``
(aggregate-only, ADR 0005 boundary) and asserts each gated category's
failure RATE stays under a monotone-ratchet ceiling. The ceilings may
only ratchet DOWN as fixes land — a baseline regen that worsens a gated
rate beyond its ceiling must either tighten-or-justify (the test fails,
forcing acknowledgment instead of a silent regression).

Why rates, not absolute counts: the variance audit (#1025) found absolute
counts are deterministic *per HEAD* but vary cross-HEAD (49 ↔ 65 ↔ 76 for
verifier_false_negative across PR #1001 / #1004 / #1018). Ceilings carry a
documented margin over the current committed value to absorb that
cross-HEAD variance; genuine regressions beyond historical variance still
fire.

Process: see ``docs/operations/failure-mode-harden-process.md``.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from eval.scorers.failure_classifier import FAILURE_CATEGORIES

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "reports" / "real100" / "baseline.aggregate.json"

# --- Monotone-ratchet ceilings (ADR 0062) ----------------------------------
#
# Each value is an UPPER BOUND on the committed baseline's failure RATE
# (category_count / num_predictions). These may only ratchet DOWN as fixes
# land — never up without an [ALLOW_REGRESSION] justification in the PR that
# regenerates the baseline.
#
# Current committed baseline (n=221):
#   total failures            180 / 221 = 0.814
#   verifier_false_negative    76 / 221 = 0.344  (Finding #1, audit #1020)
#   retrieval_miss             67 / 221 = 0.303  (dominant, audit #1005)
#
# Initial ceilings = current rate + margin absorbing the cross-HEAD variance
# the variance audit (#1025) measured (verifier_false_negative ranged
# 49-76 → rate 0.22-0.34 across HEADs). Tighten these as Issue F/G/A fixes
# land.
CEILING_TOTAL_FAILURE_RATE = 0.86
CEILING_RATE_BY_CATEGORY = {
    "verifier_false_negative": 0.40,
    "retrieval_miss": 0.34,
}


def _load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        raise unittest.SkipTest(f"baseline missing: {BASELINE_PATH}")
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


class FailureRateRegressionTest(unittest.TestCase):
    """Lock failure-rate ceilings against the committed baseline."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = _load_baseline()
        cls.n = int(cls.baseline.get("num_predictions", 0))
        cls.fcc = cls.baseline.get("failure_category_counts") or {}

    def test_baseline_has_failure_category_counts(self) -> None:
        """ADR 0059 surface must be present in the committed baseline."""
        self.assertTrue(
            self.fcc,
            "baseline.aggregate.json missing failure_category_counts — "
            "regen with ADR 0059 wired (PR #1001+).",
        )
        self.assertGreater(self.n, 0, "num_predictions must be > 0")
        # All 7 ADR 0059 categories present (the aggregator always emits them).
        for category in FAILURE_CATEGORIES:
            self.assertIn(
                category,
                self.fcc,
                f"category {category!r} absent — classifier schema drifted.",
            )

    def test_total_failure_rate_under_ceiling(self) -> None:
        total = sum(int(v) for v in self.fcc.values())
        rate = total / self.n
        self.assertLessEqual(
            rate,
            CEILING_TOTAL_FAILURE_RATE,
            f"total failure rate {rate:.3f} ({total}/{self.n}) exceeds ceiling "
            f"{CEILING_TOTAL_FAILURE_RATE}. Either fix the regression or "
            f"tighten-or-justify the ceiling per "
            f"docs/operations/failure-mode-harden-process.md.",
        )

    def test_gated_category_rates_under_ceiling(self) -> None:
        for category, ceiling in CEILING_RATE_BY_CATEGORY.items():
            with self.subTest(category=category):
                count = int(self.fcc.get(category, 0))
                rate = count / self.n
                self.assertLessEqual(
                    rate,
                    ceiling,
                    f"{category} rate {rate:.3f} ({count}/{self.n}) exceeds "
                    f"ceiling {ceiling}. Either fix the regression or "
                    f"tighten-or-justify the ceiling per "
                    f"docs/operations/failure-mode-harden-process.md.",
                )

    def test_ceilings_are_monotone_sane(self) -> None:
        """Ceilings must each sit at-or-above the current committed rate.

        Guards against a fat-finger that sets a ceiling BELOW the current
        baseline (which would make the test pass only because the rate is
        already low — defeating the ratchet). Each gated ceiling should be
        ≥ current rate; the harden process tightens it toward the current
        rate as fixes land, never below.
        """
        for category, ceiling in CEILING_RATE_BY_CATEGORY.items():
            with self.subTest(category=category):
                count = int(self.fcc.get(category, 0))
                rate = count / self.n
                self.assertGreaterEqual(
                    ceiling,
                    rate,
                    f"ceiling {ceiling} for {category} is below current rate "
                    f"{rate:.3f} — ratchet inverted. Set ceiling ≥ current.",
                )

    def test_adr_0059_first_match_contract(self) -> None:
        """Integrity: verifier_false_negative == abstention_outcomes.incorrect_answer.

        ADR 0059 first-match-wins ordering guarantees the Finding #1 pattern
        accumulates into verifier_false_negative. The supply 2 dashboard
        (#1004) surfaces this; we re-assert it here so a future ordering
        tweak that breaks the contract fails the regression gate too.
        """
        ao = self.baseline.get("abstention_outcomes") or {}
        if "incorrect_answer" not in ao:
            self.skipTest("abstention_outcomes.incorrect_answer absent")
        vfn = int(self.fcc.get("verifier_false_negative", 0))
        incorrect = int(ao["incorrect_answer"])
        self.assertEqual(
            vfn,
            incorrect,
            f"ADR 0059 contract broken: verifier_false_negative={vfn} != "
            f"abstention_outcomes.incorrect_answer={incorrect}.",
        )


if __name__ == "__main__":
    unittest.main()
