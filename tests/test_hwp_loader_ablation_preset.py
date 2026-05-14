"""Regression test for HWP loader 3-way ablation preset (issue #652 / ADR 0039).

Verifies that eval/config.yaml contains the three required ablation rows
(hwp_csv_text / hwp_native / hwp_native_tables) with the expected structure,
and that scripts/build_index.py exposes the --hwp_loader flag.
"""
from __future__ import annotations

import argparse
import ast
import unittest
from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "eval" / "config.yaml"
BUILD_INDEX_PATH = ROOT_DIR / "scripts" / "build_index.py"


class TestHwpAblationRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(CONFIG_PATH) as f:
            cls.config = yaml.safe_load(f)
        cls.ablation_runs: list[dict] = cls.config.get("ablation_runs", [])
        cls.ablation_by_name = {row["name"]: row for row in cls.ablation_runs}
        cls.latency_budgets: dict = cls.config.get("latency_budgets", {})

    def test_three_hwp_rows_exist(self) -> None:
        for name in ("hwp_csv_text", "hwp_native", "hwp_native_tables"):
            self.assertIn(name, self.ablation_by_name, f"Ablation row '{name}' missing")

    def test_all_hwp_rows_use_agentic_full(self) -> None:
        for name in ("hwp_csv_text", "hwp_native", "hwp_native_tables"):
            row = self.ablation_by_name[name]
            self.assertEqual(row.get("pipeline"), "agentic_full", f"{name}: pipeline must be agentic_full")

    def test_hwp_rows_have_loader_key(self) -> None:
        expected = {
            "hwp_csv_text": "csv",
            "hwp_native": "native",
            "hwp_native_tables": "native_tables",
        }
        for name, loader_val in expected.items():
            row = self.ablation_by_name[name]
            self.assertEqual(row.get("hwp_loader"), loader_val, f"{name}: hwp_loader mismatch")

    def test_latency_budgets_present(self) -> None:
        for name in ("hwp_csv_text", "hwp_native", "hwp_native_tables"):
            self.assertIn(name, self.latency_budgets, f"latency_budgets entry for '{name}' missing")
            self.assertIsNotNone(self.latency_budgets[name].get("p95_ms"))

    def test_naive_baseline_unchanged(self) -> None:
        row = self.ablation_by_name.get("naive_baseline", {})
        self.assertEqual(row.get("pipeline"), "naive_baseline")
        self.assertNotIn("hwp_loader", row, "hwp_loader must not appear on naive_baseline row")


class TestBuildIndexHwpLoaderFlag(unittest.TestCase):
    """Verify --hwp_loader flag is wired in scripts/build_index.py."""

    @classmethod
    def setUpClass(cls) -> None:
        with open(BUILD_INDEX_PATH) as f:
            cls.source = f.read()
        cls.tree = ast.parse(cls.source)

    def test_hwp_loader_in_source(self) -> None:
        self.assertIn("hwp_loader", self.source)
        self.assertIn("BIDMATE_HWP_LOADER", self.source)

    def test_choices_are_correct(self) -> None:
        self.assertIn('"csv"', self.source)
        self.assertIn('"native"', self.source)
        self.assertIn('"native_tables"', self.source)


if __name__ == "__main__":
    unittest.main()
