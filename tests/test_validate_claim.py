"""Tests for scripts/validate_claim.py — ADR 0055 PR-body claim sanity gate.

Six cases cover the four failure conditions + happy path + multi-claim.
Uses synthetic case_results with deterministic Bernoulli arrays so paired_bootstrap_ci
results are predictable.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_claim import main, parse_claims, validate_one_claim  # noqa: E402


def _make_case_results(values_by_metric: dict[str, list[float | None]]) -> list[dict]:
    """Build case_results-shape list of dicts. case_id = real_<idx>."""
    metrics = list(values_by_metric.keys())
    n = len(next(iter(values_by_metric.values())))
    rows = []
    for i in range(n):
        row: dict = {"case_id": f"real_{i:04d}"}
        for m in metrics:
            row[m] = values_by_metric[m][i]
        rows.append(row)
    return rows


def _write_summary(tmp: Path, name: str, case_results: list[dict]) -> Path:
    path = tmp / name
    path.write_text(json.dumps({"case_results": case_results}), encoding="utf-8")
    return path


def _write_pr_body(tmp: Path, body: str) -> Path:
    path = tmp / "pr_body.txt"
    path.write_text(body, encoding="utf-8")
    return path


class TestParseClaims(unittest.TestCase):
    def test_extracts_simple_claim(self):
        body = "## Summary\nClaim: accuracy=+4.0pp\n"
        claims = parse_claims(body)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["metric"], "accuracy")
        self.assertEqual(claims[0]["sign"], "+")
        self.assertEqual(claims[0]["value"], 4.0)

    def test_skips_claim_inside_code_fence(self):
        body = "```\nClaim: accuracy=+4.0pp\n```\nClaim: groundedness=-2.5pp\n"
        claims = parse_claims(body)
        # Only the un-fenced one survives.
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["metric"], "groundedness")
        self.assertEqual(claims[0]["sign"], "-")

    def test_multi_claim_extraction(self):
        body = "Claim: accuracy=+4.0pp\nClaim: groundedness=+2.5pp\nClaim: citation_precision=-1.0pp\n"
        claims = parse_claims(body)
        self.assertEqual(len(claims), 3)
        self.assertEqual([c["metric"] for c in claims], ["accuracy", "groundedness", "citation_precision"])


class TestHappyPath(unittest.TestCase):
    """Case 1: claim aligns with mean_diff and CI excludes 0 → PASS."""

    def test_pass_when_claim_within_ci(self):
        # baseline ~ 0.0 mean, candidate ~ 0.05 mean → +5pp shift, large n, tight CI.
        baseline_vals = [0.0] * 200 + [1.0] * 50  # 250 cases, mean=0.20
        candidate_vals = [0.0] * 150 + [1.0] * 100  # mean=0.40 → +20pp
        baseline_cr = _make_case_results({"accuracy": baseline_vals})
        candidate_cr = _make_case_results({"accuracy": candidate_vals})
        claim = {"metric": "accuracy", "sign": "+", "value": 15.0, "line_no": 1}  # claim +15pp, observed +20pp
        passed, msg = validate_one_claim(claim, baseline_cr, candidate_cr, min_sample=200, alpha=0.05)
        self.assertTrue(passed, msg=msg)
        self.assertIn("PASS", msg)


class TestCICrossesZero(unittest.TestCase):
    """Case 2: CI crosses 0 → FAIL."""

    def test_fail_when_ci_crosses_zero(self):
        # baseline and candidate have same mean (0.5) → CI centered on 0.
        baseline_vals = [0.0, 1.0] * 125  # 250 cases, mean=0.5
        candidate_vals = [1.0, 0.0] * 125  # mean=0.5 (just permuted, paired diffs alternate ±1)
        baseline_cr = _make_case_results({"accuracy": baseline_vals})
        candidate_cr = _make_case_results({"accuracy": candidate_vals})
        claim = {"metric": "accuracy", "sign": "+", "value": 1.0, "line_no": 1}
        passed, msg = validate_one_claim(claim, baseline_cr, candidate_cr, min_sample=200, alpha=0.05)
        self.assertFalse(passed)
        self.assertIn("crosses 0", msg)


class TestSampleSizeShortfall(unittest.TestCase):
    """Case 3: effective n < min_sample → FAIL."""

    def test_fail_when_sample_too_small(self):
        baseline_vals = [0.0] * 100  # only 100 cases
        candidate_vals = [1.0] * 100
        baseline_cr = _make_case_results({"accuracy": baseline_vals})
        candidate_cr = _make_case_results({"accuracy": candidate_vals})
        claim = {"metric": "accuracy", "sign": "+", "value": 50.0, "line_no": 1}
        passed, msg = validate_one_claim(claim, baseline_cr, candidate_cr, min_sample=200, alpha=0.05)
        self.assertFalse(passed)
        self.assertIn("min_sample=200", msg)


class TestSignMismatch(unittest.TestCase):
    """Case 4: claim says + but observed mean_diff is − → FAIL."""

    def test_fail_when_sign_mismatch(self):
        baseline_vals = [1.0] * 200 + [0.0] * 50  # mean=0.8
        candidate_vals = [0.0] * 200 + [1.0] * 50  # mean=0.2 → −60pp
        baseline_cr = _make_case_results({"accuracy": baseline_vals})
        candidate_cr = _make_case_results({"accuracy": candidate_vals})
        claim = {"metric": "accuracy", "sign": "+", "value": 5.0, "line_no": 1}  # claim positive, observed negative
        passed, msg = validate_one_claim(claim, baseline_cr, candidate_cr, min_sample=200, alpha=0.05)
        self.assertFalse(passed)
        self.assertIn("Direction mismatch", msg)


class TestOverClaim(unittest.TestCase):
    """Case 5: |claim| > |upper CI edge| → FAIL."""

    def test_fail_when_overclaim(self):
        # +5pp observed, tight CI ~ (3pp, 7pp). Claim +20pp exceeds upper edge.
        baseline_vals = [0.0] * 200 + [1.0] * 50  # 250 cases, mean=0.20
        candidate_vals = [0.0] * 187 + [1.0] * 63  # mean=0.252 → +5.2pp
        baseline_cr = _make_case_results({"accuracy": baseline_vals})
        candidate_cr = _make_case_results({"accuracy": candidate_vals})
        claim = {"metric": "accuracy", "sign": "+", "value": 20.0, "line_no": 1}
        passed, msg = validate_one_claim(claim, baseline_cr, candidate_cr, min_sample=200, alpha=0.05)
        self.assertFalse(passed)
        self.assertIn("exceeds optimistic CI edge", msg)


class TestADR0054NoneSemanticsHandled(unittest.TestCase):
    """ADR 0054 substantive-only semantics: None pairs are dropped before
    paired_bootstrap_ci. Ensure effective_n reflects post-drop count."""

    def test_none_pairs_dropped(self):
        # 200 substantive + 100 None pairs (refusal cases).
        baseline_vals = [0.0] * 150 + [1.0] * 50 + [None] * 100
        candidate_vals = [0.0] * 100 + [1.0] * 100 + [None] * 100
        baseline_cr = _make_case_results({"accuracy": baseline_vals})
        candidate_cr = _make_case_results({"accuracy": candidate_vals})
        # Sample 200 substantive cases — exactly at min_sample.
        claim = {"metric": "accuracy", "sign": "+", "value": 15.0, "line_no": 1}
        passed, msg = validate_one_claim(claim, baseline_cr, candidate_cr, min_sample=200, alpha=0.05)
        # Should pass — 200 effective cases, +25pp observed.
        self.assertTrue(passed, msg=msg)
        self.assertIn("n=200", msg)


class TestEndToEndCLI(unittest.TestCase):
    """Case 6: multi-claim PR body via main() — 1 PASS + 1 FAIL → exit 1."""

    def test_main_exits_nonzero_when_any_claim_fails(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            baseline_cr = _make_case_results(
                {
                    "accuracy": [0.0] * 200 + [1.0] * 50,  # mean=0.20
                    "groundedness": [1.0] * 200 + [0.0] * 50,  # mean=0.80
                }
            )
            candidate_cr = _make_case_results(
                {
                    "accuracy": [0.0] * 150 + [1.0] * 100,  # mean=0.40 → +20pp
                    "groundedness": [1.0] * 200 + [0.0] * 50,  # mean=0.80 (no change → CI crosses 0)
                }
            )
            base_path = _write_summary(tmp, "base.json", baseline_cr)
            cand_path = _write_summary(tmp, "cand.json", candidate_cr)
            pr_body_path = _write_pr_body(
                tmp,
                "## Summary\n\n"
                "Claim: accuracy=+15.0pp\n"
                "Claim: groundedness=+5.0pp\n",
            )
            exit_code = main(
                [
                    "--pr-body",
                    str(pr_body_path),
                    "--baseline",
                    str(base_path),
                    "--candidate",
                    str(cand_path),
                    "--min-sample",
                    "200",
                ]
            )
            self.assertEqual(exit_code, 1, "one of two claims must fail (groundedness)")

    def test_main_exits_zero_when_no_claims(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            baseline_cr = _make_case_results({"accuracy": [0.0] * 100})
            candidate_cr = _make_case_results({"accuracy": [0.0] * 100})
            base_path = _write_summary(tmp, "base.json", baseline_cr)
            cand_path = _write_summary(tmp, "cand.json", candidate_cr)
            pr_body_path = _write_pr_body(tmp, "## Summary\nno claims here\n")
            exit_code = main(
                [
                    "--pr-body",
                    str(pr_body_path),
                    "--baseline",
                    str(base_path),
                    "--candidate",
                    str(cand_path),
                ]
            )
            self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
