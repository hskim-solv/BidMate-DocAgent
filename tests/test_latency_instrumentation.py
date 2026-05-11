import time
import unittest
from pathlib import Path

import rag_core
from rag_core import _StageTimer, build_index_payload, run_rag_query
from eval.run_eval import metric_block, summarize_run


class StageTimerTest(unittest.TestCase):
    def test_records_elapsed_milliseconds(self) -> None:
        bucket: dict[str, float] = {}
        with _StageTimer(bucket, "stage_ms"):
            time.sleep(0.005)
        self.assertIn("stage_ms", bucket)
        self.assertGreater(bucket["stage_ms"], 0.0)

    def test_reentry_accumulates(self) -> None:
        bucket: dict[str, float] = {}
        with _StageTimer(bucket, "stage_ms"):
            time.sleep(0.001)
        first = bucket["stage_ms"]
        with _StageTimer(bucket, "stage_ms"):
            time.sleep(0.001)
        self.assertGreater(bucket["stage_ms"], first)


class RunRagQueryTimingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_index_payload(Path("data/raw"), embedding_backend="hashing")

    def setUp(self) -> None:
        rag_core._PROCESS_WARM = False

    def test_diagnostics_include_stage_latency(self) -> None:
        result = run_rag_query(self.index, "기관A의 보안 통제 요구사항은?")
        diagnostics = result["diagnostics"]
        self.assertIn("stage_latency", diagnostics)
        self.assertIn("cold_start", diagnostics)
        for key in ("query_analysis_ms", "context_resolution_ms", "answer_generation_ms"):
            self.assertIn(key, diagnostics["stage_latency"])
            self.assertGreaterEqual(diagnostics["stage_latency"][key], 0.0)

    def test_filter_stage_attempts_have_per_attempt_timings(self) -> None:
        result = run_rag_query(self.index, "기관A의 보안 통제 요구사항은?")
        attempts = result["diagnostics"]["filter_stage_attempts"]
        self.assertTrue(attempts)
        for attempt in attempts:
            self.assertIn("retrieve_ms", attempt)
            self.assertIn("verify_ms", attempt)
            self.assertGreaterEqual(attempt["retrieve_ms"], 0.0)
            self.assertGreaterEqual(attempt["verify_ms"], 0.0)

    def test_cold_start_flag_flips_after_first_call(self) -> None:
        first = run_rag_query(self.index, "기관A의 보안 통제 요구사항은?")
        second = run_rag_query(self.index, "기관A의 보안 통제 요구사항은?")
        self.assertTrue(first["diagnostics"]["cold_start"])
        self.assertFalse(second["diagnostics"]["cold_start"])

    def test_retry_attempts_each_get_timings(self) -> None:
        original_verify = rag_core.verify_evidence
        calls = {"n": 0}

        def always_fail(analysis, evidence, **_kwargs):
            calls["n"] += 1
            return False, ["forced_failure"]

        rag_core.verify_evidence = always_fail
        try:
            result = run_rag_query(self.index, "기관A의 보안 통제 요구사항은?")
        finally:
            rag_core.verify_evidence = original_verify

        attempts = result["diagnostics"]["filter_stage_attempts"]
        self.assertGreaterEqual(len(attempts), 2)
        for attempt in attempts:
            self.assertIn("retrieve_ms", attempt)
            self.assertIn("verify_ms", attempt)
        self.assertGreaterEqual(result["diagnostics"]["retry_count"], 1)


class MetricBlockLatencyTest(unittest.TestCase):
    def _case(
        self,
        *,
        retry_count: int,
        latency_ms: float,
        cold_start: bool = False,
        retrieve_ms: float = 5.0,
        verify_ms: float = 1.0,
    ) -> dict:
        attempts = retry_count + 1
        return {
            "query_type": "single_doc",
            "hardcase_categories": [],
            "accuracy": 1.0,
            "groundedness": 1.0,
            "citation_precision": 1.0,
            "answer_format_compliance": 1.0,
            "abstention": None,
            "latency_ms": latency_ms,
            "retry_count": retry_count,
            "retry_trigger_reasons": [],
            "cold_start": cold_start,
            "stage_latency": {
                "query_analysis_ms": 2.0,
                "context_resolution_ms": 1.0,
                "answer_generation_ms": 3.0,
            },
            "attempt_latency": [
                {"stage": "strict", "retrieve_ms": retrieve_ms, "verify_ms": verify_ms}
            ]
            * attempts,
        }

    def test_stage_latency_aggregations_present(self) -> None:
        case_results = [
            self._case(retry_count=0, latency_ms=10.0),
            self._case(retry_count=1, latency_ms=20.0),
            self._case(retry_count=2, latency_ms=30.0),
        ]
        block = metric_block(case_results)
        self.assertIn("stage_latency", block)
        for key in (
            "query_analysis_ms",
            "context_resolution_ms",
            "answer_generation_ms",
            "retrieve_ms",
            "verify_ms",
        ):
            self.assertIn(key, block["stage_latency"])
            self.assertEqual(2.0 if key == "query_analysis_ms" else block["stage_latency"][key]["mean"], block["stage_latency"][key]["mean"])
            self.assertGreater(block["stage_latency"][key]["count"], 0)

    def test_latency_by_retry_count_buckets(self) -> None:
        case_results = [
            self._case(retry_count=0, latency_ms=10.0),
            self._case(retry_count=0, latency_ms=12.0),
            self._case(retry_count=1, latency_ms=25.0),
        ]
        block = metric_block(case_results)
        self.assertIn("0", block["latency_by_retry_count"])
        self.assertIn("1", block["latency_by_retry_count"])
        self.assertEqual(2, block["latency_by_retry_count"]["0"]["count"])
        self.assertEqual(1, block["latency_by_retry_count"]["1"]["count"])

    def test_cold_start_excluded_from_warm_aggregations(self) -> None:
        case_results = [
            self._case(retry_count=0, latency_ms=500.0, cold_start=True),
            self._case(retry_count=0, latency_ms=10.0),
            self._case(retry_count=0, latency_ms=12.0),
        ]
        block = metric_block(case_results)
        # Warm bucket should not include the 500ms cold-start latency.
        self.assertEqual(2, block["latency_by_retry_count"]["0"]["count"])
        self.assertLess(block["latency_by_retry_count"]["0"]["p95"], 500.0)
        self.assertEqual(1, block["cold_start_samples"]["count"])
        self.assertIsNotNone(block["cold_start_samples"]["latency_ms"])

    def test_summarize_run_propagates_stage_latency_to_query_type(self) -> None:
        case_results = [
            self._case(retry_count=0, latency_ms=10.0),
            self._case(retry_count=1, latency_ms=20.0),
        ]
        summary = summarize_run("unit", {"pipeline": "agentic_full"}, case_results)
        self.assertIn("stage_latency", summary)
        self.assertIn("stage_latency", summary["by_query_type"]["single_doc"])
        self.assertIn("latency_by_retry_count", summary["by_query_type"]["single_doc"])


if __name__ == "__main__":
    unittest.main()
