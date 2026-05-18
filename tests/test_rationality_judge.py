"""Tests for the trajectory-rationality judge (ADR 0056, issue #969).

Covers the stub backend's determinism, the 3-axis schema, the env-off
``answer_reasoning=None`` skip semantics, bootstrap-CI integration, and
the end-to-end CLI via ``main()``.

We do NOT exercise the openai_compatible backend — it requires a live
endpoint and an API key.  The stub backend uses the same shared
``judge_common`` helpers (clamp_score) so coverage of the LLM path is
implicit through the verdict-normalisation surface.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.judges.rationality_judge import (  # noqa: E402
    RATIONALITY_AXES,
    judge_rationality,
    render_markdown,
)
from scripts.run_rationality_judge import main as cli_main  # noqa: E402


def _make_trace(
    *,
    with_synthesis: bool = True,
    stage_sequence: list[str] | None = None,
    verification_reasons: list[list[str]] | None = None,
) -> dict:
    """Minimal trace JSON shape mirroring the v2 ``build_result_trace`` output."""
    stage_sequence = stage_sequence or ["relaxed", "relaxed"]
    verification_reasons = verification_reasons or [
        ["topic_not_grounded"],
        ["partial_topic_grounding"],
    ]
    trace: dict = {
        "schema_version": 2,
        "case_id": "stub_case",
        "query": "기관 A 의 사업기간은?",
        "trace": {
            "schema_version": 2,
            "planner": {
                "query_type": "single_doc",
                "pipeline": "agentic_full",
                "stage_sequence": stage_sequence,
                "selected_top_k": 8,
                "retrieval_budget": {"reason": "retry_expansion"},
                "attempts": [
                    {"verification_reasons": reasons}
                    for reasons in verification_reasons
                ],
            },
        },
    }
    if with_synthesis:
        trace["trace"]["synthesis_llm_call"] = {
            "backend": "anthropic",
            "model": "claude-sonnet-4-6",
            "tokens_in": 1200,
            "tokens_out": 350,
            "user_prompt_text": "Query: 기관 A 사업기간\n\nEvidence: ...",
            "completion_text": '{"summary": "12개월", "used_chunk_ids": ["c1"]}',
        }
    return trace


def _summary_with_inline_traces(n: int = 3, with_synthesis: bool = True) -> dict:
    """Build an eval_summary dict with embedded traces (sidesteps trace_path I/O)."""
    return {
        "case_results": [
            {
                "id": f"case_{i}",
                "slice": "single_doc",
                "query_type": "single_doc",
                "query": f"query {i}",
                "trace": _make_trace(with_synthesis=with_synthesis),
            }
            for i in range(n)
        ]
    }


class TestStubBackendDeterminism(unittest.TestCase):
    def test_two_runs_byte_identical_per_case_scores(self):
        summary = _summary_with_inline_traces(n=3)
        local1, _ = judge_rationality(summary, backend="stub")
        local2, _ = judge_rationality(summary, backend="stub")
        # Compare only the per-axis scores (not the timestamp) for determinism.
        scores1 = [
            {axis: c.get(axis) for axis in RATIONALITY_AXES}
            for c in local1["cases"]
        ]
        scores2 = [
            {axis: c.get(axis) for axis in RATIONALITY_AXES}
            for c in local2["cases"]
        ]
        self.assertEqual(scores1, scores2)


class TestAxisSchemaAndRange(unittest.TestCase):
    def test_three_axes_present_per_case_scores_in_unit_interval(self):
        summary = _summary_with_inline_traces(n=5)
        local, _ = judge_rationality(summary, backend="stub")
        for case in local["cases"]:
            for axis in RATIONALITY_AXES:
                value = case.get(axis)
                self.assertIsNotNone(value, f"axis {axis} missing on {case['id']}")
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)


class TestAnswerReasoningEnvOffSkip(unittest.TestCase):
    def test_no_synthesis_llm_call_yields_none_answer_reasoning(self):
        summary = _summary_with_inline_traces(n=3, with_synthesis=False)
        local, aggregate = judge_rationality(summary, backend="stub")
        for case in local["cases"]:
            self.assertIsNone(case["answer_reasoning"])
            # other axes still produce scores
            self.assertIsNotNone(case["planner_decomposition"])
            self.assertIsNotNone(case["retrieval_recalls"])
        # aggregate reports effective_n = 0 for answer_reasoning
        self.assertEqual(aggregate["effective_n"]["answer_reasoning"], 0)
        self.assertIsNone(aggregate["axis_means"]["answer_reasoning"])
        # synthesis-aware axes still aggregated
        self.assertEqual(aggregate["effective_n"]["planner_decomposition"], 3)


class TestAggregateBootstrapCI(unittest.TestCase):
    def test_aggregate_includes_axis_means_and_cis(self):
        summary = _summary_with_inline_traces(n=10)
        _, aggregate = judge_rationality(summary, backend="stub")
        self.assertEqual(aggregate["n"], 10)
        for axis in RATIONALITY_AXES:
            mean = aggregate["axis_means"].get(axis)
            self.assertIsNotNone(mean, axis)
            self.assertGreaterEqual(mean, 0.0)
            self.assertLessEqual(mean, 1.0)
            ci = aggregate["axis_cis"].get(axis)
            self.assertIsNotNone(ci, axis)
            self.assertIn("ci_lo", ci)
            self.assertIn("ci_hi", ci)
            self.assertLessEqual(ci["ci_lo"], mean)
            self.assertLessEqual(mean, ci["ci_hi"])


class TestMarkdownRenders(unittest.TestCase):
    def test_render_markdown_contains_axes_and_n(self):
        summary = _summary_with_inline_traces(n=4)
        local, aggregate = judge_rationality(summary, backend="stub")
        md = render_markdown(aggregate, local)
        self.assertIn("Trajectory rationality (ADR 0056)", md)
        for axis in RATIONALITY_AXES:
            self.assertIn(axis, md)
        self.assertIn("n: 4", md)


class TestEndToEndCLI(unittest.TestCase):
    def test_cli_writes_three_outputs_and_exits_zero(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            eval_path = tmp_path / "eval_summary.json"
            eval_path.write_text(
                json.dumps(_summary_with_inline_traces(n=3)),
                encoding="utf-8",
            )
            out_local = tmp_path / "rationality.local.json"
            out_agg = tmp_path / "rationality.aggregate.json"
            out_md = tmp_path / "rationality.md"

            rc = cli_main(
                [
                    "--eval-summary",
                    str(eval_path),
                    "--output",
                    str(out_local),
                    "--out-aggregate",
                    str(out_agg),
                    "--out-md",
                    str(out_md),
                    "--backend",
                    "stub",
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(out_local.exists())
            self.assertTrue(out_agg.exists())
            self.assertTrue(out_md.exists())
            agg = json.loads(out_agg.read_text())
            self.assertEqual(agg["n"], 3)


if __name__ == "__main__":
    unittest.main()
