"""Regression tests for by_hardcase_category aggregate (issue #845 / ADR 0039).

Companion to test_eval_by_format_aggregate_regression.py — same fail-closed
contract, different bucket dimension. Verifies that:

1. ``extract_aggregate`` in ``scripts/run_real_eval_delta`` retains buckets
   whose name is in :data:`SAFE_HARDCASE_CATEGORY_BUCKET_KEYS` (the public
   ADR 0039 4-category enum).
2. Unknown bucket names — including the private 5-slice category names from
   ``docs/real-data/private-hardcase-benchmark.md`` (``scanned_pdf``,
   ``mixed_layout``, ``noisy_ocr``) — are silently dropped (fail-closed),
   so a misconfigured local-only ``real_config.local.yaml`` cannot leak
   the private taxonomy through the ADR 0005 commit boundary.
3. No per-case payload (``FORBIDDEN_KEYS``) appears in the by_hardcase_category
   output.
4. The bucket key set agrees with the inventory regression in
   ``test_hwp_hardcase_category_inventory_regression.py`` (single source of
   truth for the public 4-category enum).
"""
from __future__ import annotations

import unittest
from typing import Any

from scripts.run_real_eval_delta import (
    FORBIDDEN_KEYS,
    SAFE_HARDCASE_CATEGORY_BUCKET_KEYS,
    extract_aggregate,
)


class TestExtractAggregateByHardcaseCategory(unittest.TestCase):
    def _minimal_summary(self, by_hardcase_category: dict[str, Any]) -> dict[str, Any]:
        return {
            "num_predictions": 3,
            "accuracy": 1.0,
            "groundedness": 1.0,
            "citation_precision": 1.0,
            "citation_grounding": None,
            "claim_citation_alignment": None,
            "answer_format_compliance": 1.0,
            "abstention": None,
            "retry": 0.0,
            "by_hardcase_category": by_hardcase_category,
        }

    def test_allowed_buckets_pass_through(self) -> None:
        summary = self._minimal_summary(
            {
                "table_heavy": {"num_predictions": 5, "accuracy": 0.6},
                "ocr_noisy": {"num_predictions": 2, "accuracy": 0.5},
                "rotated_or_skewed": {"num_predictions": 1, "accuracy": 1.0},
                "layout_broken": {"num_predictions": 3, "accuracy": 0.33},
            }
        )
        out = extract_aggregate(summary)
        self.assertIn("by_hardcase_category", out)
        buckets = out["by_hardcase_category"]
        self.assertIn("table_heavy", buckets)
        self.assertIn("ocr_noisy", buckets)
        self.assertIn("rotated_or_skewed", buckets)
        self.assertIn("layout_broken", buckets)
        self.assertEqual(buckets["table_heavy"]["num_predictions"], 5)
        self.assertEqual(buckets["layout_broken"]["accuracy"], 0.33)

    def test_private_5_slice_names_dropped_fail_closed(self) -> None:
        """Private taxonomy names from docs/real-data/private-hardcase-benchmark.md
        must never cross the commit boundary, even if a local-only
        real_config.local.yaml uses them by mistake."""
        summary = self._minimal_summary(
            {
                "table_heavy": {"num_predictions": 1, "accuracy": 1.0},
                "scanned_pdf": {"num_predictions": 99, "accuracy": 0.0},
                "mixed_layout": {"num_predictions": 99, "accuracy": 0.0},
                "noisy_ocr": {"num_predictions": 99, "accuracy": 0.0},
            }
        )
        out = extract_aggregate(summary)
        buckets = out.get("by_hardcase_category", {})
        self.assertIn("table_heavy", buckets)
        self.assertNotIn("scanned_pdf", buckets)
        self.assertNotIn("mixed_layout", buckets)
        self.assertNotIn("noisy_ocr", buckets)

    def test_unknown_arbitrary_bucket_dropped(self) -> None:
        summary = self._minimal_summary(
            {
                "table_heavy": {"num_predictions": 1, "accuracy": 1.0},
                "secret_category": {"num_predictions": 99, "accuracy": 0.0},
            }
        )
        out = extract_aggregate(summary)
        self.assertNotIn("secret_category", out.get("by_hardcase_category", {}))

    def test_absent_when_no_buckets(self) -> None:
        """When no case is tagged with a hardcase_category, run_eval omits the
        ``by_hardcase_category`` key entirely (run_eval.py:677-685 only assigns
        when ``hardcase_grouped`` is non-empty). The extractor must mirror that:
        no empty dict in the committable aggregate."""
        summary = {
            "num_predictions": 3,
            "accuracy": 1.0,
        }
        out = extract_aggregate(summary)
        self.assertNotIn("by_hardcase_category", out)

    def test_no_forbidden_keys_in_output(self) -> None:
        summary = self._minimal_summary(
            {
                "table_heavy": {
                    "num_predictions": 1,
                    "accuracy": 1.0,
                    "case_results": "should_be_dropped",
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

    def test_safe_hardcase_category_bucket_keys_match_adr_0039(self) -> None:
        """Single source of truth: the bucket whitelist here must agree with
        ``ADR_0039_CATEGORIES`` in
        ``tests/test_hwp_hardcase_category_inventory_regression.py``. Drift
        between the two means either a new public category was added without
        an extractor update (silent drop) or a private category was promoted
        without an inventory test update (silent leak)."""
        from tests.test_hwp_hardcase_category_inventory_regression import (
            ADR_0039_CATEGORIES,
        )

        self.assertEqual(
            SAFE_HARDCASE_CATEGORY_BUCKET_KEYS,
            ADR_0039_CATEGORIES,
            "Extractor whitelist drifted from ADR 0039 4-category enum",
        )


if __name__ == "__main__":
    unittest.main()
