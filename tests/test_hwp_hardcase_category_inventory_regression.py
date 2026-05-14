"""Regression test: all four ADR 0039 HWP structural hardcase categories are
present in at least one public eval case (issue #654).

Categories: table_heavy / ocr_noisy / rotated_or_skewed / layout_broken.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "eval" / "config.yaml"

ADR_0039_CATEGORIES = frozenset(
    {"table_heavy", "ocr_noisy", "rotated_or_skewed", "layout_broken"}
)


class TestAdr0039CategoryInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
        cls.cases: list[dict] = cfg.get("cases", [])

    def _all_categories(self) -> set[str]:
        found: set[str] = set()
        for case in self.cases:
            cats = case.get("hardcase_categories") or []
            found.update(cats)
        return found

    def test_all_four_adr0039_categories_present(self) -> None:
        found = self._all_categories()
        missing = ADR_0039_CATEGORIES - found
        self.assertFalse(
            missing,
            f"ADR 0039 categories missing from eval cases: {sorted(missing)}",
        )

    def test_table_heavy_has_hwp_cases(self) -> None:
        tagged = [c for c in self.cases if "table_heavy" in (c.get("hardcase_categories") or [])]
        hwp = [c for c in tagged if any("hwp" in d for d in (c.get("expected_doc_ids") or []))]
        self.assertGreater(len(hwp), 0, "table_heavy category has no HWP fixture cases")

    def test_layout_broken_has_hwp_cases(self) -> None:
        tagged = [c for c in self.cases if "layout_broken" in (c.get("hardcase_categories") or [])]
        hwp = [c for c in tagged if any("hwp" in d for d in (c.get("expected_doc_ids") or []))]
        self.assertGreater(len(hwp), 0, "layout_broken category has no HWP fixture cases")

    def test_no_regression_in_existing_categories(self) -> None:
        found = self._all_categories()
        pre_existing = {"retrieval_hardening", "ambiguous_follow_up", "chunk_boundary"}
        for cat in pre_existing:
            self.assertIn(cat, found, f"Pre-existing category '{cat}' disappeared")


if __name__ == "__main__":
    unittest.main()
