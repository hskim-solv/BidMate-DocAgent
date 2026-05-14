"""Regression test for retrieval_only ablation preset (issue #694).

Verifies that eval/config.yaml contains the ``retrieval_only`` row with the
expected config (full retrieval stack, verifier_retry=False) and that the
ADR 0001 invariants are preserved (naive_baseline unchanged,
no_verifier_retry not removed).
"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "eval" / "config.yaml"


class TestRetrievalOnlyAblationRow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(CONFIG_PATH) as f:
            cls.config = yaml.safe_load(f)
        cls.ablation_runs: list[dict] = cls.config.get("ablation_runs", [])
        cls.ablation_by_name = {row["name"]: row for row in cls.ablation_runs}

    def test_retrieval_only_row_exists(self) -> None:
        self.assertIn(
            "retrieval_only",
            self.ablation_by_name,
            "Ablation row 'retrieval_only' missing from eval/config.yaml",
        )

    def test_retrieval_only_uses_agentic_full(self) -> None:
        row = self.ablation_by_name["retrieval_only"]
        self.assertEqual(
            row.get("pipeline"),
            "agentic_full",
            "retrieval_only: pipeline must be agentic_full (full retrieval stack)",
        )

    def test_retrieval_only_verifier_retry_false(self) -> None:
        """verifier_retry=False so first-pass chunk ranking is measured without retry."""
        row = self.ablation_by_name["retrieval_only"]
        self.assertFalse(
            row.get("verifier_retry", True),
            "retrieval_only: verifier_retry must be False",
        )

    def test_retrieval_only_metadata_first_and_rerank(self) -> None:
        """Full retrieval stack — metadata_first and rerank must be True."""
        row = self.ablation_by_name["retrieval_only"]
        self.assertTrue(
            row.get("metadata_first", True),
            "retrieval_only: metadata_first must be True (full retrieval stack)",
        )
        self.assertTrue(
            row.get("rerank", True),
            "retrieval_only: rerank must be True (full retrieval stack)",
        )

    def test_retrieval_only_flat_retrieval_mode(self) -> None:
        row = self.ablation_by_name["retrieval_only"]
        mode = row.get("retrieval_mode", "flat")
        self.assertEqual(mode, "flat", "retrieval_only: retrieval_mode must be flat")

    # ADR 0001 invariant: naive_baseline preserved and no_verifier_retry not removed.

    def test_naive_baseline_preserved(self) -> None:
        row = self.ablation_by_name.get("naive_baseline", {})
        self.assertEqual(
            row.get("pipeline"),
            "naive_baseline",
            "ADR 0001: naive_baseline row must remain with pipeline=naive_baseline",
        )

    def test_no_verifier_retry_still_present(self) -> None:
        """retrieval_only is additive; no_verifier_retry must NOT be removed."""
        self.assertIn(
            "no_verifier_retry",
            self.ablation_by_name,
            "no_verifier_retry must remain — it is the verifier-retry-contribution ablation reference",
        )

    def test_retrieval_only_is_distinct_named_slot(self) -> None:
        """Ablation run names must be unique (run_eval.py enforces at runtime)."""
        names = [row["name"] for row in self.ablation_runs]
        self.assertEqual(
            len(names),
            len(set(names)),
            "Duplicate ablation run names found in eval/config.yaml",
        )


if __name__ == "__main__":
    unittest.main()
