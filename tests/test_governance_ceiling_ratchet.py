"""Regression tests for the ADR 0062 monotone ceiling ratchet enforcement
(issue #1150).

ADR 0062 documents a ratchet contract — the failure-rate ceilings in
``tests/test_failure_rate_regression.py`` may only go DOWN, never up without an
explicit ``[ALLOW_REGRESSION]`` justification. Before #1150 nothing enforced
it: ``test_ceilings_are_monotone_sane`` only checks each ceiling against the
*current committed rate*, never the base branch, so a PR could RAISE a ceiling
(loosening the gate) with every test green.

These tests pin the pure helpers that the
``check_branch_and_issue.py --check-ceiling-ratchet`` CI gate is built on:
parsing ceilings out of source (AST, no import), parsing the
``[ALLOW_REGRESSION]`` tokens out of a PR body, and the loosening-detection
itself. The (a)/(b)/(c) cases from the issue map to
``test_raise_without_token_*`` / ``test_raise_with_token_passes`` /
``test_lowered_or_equal_passes``.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from eval.scorers.failure_classifier import FAILURE_CATEGORIES

REPO = Path(__file__).resolve().parents[1]
CEILING_TEST = REPO / "tests" / "test_failure_rate_regression.py"
CHECK_SCRIPT = REPO / "scripts" / "check_branch_and_issue.py"

sys.path.insert(0, str(REPO / "scripts"))
import _governance as gov  # type: ignore  # noqa: E402


SAMPLE_SOURCE = """
CEILING_TOTAL_FAILURE_RATE = 0.86
CEILING_RATE_BY_CATEGORY = {
    "verifier_false_negative": 0.40,
    "retrieval_miss": 0.34,
}
"""


class TestParseFailureRateCeilings(unittest.TestCase):
    def test_parses_sample_with_total_under_sentinel(self) -> None:
        c = gov.parse_failure_rate_ceilings(SAMPLE_SOURCE)
        self.assertEqual(
            c,
            {
                gov.TOTAL_FAILURE_RATE_KEY: 0.86,
                "verifier_false_negative": 0.40,
                "retrieval_miss": 0.34,
            },
        )

    def test_parses_the_real_committed_file(self) -> None:
        c = gov.parse_failure_rate_ceilings(CEILING_TEST.read_text(encoding="utf-8"))
        # Total present under the sentinel key; gated categories present.
        self.assertIn(gov.TOTAL_FAILURE_RATE_KEY, c)
        self.assertIn("verifier_false_negative", c)
        self.assertIn("retrieval_miss", c)
        for v in c.values():
            self.assertIsInstance(v, float)
            self.assertGreaterEqual(v, 0.0)

    def test_real_file_gated_keys_are_known_categories(self) -> None:
        """Integrity: every gated key is an ADR 0075 category or the total
        sentinel. Catches a constant rename that would silently blind the gate.
        """
        c = gov.parse_failure_rate_ceilings(CEILING_TEST.read_text(encoding="utf-8"))
        allowed_keys = set(FAILURE_CATEGORIES) | {gov.TOTAL_FAILURE_RATE_KEY}
        self.assertTrue(set(c).issubset(allowed_keys), set(c) - allowed_keys)

    def test_total_sentinel_does_not_collide_with_a_category(self) -> None:
        self.assertNotIn(gov.TOTAL_FAILURE_RATE_KEY, set(FAILURE_CATEGORIES))

    def test_missing_dict_assignment_raises(self) -> None:
        with self.assertRaises(ValueError):
            gov.parse_failure_rate_ceilings("CEILING_TOTAL_FAILURE_RATE = 0.86\n")

    def test_missing_total_assignment_raises(self) -> None:
        with self.assertRaises(ValueError):
            gov.parse_failure_rate_ceilings(
                'CEILING_RATE_BY_CATEGORY = {"retrieval_miss": 0.34}\n'
            )

    def test_non_dict_value_raises(self) -> None:
        with self.assertRaises(ValueError):
            gov.parse_failure_rate_ceilings(
                "CEILING_TOTAL_FAILURE_RATE = 0.86\n"
                "CEILING_RATE_BY_CATEGORY = 0.5\n"
            )


class TestParseAllowRegressionCategories(unittest.TestCase):
    def test_empty_body(self) -> None:
        self.assertEqual(gov.parse_allow_regression_categories(""), set())
        self.assertEqual(gov.parse_allow_regression_categories(None), set())  # type: ignore[arg-type]

    def test_no_token(self) -> None:
        self.assertEqual(
            gov.parse_allow_regression_categories("just a normal PR body"), set()
        )

    def test_single_token(self) -> None:
        body = "We loosen [ALLOW_REGRESSION: retrieval_miss 0.34→0.40 cross-HEAD variance]."
        self.assertEqual(
            gov.parse_allow_regression_categories(body), {"retrieval_miss"}
        )

    def test_multiple_tokens(self) -> None:
        body = (
            "[ALLOW_REGRESSION: retrieval_miss 0.34->0.40 x]\n"
            "[ALLOW_REGRESSION: total_failure_rate 0.86->0.90 y]"
        )
        self.assertEqual(
            gov.parse_allow_regression_categories(body),
            {"retrieval_miss", "total_failure_rate"},
        )

    def test_arrow_variants_irrelevant_to_capture(self) -> None:
        # Both the unicode arrow and ASCII '->' work — we only capture the
        # leading category name, so the arrow form never matters.
        for arrow in ("→", "->", " "):
            with self.subTest(arrow=arrow):
                body = f"[ALLOW_REGRESSION: verifier_false_negative 0.40{arrow}0.45 r]"
                self.assertEqual(
                    gov.parse_allow_regression_categories(body),
                    {"verifier_false_negative"},
                )

    def test_lowercase_keyword_does_not_match(self) -> None:
        # The token keyword is a deliberate, visible marker; a lowercase
        # mention in prose must not silently satisfy the gate.
        body = "we should allow_regression: retrieval_miss someday"
        self.assertEqual(gov.parse_allow_regression_categories(body), set())


class TestCeilingRatchetViolations(unittest.TestCase):
    # --- (a) raised without token → violation -----------------------------
    def test_raise_without_token_violates(self) -> None:
        v = gov.ceiling_ratchet_violations(
            {"retrieval_miss": 0.34}, {"retrieval_miss": 0.40}, set()
        )
        self.assertEqual(len(v), 1)
        self.assertIn("retrieval_miss", v[0])
        self.assertIn("ALLOW_REGRESSION", v[0])

    def test_total_raise_without_token_violates(self) -> None:
        v = gov.ceiling_ratchet_violations(
            {gov.TOTAL_FAILURE_RATE_KEY: 0.86},
            {gov.TOTAL_FAILURE_RATE_KEY: 0.90},
            set(),
        )
        self.assertEqual(len(v), 1)
        self.assertIn(gov.TOTAL_FAILURE_RATE_KEY, v[0])

    # --- (b) raised with token → passes -----------------------------------
    def test_raise_with_token_passes(self) -> None:
        v = gov.ceiling_ratchet_violations(
            {"retrieval_miss": 0.34}, {"retrieval_miss": 0.40}, {"retrieval_miss"}
        )
        self.assertEqual(v, [])

    def test_total_raise_with_token_passes(self) -> None:
        v = gov.ceiling_ratchet_violations(
            {gov.TOTAL_FAILURE_RATE_KEY: 0.86},
            {gov.TOTAL_FAILURE_RATE_KEY: 0.90},
            {gov.TOTAL_FAILURE_RATE_KEY},
        )
        self.assertEqual(v, [])

    # --- (c) lowered / equal → passes -------------------------------------
    def test_lowered_or_equal_passes(self) -> None:
        self.assertEqual(
            gov.ceiling_ratchet_violations(
                {"retrieval_miss": 0.34}, {"retrieval_miss": 0.30}, set()
            ),
            [],
        )
        self.assertEqual(
            gov.ceiling_ratchet_violations(
                {"retrieval_miss": 0.34}, {"retrieval_miss": 0.34}, set()
            ),
            [],
        )

    # --- removal (the deletion bypass hole) -------------------------------
    def test_removed_category_without_token_violates(self) -> None:
        v = gov.ceiling_ratchet_violations({"retrieval_miss": 0.34}, {}, set())
        self.assertEqual(len(v), 1)
        self.assertIn("removed", v[0])

    def test_removed_category_with_token_passes(self) -> None:
        v = gov.ceiling_ratchet_violations(
            {"retrieval_miss": 0.34}, {}, {"retrieval_miss"}
        )
        self.assertEqual(v, [])

    # --- new category is fine (tightening the net) ------------------------
    def test_new_category_passes(self) -> None:
        v = gov.ceiling_ratchet_violations(
            {}, {"verifier_false_negative": 0.40}, set()
        )
        self.assertEqual(v, [])

    # --- mixed: one justified raise + one unjustified ---------------------
    def test_mixed_only_unjustified_violates(self) -> None:
        base = {"retrieval_miss": 0.34, "verifier_false_negative": 0.40}
        head = {"retrieval_miss": 0.40, "verifier_false_negative": 0.45}
        v = gov.ceiling_ratchet_violations(base, head, {"retrieval_miss"})
        self.assertEqual(len(v), 1)
        self.assertIn("verifier_false_negative", v[0])

    def test_float_noise_not_flagged(self) -> None:
        # Reparsed-but-equal values must not register as a raise.
        v = gov.ceiling_ratchet_violations(
            {"retrieval_miss": 0.1 + 0.2}, {"retrieval_miss": 0.3}, set()
        )
        self.assertEqual(v, [])


class TestCliWiring(unittest.TestCase):
    def test_check_ceiling_ratchet_flag_is_registered(self) -> None:
        """Smoke: the CI flag is wired into the argparser (catches a wiring
        regression without needing gh / network)."""
        r = subprocess.run(
            ["python3", str(CHECK_SCRIPT), "--help"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("--check-ceiling-ratchet", r.stdout)


if __name__ == "__main__":
    unittest.main()
