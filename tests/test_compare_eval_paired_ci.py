"""Paired-bootstrap CI block in the local eval comparator (issue #1205).

Locks the additive ``--paired-ci`` surface of ``scripts/compare_eval.py``:

* A clear per-case improvement reports a CI excluding 0 (유의함).
* An identical pair reports a CI bracketing 0 (유의하지 않음).
* A committed aggregate baseline (no ``case_results``) degrades to an
  explanatory note rather than crashing — the ADR 0005 boundary case.
* An all-``None`` conditional metric (ADR 0054) is skipped, not fatal.
* The block is OFF by default so existing PR-eval output is unchanged.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))  # for eval.bootstrap via _ablation_common

from compare_eval import _render_paired_ci_block  # noqa: E402


def _summary(case_scores: Sequence[tuple[str, float | None]]) -> dict:
    """Minimal eval_summary.json with per-case ``accuracy``/``abstention``."""
    return {
        "pipeline": "agentic_full",
        "primary_run": "full",
        "num_predictions": len(case_scores),
        "accuracy": (
            sum(a for _, a in case_scores if a is not None)
            / max(1, sum(1 for _, a in case_scores if a is not None))
        ),
        "case_results": [
            {"id": cid, "accuracy": acc, "groundedness": acc, "abstention": None}
            for cid, acc in case_scores
        ],
    }


class PairedCIBlockTest(unittest.TestCase):
    def test_clear_improvement_excludes_zero(self) -> None:
        base = _summary([(f"c{i}", 0.0) for i in range(30)])
        head = _summary([(f"c{i}", 1.0) for i in range(30)])
        block = "\n".join(_render_paired_ci_block(base, head, seeds=[17, 19, 23]))
        self.assertIn("accuracy", block)
        self.assertIn("+1.000", block)
        self.assertIn("유의함", block)
        self.assertIn("paired cases: 30", block)

    def test_identical_pair_brackets_zero(self) -> None:
        rows = [(f"c{i}", float(i % 2)) for i in range(30)]
        block = "\n".join(
            _render_paired_ci_block(_summary(rows), _summary(rows), seeds=[17, 19, 23])
        )
        self.assertIn("유의하지 않음", block)

    def test_missing_case_results_degrades_gracefully(self) -> None:
        base = {"accuracy": 0.5}  # aggregate-only baseline, no case_results
        head = {"accuracy": 0.6}
        block = "\n".join(_render_paired_ci_block(base, head, seeds=[17]))
        self.assertIn("case_results", block)

    def test_all_none_metric_is_skipped_not_fatal(self) -> None:
        # abstention is None for every case -> N/A row, no exception.
        rows = [(f"c{i}", 1.0) for i in range(10)]
        block = "\n".join(_render_paired_ci_block(_summary(rows), _summary(rows), seeds=[17]))
        self.assertIn("abstention", block)
        self.assertIn("N/A", block)

    def test_no_shared_ids(self) -> None:
        base = _summary([(f"a{i}", 1.0) for i in range(5)])
        head = _summary([(f"b{i}", 1.0) for i in range(5)])
        block = "\n".join(_render_paired_ci_block(base, head, seeds=[17]))
        self.assertIn("no shared case ids", block)

    def test_flag_off_by_default_via_cli(self) -> None:
        """Default invocation must not emit the paired-CI block."""
        with _tmp_summaries() as (base_path, head_path):
            out = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "compare_eval.py"),
                    "--base",
                    base_path,
                    "--head",
                    head_path,
                    "--regression-threshold",
                    "0",
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertNotIn("Paired bootstrap", out.stdout)

    def test_flag_on_emits_block_via_cli(self) -> None:
        with _tmp_summaries() as (base_path, head_path):
            out = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "compare_eval.py"),
                    "--base",
                    base_path,
                    "--head",
                    head_path,
                    "--regression-threshold",
                    "0",
                    "--paired-ci",
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("Paired bootstrap", out.stdout)


import contextlib  # noqa: E402
import tempfile  # noqa: E402


@contextlib.contextmanager
def _tmp_summaries():
    base = _summary([(f"c{i}", 0.0) for i in range(20)])
    head = _summary([(f"c{i}", 1.0) for i in range(20)])
    with tempfile.TemporaryDirectory() as d:
        bp = Path(d) / "base.json"
        hp = Path(d) / "head.json"
        bp.write_text(json.dumps(base), encoding="utf-8")
        hp.write_text(json.dumps(head), encoding="utf-8")
        yield str(bp), str(hp)


if __name__ == "__main__":
    unittest.main()
