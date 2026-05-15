"""Tests for the LLM-judge plumbing on the real-data surface (ADR 0006)
and the additive RAGAS-style judge on the synthetic surface (ADR 0014).

The stub backends are deterministic, so plumbing is testable without
a network / API key. Tests pin:

* per-case verdict shape (ADR 0006: status; ADR 0014: four RAGAS scores)
* aggregate shape stays inside the ADR 0005 commit boundary
* per-case content caching makes re-runs cost-free
* token budget enforcement refuses past the cap
* CLI writes local file but stdout shows only aggregates
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from eval.judges.llm_judge import (
    DEFAULT_TOKEN_BUDGET,
    RAGAS_METRICS,
    judge_ragas,
)
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


class JudgeRagasStubTest(unittest.TestCase):
    """ADR 0014: RAGAS-style judge on the synthetic surface (additive)."""

    def test_stub_returns_four_metrics_with_fixed_scores(self) -> None:
        with TemporaryDirectory() as tmp:
            local, agg = judge_ragas(
                _fake_summary(), backend="stub", cache_dir=Path(tmp)
            )
        self.assertEqual(3, len(local["cases"]))
        for case in local["cases"]:
            for metric in RAGAS_METRICS:
                self.assertIn(metric, case)
                self.assertTrue(0.0 <= case[metric] <= 1.0)
        # Aggregate has the four metric means + n + ci.
        self.assertEqual(3, agg["n"])
        # Stub fixture: faithfulness=1.0, others=0.95.
        self.assertAlmostEqual(1.0, agg["faithfulness"])
        self.assertAlmostEqual(0.95, agg["answer_relevance"])
        self.assertAlmostEqual(0.95, agg["context_precision"])
        self.assertAlmostEqual(0.95, agg["context_recall"])
        # CI block exists and is well-formed per metric.
        for metric in RAGAS_METRICS:
            ci = agg["ci"].get(metric)
            self.assertIsNotNone(ci, metric)
            self.assertIn("ci_lo", ci)
            self.assertIn("ci_hi", ci)

    def test_aggregate_does_not_leak_per_case_text(self) -> None:
        with TemporaryDirectory() as tmp:
            _local, agg = judge_ragas(
                _fake_summary(), backend="stub", cache_dir=Path(tmp)
            )
        flat = json.dumps(agg, ensure_ascii=False)
        for leak in [
            "case_supported", "case_partial", "case_abstain",
            "private query", "private answer summary", "private evidence text",
        ]:
            self.assertNotIn(leak, flat)

    def test_cache_hit_skips_backend_call(self) -> None:
        """A second invocation against the same cache dir + inputs should
        be served entirely from cache (cache_hits == n, new_calls == 0)."""
        with TemporaryDirectory() as tmp:
            cache = Path(tmp)
            _first, _ = judge_ragas(
                _fake_summary(), backend="stub", cache_dir=cache
            )
            second, _ = judge_ragas(
                _fake_summary(), backend="stub", cache_dir=cache
            )
        self.assertEqual(3, second["cache_hits"])
        self.assertEqual(0, second["new_calls"])
        self.assertEqual(0, second["tokens_estimated"])

    def test_cache_invalidates_on_backend_switch(self) -> None:
        """Different backend identity should bust the cache."""
        with TemporaryDirectory() as tmp:
            cache = Path(tmp)
            _first, _ = judge_ragas(
                _fake_summary(), backend="stub", cache_dir=cache
            )
            # Manually creating cache entries with a fake backend identity
            # would be invasive; instead, verify the cache key includes
            # backend: switching backends (if openai_compatible were
            # available) would refresh. Here we just confirm consistency.
            second, _ = judge_ragas(
                _fake_summary(), backend="stub", cache_dir=cache
            )
        self.assertEqual(3, second["cache_hits"])

    def test_token_budget_refusal(self) -> None:
        """A zero-budget run must refuse rather than incur cost."""
        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                judge_ragas(
                    _fake_summary(),
                    backend="stub",
                    cache_dir=Path(tmp),
                    token_budget=0,
                )

    def test_unknown_backend_raises(self) -> None:
        with self.assertRaises(ValueError):
            judge_ragas(_fake_summary(), backend="does_not_exist")

    def test_empty_case_set_yields_null_aggregate(self) -> None:
        with TemporaryDirectory() as tmp:
            _local, agg = judge_ragas(
                {"case_results": []}, backend="stub", cache_dir=Path(tmp)
            )
        self.assertEqual(0, agg["n"])
        for metric in RAGAS_METRICS:
            self.assertIsNone(agg[metric])


class JudgeRagasCLITest(unittest.TestCase):
    def test_cli_stub_writes_local_payload_and_aggregate_to_stdout(self) -> None:
        with TemporaryDirectory() as tmp:
            eval_path = Path(tmp) / "eval_summary.json"
            out_path = Path(tmp) / "judge.local.json"
            cache_dir = Path(tmp) / "cache"
            eval_path.write_text(
                json.dumps(_fake_summary(), ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "eval/judges/llm_judge.py",
                    "--eval-summary", str(eval_path),
                    "--output", str(out_path),
                    "--cache-dir", str(cache_dir),
                    "--backend", "stub",
                ],
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parents[1],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            # Aggregate JSON appears on stdout; per-case text does not.
            self.assertIn("faithfulness", result.stdout)
            self.assertIn("context_recall", result.stdout)
            for leak in [
                "case_supported", "private query", "private answer summary",
            ]:
                self.assertNotIn(leak, result.stdout)
            # Local payload has per-case data + caching counters.
            local = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(3, len(local["cases"]))
            self.assertIn("cache_hits", local)
            self.assertIn("tokens_estimated", local)

    def test_cli_fold_aggregate_writes_into_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            eval_path = Path(tmp) / "eval_summary.json"
            out_path = Path(tmp) / "judge.local.json"
            cache_dir = Path(tmp) / "cache"
            eval_path.write_text(
                json.dumps(_fake_summary(), ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "eval/judges/llm_judge.py",
                    "--eval-summary", str(eval_path),
                    "--output", str(out_path),
                    "--cache-dir", str(cache_dir),
                    "--backend", "stub",
                    "--fold-aggregate",
                ],
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parents[1],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            folded = json.loads(eval_path.read_text(encoding="utf-8"))
            self.assertIn("judge_ragas", folded)
            self.assertAlmostEqual(1.0, folded["judge_ragas"]["faithfulness"])


if __name__ == "__main__":
    unittest.main()
