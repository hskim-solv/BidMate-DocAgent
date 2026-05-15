"""Regression test for retrieval_only ablation preset (issues #694, #800).

Verifies that eval/config.yaml contains the ``retrieval_only`` row with the
expected config (raw retrieval ablation: rerank=False + verifier_retry=False)
and that the ADR 0001 invariants are preserved (naive_baseline unchanged,
no_verifier_retry not removed).

Additionally enforces the differentiation invariant from issue #800:
``retrieval_only`` and ``no_verifier_retry`` must NOT be byte-identical
configs (name aside).  The original #694 definition violated this, which is
why the row was re-defined to ``rerank=false``.
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

    def test_retrieval_only_metadata_first_true(self) -> None:
        """metadata_first stays True — retrieval_only measures the post-prefilter stack."""
        row = self.ablation_by_name["retrieval_only"]
        self.assertTrue(
            row.get("metadata_first", True),
            "retrieval_only: metadata_first must be True",
        )

    def test_retrieval_only_rerank_false(self) -> None:
        """Issue #800: rerank=False (raw retrieval, no cross-encoder rerank).

        Differentiates retrieval_only from no_verifier_retry (which has
        rerank=True).  Previously rerank=True, which made the two rows
        byte-identical — see issue #800 for the redefinition rationale.
        """
        row = self.ablation_by_name["retrieval_only"]
        self.assertFalse(
            row.get("rerank", True),
            "retrieval_only: rerank must be False (raw retrieval ablation, issue #800)",
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

    def test_retrieval_only_differs_from_no_verifier_retry(self) -> None:
        """Issue #800 invariant: retrieval_only and no_verifier_retry must NOT
        be byte-identical (name aside).

        The original PR #694 definition violated this — both rows had
        identical pipeline/metadata_first/rerank/verifier_retry/retrieval_mode,
        so ablation runner produced identical leaderboard values for two
        named columns.  This invariant prevents the regression.
        """
        retrieval_only = self.ablation_by_name["retrieval_only"]
        no_verifier_retry = self.ablation_by_name["no_verifier_retry"]
        ro_minus_name = {k: v for k, v in retrieval_only.items() if k != "name"}
        nvr_minus_name = {k: v for k, v in no_verifier_retry.items() if k != "name"}
        self.assertNotEqual(
            ro_minus_name,
            nvr_minus_name,
            "retrieval_only and no_verifier_retry are byte-identical (issue #800). "
            "If you intended retrieval_only to be an alias, delete the duplicate row; "
            "otherwise differentiate at least one config bit.",
        )


if __name__ == "__main__":
    unittest.main()
