"""Regression tests for eval/judge_agreement.py (issue #169, ADR 0016).

Uses synthetic label fixtures only — no real human labels needed.
Real calibration runs are private (ADR 0005); this test guards the
metric implementation itself.
"""
from __future__ import annotations

import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from eval.judge_agreement import (
    LABELS,
    cohens_kappa,
    compute_agreement,
    confusion_matrix,
    load_labels,
    main,
    spearman_rho,
)


class CohensKappaTest(unittest.TestCase):
    def test_perfect_agreement_yields_kappa_one(self) -> None:
        labels = list(LABELS) * 5
        self.assertEqual(1.0, cohens_kappa(labels, labels))

    def test_disjoint_extreme_marginals_yield_zero(self) -> None:
        # All judge=supported, all human=insufficient. Both marginals
        # point at separate cells, expected = 0, kappa = 0.
        judge = ["supported"] * 10
        human = ["insufficient"] * 10
        self.assertEqual(0.0, cohens_kappa(judge, human))

    def test_systematic_inversion_yields_negative_kappa(self) -> None:
        # Symmetric inversion → expected = 0.5, observed = 0 → kappa = -1.
        judge = ["supported", "supported", "insufficient", "insufficient"]
        human = ["insufficient", "insufficient", "supported", "supported"]
        self.assertAlmostEqual(-1.0, cohens_kappa(judge, human), places=6)

    def test_empty_returns_nan(self) -> None:
        self.assertTrue(math.isnan(cohens_kappa([], [])))

    def test_mismatched_lengths_raise(self) -> None:
        with self.assertRaises(ValueError):
            cohens_kappa(["supported"], [])


class SpearmanRhoTest(unittest.TestCase):
    def test_perfect_monotone_agreement_rho_one(self) -> None:
        judge = ["supported", "partial", "insufficient"] * 4
        human = list(judge)
        self.assertAlmostEqual(1.0, spearman_rho(judge, human), places=6)

    def test_perfect_inversion_rho_minus_one(self) -> None:
        judge = ["supported", "partial", "insufficient"] * 4
        human = ["insufficient", "partial", "supported"] * 4
        self.assertAlmostEqual(-1.0, spearman_rho(judge, human), places=6)

    def test_nan_below_minimum_n_or_zero_variance(self) -> None:
        # n=0, n=1, and a single-label sequence all hit the NaN guard.
        self.assertTrue(math.isnan(spearman_rho([], [])))
        self.assertTrue(math.isnan(spearman_rho(["supported"], ["partial"])))
        self.assertTrue(
            math.isnan(spearman_rho(["supported"] * 5, ["supported"] * 5))
        )


class ConfusionMatrixTest(unittest.TestCase):
    def test_diagonal_dominates_on_perfect_agreement(self) -> None:
        judge = ["supported", "partial", "insufficient", "supported"]
        human = list(judge)
        matrix = confusion_matrix(judge, human)
        self.assertEqual(2, matrix["supported"]["supported"])
        self.assertEqual(1, matrix["partial"]["partial"])
        self.assertEqual(1, matrix["insufficient"]["insufficient"])
        # Off-diagonal stays zero.
        self.assertEqual(0, matrix["supported"]["partial"])
        self.assertEqual(0, matrix["partial"]["insufficient"])

    def test_disagreement_lands_off_diagonal(self) -> None:
        judge = ["supported", "insufficient"]
        human = ["partial", "supported"]
        matrix = confusion_matrix(judge, human)
        self.assertEqual(1, matrix["partial"]["supported"])
        self.assertEqual(1, matrix["supported"]["insufficient"])


class ComputeAgreementTest(unittest.TestCase):
    def test_passing_run_marks_passes_true(self) -> None:
        rows = [
            ("c-1", "supported", "supported"),
            ("c-2", "partial", "partial"),
            ("c-3", "insufficient", "insufficient"),
            ("c-4", "supported", "supported"),
        ]
        report = compute_agreement(rows, threshold=0.6)
        self.assertEqual(4, report["n"])
        self.assertEqual(1.0, report["cohens_kappa"])
        self.assertTrue(report["passes"])

    def test_below_threshold_run_marks_passes_false(self) -> None:
        rows = [
            ("c-1", "supported", "supported"),
            ("c-2", "supported", "partial"),
            ("c-3", "supported", "insufficient"),
            ("c-4", "partial", "supported"),
            ("c-5", "insufficient", "partial"),
        ]
        report = compute_agreement(rows, threshold=0.6)
        self.assertFalse(report["passes"])

    def test_empty_input_does_not_pass(self) -> None:
        # No labeled rows → NaN kappa → passes=False even at the most
        # permissive threshold. Guards against silently green pipelines
        # when the labels file is empty.
        report = compute_agreement([], threshold=0.0)
        self.assertEqual(0, report["n"])
        self.assertTrue(math.isnan(report["cohens_kappa"]))
        self.assertFalse(report["passes"])


class LoadLabelsTest(unittest.TestCase):
    def _write(self, tmp: str, body: str) -> Path:
        path = Path(tmp) / "labels.csv"
        path.write_text(body, encoding="utf-8")
        return path

    def test_round_trip_csv(self) -> None:
        with TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "case_id,judge_status,human_status\n"
                "c-1,supported,supported\n"
                "c-2,partial,insufficient\n",
            )
            rows = load_labels(path)
            self.assertEqual(
                [
                    ("c-1", "supported", "supported"),
                    ("c-2", "partial", "insufficient"),
                ],
                rows,
            )

    def test_blank_case_id_is_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "case_id,judge_status,human_status\n"
                "c-1,supported,supported\n"
                ",supported,supported\n",  # blank trailing row
            )
            rows = load_labels(path)
            self.assertEqual(1, len(rows))

    def test_invalid_label_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "case_id,judge_status,human_status\n" "c-1,bogus,supported\n",
            )
            with self.assertRaises(ValueError):
                load_labels(path)

    def test_missing_required_column_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            path = self._write(
                tmp, "case_id,judge_status\n" "c-1,supported\n"
            )
            with self.assertRaises(ValueError):
                load_labels(path)

    def test_case_normalised_to_lower(self) -> None:
        with TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "case_id,judge_status,human_status\n"
                "c-1,Supported,SUPPORTED\n",
            )
            self.assertEqual(
                [("c-1", "supported", "supported")], load_labels(path)
            )


class CliExitCodeTest(unittest.TestCase):
    def _run(self, csv_body: str, *, threshold: str = "0.6") -> int:
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "labels.csv"
            csv_path.write_text(csv_body, encoding="utf-8")
            return main(
                ["--input", str(csv_path), "--threshold", threshold, "--json"]
            )

    def test_pass_returns_zero(self) -> None:
        body = (
            "case_id,judge_status,human_status\n"
            "c-1,supported,supported\n"
            "c-2,partial,partial\n"
            "c-3,insufficient,insufficient\n"
            "c-4,supported,supported\n"
        )
        self.assertEqual(0, self._run(body, threshold="0.6"))

    def test_below_threshold_returns_one(self) -> None:
        body = (
            "case_id,judge_status,human_status\n"
            "c-1,supported,insufficient\n"
            "c-2,supported,insufficient\n"
            "c-3,partial,supported\n"
        )
        self.assertEqual(1, self._run(body, threshold="0.6"))


if __name__ == "__main__":
    unittest.main()
