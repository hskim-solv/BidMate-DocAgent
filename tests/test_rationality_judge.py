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
    _planner_subset,
    _retrieval_subset,
    _synthesis_subset,
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


class TestAnswerReasoningCaptured(unittest.TestCase):
    """ADR 0056 follow-up (#1312 pending → measured): a trace carrying a
    populated synthesis_llm_call must yield answer_reasoning effective_n > 0,
    proving the BIDMATE_TRACE_FULL=1 stub-synthesis wiring reaches the axis."""

    def test_synthesis_populated_trace_scores_answer_reasoning(self):
        summary = _summary_with_inline_traces(n=4, with_synthesis=True)
        local, aggregate = judge_rationality(summary, backend="stub")
        # Every case carries a synthesis_llm_call → all scored.
        self.assertEqual(aggregate["effective_n"]["answer_reasoning"], 4)
        self.assertEqual(aggregate["cases_with_synthesis_llm_call"], 4)
        self.assertIsNotNone(aggregate["axis_means"]["answer_reasoning"])
        for case in local["cases"]:
            self.assertIsNotNone(case["answer_reasoning"])


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


class TestMarkdownSanitizesCaseIds(unittest.TestCase):
    """ADR 0056 line 71 / #1297: the committable Markdown must not leak raw
    descriptive case ids — those stay in the gitignored local payload."""

    def test_bottom_rows_use_anonymous_rank_not_case_id(self):
        # Descriptive ids that encode an agency name + topic, like the real qids.
        summary = {
            "case_results": [
                {
                    "id": f"real_광주연구원_no_answer_topic_{i}",
                    "slice": "abstention",
                    "query_type": "single_doc",
                    "query": f"query {i}",
                    "trace": _make_trace(),
                }
                for i in range(5)
            ]
        }
        local, aggregate = judge_rationality(summary, backend="stub")
        md = render_markdown(aggregate, local)
        # No raw case id appears in the committable Markdown.
        for case in local["cases"]:
            self.assertNotIn(case["id"], md)
        # Anonymous rank labels are used instead.
        self.assertIn("- #1 (slice=", md)
        self.assertIn("case ids omitted", md)

    def test_answer_reasoning_zero_effective_n_renders_pending(self):
        summary = _summary_with_inline_traces(n=3, with_synthesis=False)
        local, aggregate = judge_rationality(summary, backend="stub")
        md = render_markdown(aggregate, local)
        # Table cell and bottom-3 section both say "pending", never bare "N/A".
        self.assertIn("| `answer_reasoning` | pending | (full-trace) | 0 |", md)
        self.assertIn(
            "`answer_reasoning` — pending (no synthesis LLM call captured", md
        )


class TestMalformedTraceNullSafety(unittest.TestCase):
    """Guard paths for nested ``None`` values in the trace dict.

    The subset extractors must tolerate ``planner`` / ``attempts`` /
    ``retrieval_budget`` being ``None`` (or otherwise non-dict/non-list)
    without raising, falling back to the same empty-defaults the
    isinstance guards always intended.
    """

    def test_planner_none_yields_all_none_fields(self):
        subset = _planner_subset({"trace": {"planner": None}})
        self.assertEqual(
            subset,
            {
                "query_type": None,
                "pipeline": None,
                "stage_sequence": None,
                "selected_top_k": None,
                "retrieval_budget_reason": None,
            },
        )

    def test_retrieval_budget_non_dict_yields_none_reason(self):
        subset = _planner_subset(
            {"trace": {"planner": {"retrieval_budget": "not-a-dict"}}}
        )
        self.assertIsNone(subset["retrieval_budget_reason"])

    def test_attempts_none_yields_empty_list(self):
        self.assertEqual(_retrieval_subset({"trace": {"planner": {"attempts": None}}}), [])

    def test_missing_nested_trace_key_falls_back_to_top_level(self):
        # No "trace" nesting: planner sits at top level.
        self.assertEqual(_retrieval_subset({"planner": {"attempts": None}}), [])

    def test_synthesis_call_non_dict_returns_none(self):
        self.assertIsNone(_synthesis_subset({"trace": {"synthesis_llm_call": None}}))


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


class TestExpectFullTraceGuard(unittest.TestCase):
    """#1297: --expect-full-trace fails loudly when answer_reasoning is empty
    (no synthesis LLM call captured), surfacing a silently-incomplete run."""

    def _run(self, *, with_synthesis: bool, expect_full_trace: bool) -> int:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            eval_path = tmp_path / "eval_summary.json"
            eval_path.write_text(
                json.dumps(
                    _summary_with_inline_traces(n=3, with_synthesis=with_synthesis)
                ),
                encoding="utf-8",
            )
            argv = [
                "--eval-summary", str(eval_path),
                "--output", str(tmp_path / "rationality.local.json"),
                "--out-aggregate", str(tmp_path / "rationality.aggregate.json"),
                "--out-md", str(tmp_path / "rationality.md"),
                "--backend", "stub",
            ]
            if expect_full_trace:
                argv.append("--expect-full-trace")
            return cli_main(argv)

    def test_exits_3_when_answer_reasoning_uncaptured(self):
        self.assertEqual(
            self._run(with_synthesis=False, expect_full_trace=True), 3
        )

    def test_exits_0_when_answer_reasoning_captured(self):
        self.assertEqual(
            self._run(with_synthesis=True, expect_full_trace=True), 0
        )

    def test_without_flag_uncaptured_still_exits_0(self):
        self.assertEqual(
            self._run(with_synthesis=False, expect_full_trace=False), 0
        )


if __name__ == "__main__":
    unittest.main()
