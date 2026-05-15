"""Regression tests for ADR 0048 commit-boundary extensions (issue #870).

Mirrors ``test_eval_by_hardcase_category_aggregate_regression.py`` for the
two new keys ``by_metadata_field`` + ``abstention_calibration``. Asserts:

1. Allowed bucket keys + sub-keys pass through.
2. Unknown bucket keys are silently dropped (fail-closed) so the
   `METADATA_FIELD_KEYS` enum cannot be silently widened on the
   committable surface.
3. ``abstention_calibration`` accepts the 4 numeric sub-keys
   (ece / brier / n / num_bins) and drops anything else.
4. ``abstention_calibration: null`` round-trips as ``null`` (forward-compat
   when the answer dict does not yet emit ``confidence``).
5. ``FORBIDDEN_KEYS`` never leak through either new aggregate.
6. Single source of truth: the bucket whitelist agrees with
   ``METADATA_FIELD_KEYS`` in ``eval/scorers/_shared.py``.
"""
from __future__ import annotations

import unittest
from typing import Any

from scripts.run_real_eval_delta import (
    FORBIDDEN_KEYS,
    SAFE_CALIBRATION_KEYS,
    SAFE_METADATA_FIELD_BUCKET_KEYS,
    extract_aggregate,
)


def _minimal_summary(**extras: Any) -> dict[str, Any]:
    base = {
        "num_predictions": 3,
        "accuracy": 1.0,
        "groundedness": 1.0,
        "citation_precision": 1.0,
        "citation_grounding": None,
        "claim_citation_alignment": None,
        "answer_format_compliance": 1.0,
        "abstention": None,
        "retry": 0.0,
    }
    base.update(extras)
    return base


class TestByMetadataFieldExtractor(unittest.TestCase):
    def test_allowed_buckets_pass_through(self) -> None:
        summary = _minimal_summary(
            by_metadata_field={
                "agency": {"num_predictions": 5, "accuracy": 1.0},
                "project": {"num_predictions": 4, "accuracy": 0.75},
                "budget": {"num_predictions": 3, "accuracy": 0.66},
                "deadline": {"num_predictions": 2, "accuracy": 0.5},
            }
        )
        out = extract_aggregate(summary)
        self.assertIn("by_metadata_field", out)
        buckets = out["by_metadata_field"]
        self.assertEqual(set(buckets.keys()), {"agency", "project", "budget", "deadline"})
        self.assertEqual(buckets["agency"]["num_predictions"], 5)
        self.assertEqual(buckets["deadline"]["accuracy"], 0.5)

    def test_unknown_field_silently_dropped(self) -> None:
        summary = _minimal_summary(
            by_metadata_field={
                "agency": {"num_predictions": 1, "accuracy": 1.0},
                "secret_field": {"num_predictions": 99, "accuracy": 0.0},
                "internal_only": {"num_predictions": 99, "accuracy": 0.0},
            }
        )
        out = extract_aggregate(summary)
        buckets = out.get("by_metadata_field", {})
        self.assertIn("agency", buckets)
        self.assertNotIn("secret_field", buckets)
        self.assertNotIn("internal_only", buckets)

    def test_absent_when_no_buckets(self) -> None:
        summary = _minimal_summary()
        out = extract_aggregate(summary)
        self.assertNotIn("by_metadata_field", out)

    def test_no_forbidden_keys_leak(self) -> None:
        summary = _minimal_summary(
            by_metadata_field={
                "agency": {
                    "num_predictions": 1,
                    "accuracy": 1.0,
                    "case_results": "should_be_dropped",
                    "query": "should_be_dropped",
                    "evidence": "should_be_dropped",
                }
            }
        )
        out = extract_aggregate(summary)

        def _all_keys(d: dict) -> set:
            keys = set(d.keys())
            for v in d.values():
                if isinstance(v, dict):
                    keys |= _all_keys(v)
            return keys

        present = _all_keys(out)
        for forbidden in FORBIDDEN_KEYS:
            self.assertNotIn(
                forbidden,
                present,
                f"Forbidden key '{forbidden}' leaked into aggregate output",
            )


class TestAbstentionCalibrationExtractor(unittest.TestCase):
    def test_dict_with_valid_subkeys_passes_through(self) -> None:
        summary = _minimal_summary(
            abstention_calibration={
                "ece": 0.12,
                "brier": 0.08,
                "n": 30,
                "num_bins": 10,
            }
        )
        out = extract_aggregate(summary)
        self.assertIn("abstention_calibration", out)
        block = out["abstention_calibration"]
        self.assertEqual(block["ece"], 0.12)
        self.assertEqual(block["brier"], 0.08)
        self.assertEqual(block["n"], 30)
        self.assertEqual(block["num_bins"], 10)

    def test_null_round_trips(self) -> None:
        """ADR 0048 forward-compat: when no case carries ``confidence``,
        the block is emitted as ``null`` (not ``{}`` and not omitted).
        The extractor must preserve null so downstream renderers can
        distinguish 'no data' from 'perfect calibration'."""
        summary = _minimal_summary(abstention_calibration=None)
        out = extract_aggregate(summary)
        self.assertIn("abstention_calibration", out)
        self.assertIsNone(out["abstention_calibration"])

    def test_unknown_subkeys_dropped(self) -> None:
        summary = _minimal_summary(
            abstention_calibration={
                "ece": 0.12,
                "brier": 0.08,
                "n": 30,
                "num_bins": 10,
                "confidence_histogram": [0.1, 0.2, 0.7],  # not in whitelist
                "per_case_confidences": "leak_attempt",
            }
        )
        out = extract_aggregate(summary)
        block = out["abstention_calibration"]
        self.assertEqual(set(block.keys()), {"ece", "brier", "n", "num_bins"})

    def test_absent_when_not_in_summary(self) -> None:
        summary = _minimal_summary()
        out = extract_aggregate(summary)
        self.assertNotIn("abstention_calibration", out)


class TestMetadataFieldBucketWhitelistMatchesEnum(unittest.TestCase):
    """Single source of truth: the bucket whitelist must agree with
    ``METADATA_FIELD_KEYS`` in ``eval/scorers/_shared.py``. Drift
    between the two means a new field was added without an extractor
    update (silent drop) or a private field was admitted without
    inventory test update (silent leak)."""

    def test_extractor_whitelist_matches_scorer_enum(self) -> None:
        from eval.scorers._shared import METADATA_FIELD_KEYS

        self.assertEqual(
            SAFE_METADATA_FIELD_BUCKET_KEYS,
            frozenset(METADATA_FIELD_KEYS),
            "Extractor whitelist drifted from METADATA_FIELD_KEYS enum",
        )


class TestCalibrationSubKeyWhitelistMatchesAdr(unittest.TestCase):
    def test_safe_calibration_keys_match_adr_0048(self) -> None:
        self.assertEqual(
            tuple(SAFE_CALIBRATION_KEYS),
            ("ece", "brier", "n", "num_bins"),
        )


if __name__ == "__main__":
    unittest.main()
