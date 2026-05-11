"""Smoke test for the chunking strategy ablation runner (issue #62).

Just runs the script's main code paths against `data/raw/` and checks
the report shape — every probe returns a verdict per strategy and the
strategy comparison table includes all three strategies. The script is
a measurement tool that reviewers run by hand; this guard catches
breakage in the helper functions or fixture compatibility regression.
"""

import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_chunking_ablation import (  # noqa: E402
    PROBE_CASES,
    STRATEGIES,
    run_for_strategy,
)


class ChunkingAblationRunnerTest(unittest.TestCase):
    def test_each_strategy_returns_full_probe_set(self) -> None:
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                report = run_for_strategy(strategy)
                self.assertEqual(report["strategy"], strategy)
                self.assertGreater(report["total_chunks"], 0)
                self.assertEqual(
                    len(report["probe_results"]), len(PROBE_CASES)
                )
                for probe_result in report["probe_results"]:
                    # Every probe must return a verdict — the script
                    # is the diagnostic tool reviewers consult.
                    self.assertIn("correct", probe_result)
                    self.assertIn("top_score", probe_result)
                    self.assertIn("chunk_seq", probe_result)
                    self.assertIn("total_chunks", probe_result)

    def test_chunk_counts_differ_between_strategies(self) -> None:
        # The whole point of running the ablation is that strategies
        # produce different chunk counts. If they ever match, either
        # the docs are too short (single chunk regardless) or the
        # chunker has been broken.
        counts = {
            strategy: run_for_strategy(strategy)["total_chunks"]
            for strategy in STRATEGIES
        }
        # fixed almost always produces fewer chunks than section/auto
        # for multi-section docs.
        self.assertLess(
            counts["fixed"],
            counts["section"],
            f"chunk counts unexpectedly match: {counts}",
        )

    def test_probe_cases_resolve_to_probe_doc(self) -> None:
        # Every probe targets the spectrometer probe doc by design.
        # Confirm at least one strategy gets the correct doc — if all
        # strategies fail, the chunker or the fixture has rotted.
        anyone_passes = False
        for strategy in STRATEGIES:
            for probe_result in run_for_strategy(strategy)["probe_results"]:
                if probe_result["correct"]:
                    anyone_passes = True
                    break
            if anyone_passes:
                break
        self.assertTrue(
            anyone_passes,
            "no strategy got any probe correct — fixture or chunker broken",
        )


if __name__ == "__main__":
    unittest.main()
