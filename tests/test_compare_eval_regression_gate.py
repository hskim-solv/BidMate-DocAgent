"""Regression gate contract for the PR eval workflow.

Locks the semantics of ``scripts/_eval_delta.detect_regressions`` and
the ``scripts/compare_eval.py`` CLI gate so the workflow can rely on
deterministic exit codes and a stable comment shape.

What the gate must do:

* Fail (exit 1) when any *gated* quality metric drops by more than
  the threshold.
* Skip latency metrics — host variance on CI runners would produce
  noisy failures unrelated to pipeline quality.
* Honor ``--allow-regression`` (or env ``ALLOW_REGRESSION=true``):
  surface the regression in the comment but exit 0.
* Pass quietly when deltas are within threshold.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _eval_delta import detect_regressions  # noqa: E402


def _base_summary() -> dict:
    return {
        "pipeline": "agentic_full",
        "primary_run": "full",
        "num_predictions": 42,
        "accuracy": 0.90,
        "groundedness": 0.93,
        "citation_precision": 0.90,
        "citation_grounding": 0.88,
        "claim_citation_alignment": 0.85,
        "answer_format_compliance": 1.00,
        "abstention": 0.95,
        "retry": 0.20,
        "latency": {"p50": 200.0, "p95": 800.0},
    }


class DetectRegressionsTest(unittest.TestCase):
    def test_empty_when_no_movement(self) -> None:
        base = _base_summary()
        head = dict(base)
        self.assertEqual(detect_regressions(base, head, threshold=0.05), [])

    def test_quality_drop_beyond_threshold_is_regression(self) -> None:
        base = _base_summary()
        head = dict(base, accuracy=0.80)  # -0.10
        regressions = detect_regressions(base, head, threshold=0.05)
        labels = [r["metric"] for r in regressions]
        self.assertIn("accuracy", labels)

    def test_quality_drop_within_threshold_is_not_regression(self) -> None:
        base = _base_summary()
        head = dict(base, accuracy=0.88)  # -0.02, within default 0.05
        regressions = detect_regressions(base, head, threshold=0.05)
        self.assertEqual(regressions, [])

    def test_latency_increase_is_excluded_from_gate(self) -> None:
        # Even a 10x latency spike must not fire the gate — host variance.
        base = _base_summary()
        head = dict(base, latency={"p50": 200.0, "p95": 8000.0})
        regressions = detect_regressions(base, head, threshold=0.05)
        self.assertEqual(regressions, [])

    def test_retry_rate_excluded_from_gate(self) -> None:
        # Retry rate is informational — it moves with verifier sensitivity
        # tuning and would produce false positives on intended changes.
        base = _base_summary()
        head = dict(base, retry=0.90)
        regressions = detect_regressions(base, head, threshold=0.05)
        self.assertEqual(regressions, [])

    def test_quality_improvement_is_not_regression(self) -> None:
        base = _base_summary()
        head = dict(base, accuracy=1.0)
        self.assertEqual(detect_regressions(base, head, threshold=0.05), [])

    def test_non_numeric_value_is_skipped(self) -> None:
        # Real eval summaries occasionally have null values for metrics
        # that don't apply to all slices — never raise on those.
        base = _base_summary()
        base["accuracy"] = None
        head = dict(base)
        self.assertEqual(detect_regressions(base, head, threshold=0.05), [])

    def test_multiple_regressions_all_reported(self) -> None:
        base = _base_summary()
        head = dict(
            base,
            accuracy=0.70,  # -0.20
            citation_precision=0.60,  # -0.30
        )
        regressions = detect_regressions(base, head, threshold=0.05)
        labels = sorted(r["metric"] for r in regressions)
        self.assertEqual(labels, ["accuracy", "citation_precision"])
        for r in regressions:
            self.assertIn("delta", r)
            self.assertIn("threshold", r)


class CompareEvalCliGateTest(unittest.TestCase):
    """Exit-code contract for the workflow.

    The workflow reads the exit code to decide whether to fail the
    job. Comment rendering must still happen on failure so reviewers
    see the regression in the PR conversation.
    """

    def _write(self, tmpdir: Path, name: str, data: dict) -> Path:
        path = tmpdir / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def _run(self, tmpdir: Path, base: dict, head: dict, **extra_args: object) -> subprocess.CompletedProcess:
        base_path = self._write(tmpdir, "base.json", base)
        head_path = self._write(tmpdir, "head.json", head)
        cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "compare_eval.py"),
            "--base", str(base_path),
            "--head", str(head_path),
            "--title", "Test",
        ]
        for key, value in extra_args.items():
            if value is True:
                cmd.append(f"--{key.replace('_', '-')}")
            elif value is False:
                continue
            else:
                cmd.extend([f"--{key.replace('_', '-')}", str(value)])
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_no_regression_exits_zero(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = self._run(Path(td), _base_summary(), _base_summary())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Gated quality metrics passed", result.stdout)

    def test_regression_exits_one(self) -> None:
        import tempfile
        base = _base_summary()
        head = dict(base, accuracy=0.50)
        with tempfile.TemporaryDirectory() as td:
            result = self._run(Path(td), base, head, regression_threshold=0.05)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Regression gate failed", result.stdout)
        self.assertIn("ALLOW_REGRESSION", result.stdout)

    def test_allow_regression_flag_exits_zero(self) -> None:
        import tempfile
        base = _base_summary()
        head = dict(base, accuracy=0.50)
        with tempfile.TemporaryDirectory() as td:
            result = self._run(
                Path(td), base, head,
                regression_threshold=0.05,
                allow_regression=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Acknowledged regression", result.stdout)

    def test_threshold_zero_disables_gate(self) -> None:
        import tempfile
        base = _base_summary()
        head = dict(base, accuracy=0.50)
        with tempfile.TemporaryDirectory() as td:
            result = self._run(Path(td), base, head, regression_threshold=0)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
