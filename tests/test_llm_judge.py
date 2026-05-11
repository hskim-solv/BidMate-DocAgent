"""Tests for the LLM-judge plumbing on the real-data surface (ADR 0006).

The stub backend mirrors the verifier's status, which makes the
plumbing testable without a network / API key. The tests pin:

* the per-case verdict shape and the agreement-with-verifier
  bookkeeping
* the aggregate shape stays inside the ADR 0005 / ADR 0006 commit
  boundary (no per-case judge text)
* the CLI writes the local file but stdout shows only aggregates
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.llm_judge import judge_summary


def _fake_summary() -> dict:
    return {
        "primary_run": "full",
        "pipeline": "agentic_full",
        "num_predictions": 3,
        "case_results": [
            {
                "id": "case_supported",
                "query": "private query 1",
                "answer_status": "supported",
                "answer": {"summary": "private answer summary 1"},
                "evidence": [{"text": "private evidence text 1"}],
            },
            {
                "id": "case_partial",
                "query": "private query 2",
                "answer_status": "partial",
                "answer": {"summary": "private answer summary 2"},
                "evidence": [{"text": "private evidence text 2"}],
            },
            {
                "id": "case_abstain",
                "query": "private query 3",
                "answer_status": "insufficient",
                "answer": {"summary": ""},
                "evidence": [],
            },
        ],
    }


class JudgeSummaryStubTest(unittest.TestCase):
    def test_stub_backend_agrees_with_verifier_perfectly(self) -> None:
        local, agg = judge_summary(_fake_summary(), backend="stub")
        # Per-case payload shape.
        self.assertEqual(len(local["cases"]), 3)
        for case in local["cases"]:
            self.assertIn(case["judge_status"], {"supported", "partial", "insufficient"})
            self.assertTrue(case["agrees"], case)
        # Aggregate shape — only the four committable keys + n.
        self.assertEqual(set(agg), {"status_distribution", "grounded_rate", "agreement_with_verifier", "n"})
        self.assertEqual(agg["n"], 3)
        self.assertEqual(agg["agreement_with_verifier"], 1.0)
        # Only the supported case should count as grounded.
        self.assertAlmostEqual(agg["grounded_rate"], 1 / 3)
        self.assertEqual(
            agg["status_distribution"],
            {"supported": 1, "partial": 1, "insufficient": 1},
        )

    def test_aggregate_does_not_leak_per_case_text(self) -> None:
        _local, agg = judge_summary(_fake_summary(), backend="stub")
        flat = json.dumps(agg, ensure_ascii=False)
        for leak in [
            "case_supported", "case_partial", "case_abstain",
            "private query", "private answer summary", "private evidence text",
        ]:
            self.assertNotIn(leak, flat)

    def test_unknown_backend_raises(self) -> None:
        with self.assertRaises(ValueError):
            judge_summary(_fake_summary(), backend="does_not_exist")


class JudgeCLIInvocationTest(unittest.TestCase):
    """Smoke the CLI end-to-end with the stub backend."""

    def test_cli_writes_local_file_and_prints_aggregate_only(self) -> None:
        with TemporaryDirectory() as tmp:
            eval_path = Path(tmp) / "eval_summary.json"
            out_path = Path(tmp) / "judge.local.json"
            eval_path.write_text(
                json.dumps(_fake_summary(), ensure_ascii=False), encoding="utf-8"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/llm_judge.py",
                    "--eval-summary", str(eval_path),
                    "--output", str(out_path),
                    "--backend", "stub",
                ],
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parents[1],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            # Aggregate JSON appears on stdout; per-case data does NOT.
            self.assertIn("status_distribution", result.stdout)
            self.assertIn("agreement_with_verifier", result.stdout)
            for leak in ["case_supported", "private query", "private answer summary"]:
                self.assertNotIn(leak, result.stdout)
            # Local file has per-case data (this is OK — local-only).
            local = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(len(local["cases"]), 3)
            self.assertIn("case_supported", json.dumps(local, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
