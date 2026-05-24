"""Regression tests for the ``full_dense`` control row (issue #1285).

Commit 6c1c414 (#1000, ADR 0058 Scenario A) flipped the ``agentic_full``
preset ``retrieval_backend`` from ``dense`` to ``hybrid``.  The eval ``full``
row originally inherited that default, so the flip silently moved the eval
``full`` row (and full_llm / no_rerank / retrieval_only / no_metadata_first)
dense -> hybrid, collapsing the dense agentic_full arm that ADR 0058's own win
evidence (dense_m3 vs hybrid_bm25_k60_m3, all SIG) requires for reproducibility.

Direction B (issue #1285): keep ``full`` hybrid (canonical headline reflects
the production default) and add an explicit ``full_dense`` control row so the
dense-vs-hybrid comparison is reproducible from the default config.

ADR 0074 then tightened the contract: claim-bearing eval rows must declare the
stage-separation knobs directly instead of relying on preset inheritance.

These tests pin the resolved retrieval backend through the runner's own
``normalize_run_config`` contract (which calls ``resolve_pipeline_config``),
so the assertions match what the eval runner actually executes:

1.  ``full_dense`` row exists.
2.  ``full`` resolves to hybrid (ADR 0058 Scenario A on the headline row).
3.  ``full_dense`` resolves to dense (the restored control arm).
4.  ``naive_baseline`` resolves to dense (ADR 0001 byte-identity sentinel).
5.  ``full`` and ``full_dense`` differ by exactly ``{name, retrieval_backend}``
    (the control row varies exactly one knob).
6.  Every eval row explicitly declares the core stage-separation knobs.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from eval.run_eval import normalize_run_config


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "eval" / "config.yaml"

EXPLICIT_STAGE_KNOBS = {
    "metadata_first",
    "rerank",
    "verifier_retry",
    "retrieval_mode",
    "retrieval_backend",
    "query_expansion",
}


class TestFullDenseControlRow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(CONFIG_PATH) as f:
            cls.config = yaml.safe_load(f)
        cls.ablation_runs: list[dict] = cls.config.get("ablation_runs", [])
        cls.ablation_by_name = {row["name"]: row for row in cls.ablation_runs}

    def test_full_dense_row_exists(self) -> None:
        self.assertIn(
            "full_dense",
            self.ablation_by_name,
            "Ablation row 'full_dense' missing from eval/config.yaml. It is the "
            "dense control arm restoring ADR 0058 dense-vs-hybrid reproducibility "
            "after the #1000 hybrid flip (issue #1285).",
        )

    def test_full_resolves_to_hybrid(self) -> None:
        """ADR 0058 Scenario A: the headline ``full`` row reflects the
        production default (hybrid)."""
        resolved = normalize_run_config(self.ablation_by_name["full"])
        self.assertEqual(
            resolved["retrieval_backend"],
            "hybrid",
            "full must resolve to 'hybrid' (ADR 0058 Scenario A, #1000). "
            "It is explicit in eval/config.yaml per ADR 0074.",
        )

    def test_full_dense_resolves_to_dense(self) -> None:
        """The control arm pins dense explicitly so the preset default flip
        cannot move it."""
        resolved = normalize_run_config(self.ablation_by_name["full_dense"])
        self.assertEqual(
            resolved["retrieval_backend"],
            "dense",
            "full_dense must resolve to 'dense' — it is the explicit dense "
            "control arm for ADR 0058 reproducibility (issue #1285).",
        )

    def test_naive_baseline_stays_dense(self) -> None:
        """ADR 0001 byte-identity sentinel: the naive baseline must never
        move off dense, regardless of preset-default flips."""
        resolved = normalize_run_config(self.ablation_by_name["naive_baseline"])
        self.assertEqual(
            resolved["retrieval_backend"],
            "dense",
            "naive_baseline must resolve to 'dense' (ADR 0001 byte-identity). "
            "If this fails, a preset-default change leaked into the baseline.",
        )

    def test_full_dense_differs_from_full_by_exactly_backend(self) -> None:
        """The control row must vary exactly one knob vs ``full``: the
        retrieval backend.  Pins that full_dense is a clean single-axis
        ablation and not a silent alias (cf. #800 / #804 traps)."""
        full = {k: v for k, v in self.ablation_by_name["full"].items()}
        full_dense = {k: v for k, v in self.ablation_by_name["full_dense"].items()}
        differing = {
            k
            for k in full.keys() | full_dense.keys()
            if full.get(k) != full_dense.get(k)
        }
        self.assertEqual(
            differing,
            {"name", "retrieval_backend"},
            "full and full_dense must differ by exactly {name, retrieval_backend}. "
            f"Got differing keys: {differing}. The control row should be identical "
            "to full except for the explicit dense backend.",
        )

    def test_all_rows_declare_stage_separation_knobs(self) -> None:
        """ADR 0074: eval rows must be readable without following preset
        defaults for the core retrieval/answer-stage switches."""
        for row in self.ablation_runs:
            with self.subTest(row=row["name"]):
                missing = sorted(EXPLICIT_STAGE_KNOBS - row.keys())
                self.assertEqual(
                    missing,
                    [],
                    f"{row['name']} must explicitly declare ADR 0074 stage knobs",
                )


if __name__ == "__main__":
    unittest.main()
