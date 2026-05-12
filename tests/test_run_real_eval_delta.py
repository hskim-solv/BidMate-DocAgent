"""Tests for the real-data eval delta script.

The script's main job is to enforce the ADR 0005 commit boundary
mechanically: aggregate-only output, no per-case data, no query/doc
text. These tests pin that contract.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from scripts.run_real_eval_delta import (
    FORBIDDEN_KEYS,
    SAFE_ABSTENTION_OUTCOME_KEYS,
    _fmt_delta,
    _min_num_predictions,
    _silence_threshold,
    extract_aggregate,
    render_markdown,
)


# A realistic-ish eval_summary.json with *case-level fields*. The
# extractor must drop every one of them.
FULL_SUMMARY = {
    "primary_run": "full",
    "pipeline": "agentic_full",
    "num_predictions": 21,
    "accuracy": 0.471,
    "groundedness": 0.476,
    "citation_precision": 0.286,
    "abstention": 0.5,
    "retry": 0.429,
    "latency": {"p50": 100.0, "p95": 300.0, "mean": 150.0},
    "stage_latency": {
        "retrieve_ms": {"p50": 5.0, "p95": 20.0, "mean": 8.0, "count": 21}
    },
    "retry_reason_counts": {"topic_not_grounded": 12},
    "by_query_type": {
        "single_doc": {
            "num_predictions": 12,
            "accuracy": 0.5,
            "abstention": None,
        },
        "abstention": {
            "num_predictions": 4,
            "abstention": 0.5,
        },
    },
    # Forbidden territory below — must not appear in extracted output.
    "case_results": [
        {
            "id": "real_secret_case",
            "query": "이건 진짜 비공개 질의 텍스트",
            "answer": "case-level answer leak",
            "evidence": [{"doc_id": "private_doc_1", "text": "private text"}],
            "expected_doc_ids": ["private_doc_1"],
        }
    ],
    "trace_dir": "reports/real100/traces",
}


class ExtractAggregateTest(unittest.TestCase):
    def test_extracts_top_level_aggregates(self) -> None:
        agg = extract_aggregate(FULL_SUMMARY)
        self.assertEqual(agg["accuracy"], 0.471)
        self.assertEqual(agg["pipeline"], "agentic_full")
        self.assertEqual(agg["num_predictions"], 21)
        self.assertEqual(agg["latency"], {"p50": 100.0, "p95": 300.0, "mean": 150.0})
        self.assertEqual(
            agg["retry_reason_counts"], {"topic_not_grounded": 12}
        )

    def test_drops_case_results(self) -> None:
        agg = extract_aggregate(FULL_SUMMARY)
        self.assertNotIn("case_results", agg)

    def test_drops_query_and_evidence_anywhere(self) -> None:
        agg = extract_aggregate(FULL_SUMMARY)
        flat = json.dumps(agg, ensure_ascii=False)
        # None of the leaked strings from FULL_SUMMARY's case_results
        # should appear in the serialized aggregate.
        self.assertNotIn("real_secret_case", flat)
        self.assertNotIn("진짜 비공개", flat)
        self.assertNotIn("private_doc_1", flat)
        self.assertNotIn("case-level answer leak", flat)

    def test_slice_aggregates_preserved(self) -> None:
        agg = extract_aggregate(FULL_SUMMARY)
        slices = agg["by_query_type"]
        self.assertIn("single_doc", slices)
        self.assertIn("abstention", slices)
        self.assertEqual(slices["single_doc"]["num_predictions"], 12)
        self.assertEqual(slices["abstention"]["abstention"], 0.5)
        # None of the case-level fields per slice should appear.
        for slice_payload in slices.values():
            for key in slice_payload:
                self.assertNotIn(key, FORBIDDEN_KEYS)

    def test_forbidden_key_assertion_fires_on_drift(self) -> None:
        """If a future maintainer adds a forbidden key to SAFE list,
        the assertion in extract_aggregate must crash rather than
        silently emit case-level data."""
        bad_input = {"case_results": [{"query": "leak"}]}
        # The extractor itself never copies case_results into output,
        # so this should still work — the assertion guards the OUTPUT.
        # But we can validate the recursive scanner separately by
        # feeding it a tainted dict.
        from scripts.run_real_eval_delta import _assert_no_forbidden

        with self.assertRaises(AssertionError):
            _assert_no_forbidden({"latency": {"case_results": []}})

    def test_extraction_is_idempotent(self) -> None:
        agg1 = extract_aggregate(FULL_SUMMARY)
        agg2 = extract_aggregate(agg1)
        self.assertEqual(agg1, agg2)

    def test_render_markdown_has_no_leaked_text(self) -> None:
        base = extract_aggregate(FULL_SUMMARY)
        head = extract_aggregate({**FULL_SUMMARY, "accuracy": 0.6})
        md = render_markdown(base, head, "test")
        # Strings that would only exist in case-level fields:
        for leak in [
            "real_secret_case",
            "진짜 비공개",
            "private_doc_1",
            "case-level answer leak",
        ]:
            self.assertNotIn(leak, md)
        # Aggregate values should be visible:
        self.assertIn("accuracy", md)
        self.assertIn("0.471", md)
        self.assertIn("0.600", md)

    def test_render_includes_slice_abstention(self) -> None:
        base = extract_aggregate(FULL_SUMMARY)
        head = extract_aggregate({**FULL_SUMMARY, "accuracy": 0.6})
        md = render_markdown(base, head, "test")
        # Slice section should be present.
        self.assertIn("Slice abstention", md)
        self.assertIn("abstention", md)

    def test_provenance_passes_through_extraction(self) -> None:
        """Issue #160: provenance is metadata about run state (no per-case
        content), so it crosses the ADR 0005 commit boundary intact. It
        must survive extract_aggregate and not trip the forbidden-key guard.
        """
        summary_with_provenance = {
            **FULL_SUMMARY,
            "provenance": {
                "git_commit": "deadbeef0000",
                "git_dirty": False,
                "generated_at": "2026-05-11T08:04:05Z",
            },
        }
        agg = extract_aggregate(summary_with_provenance)
        self.assertIn("provenance", agg)
        self.assertEqual(agg["provenance"]["git_commit"], "deadbeef0000")
        self.assertEqual(agg["provenance"]["git_dirty"], False)
        # No per-case data leaked through.
        flat = json.dumps(agg, ensure_ascii=False)
        self.assertNotIn("real_secret_case", flat)
        self.assertNotIn("private_doc_1", flat)

    def test_render_includes_commit_sha_header(self) -> None:
        """The rendered delta surfaces base/head commit SHAs so reviewers
        can spot eval-vs-baseline provenance skew (the #160 failure mode).
        """
        base = extract_aggregate(
            {
                **FULL_SUMMARY,
                "provenance": {
                    "git_commit": "aaaaaaaaaaaa",
                    "git_dirty": False,
                    "generated_at": "2026-05-01T00:00:00Z",
                },
            }
        )
        head = extract_aggregate(
            {
                **FULL_SUMMARY,
                "accuracy": 0.6,
                "provenance": {
                    "git_commit": "bbbbbbbbbbbb",
                    "git_dirty": False,
                    "generated_at": "2026-05-11T00:00:00Z",
                },
            }
        )
        md = render_markdown(base, head, "test")
        self.assertIn("aaaaaaaaaaaa", md)
        self.assertIn("bbbbbbbbbbbb", md)
        self.assertIn("commits:", md)

    def test_retry_effectiveness_sub_keys_extracted(self) -> None:
        """Issue #120: the retry_effectiveness aggregate must round-trip the
        whitelisted sub-keys (counts + rates + cross_ablation) and drop any
        unexpected nesting."""
        summary = {
            **FULL_SUMMARY,
            "retry_effectiveness": {
                "cases_with_retry": 6,
                "cases_without_retry": 36,
                "recovery_rate": 0.5,
                "residual_failure_rate": 0.5,
                "retry_resolution_rate": 0.83,
                "retry_lift_vs_no_retry": -0.1,
                "ci": {
                    "recovery_rate": {"mean": 0.5, "ci_lo": 0.2, "ci_hi": 0.8, "n": 6},
                    "residual_failure_rate": {
                        "mean": 0.5,
                        "ci_lo": 0.2,
                        "ci_hi": 0.8,
                        "n": 6,
                    },
                },
                "cross_ablation": {
                    "n_retry_triggered": 6,
                    "n_evaluable": 6,
                    "true_positive_triggers": 4,
                    "false_positive_triggers": 2,
                    "retry_precision": 0.667,
                    "method": "cross_ablation(agentic_full,no_verifier_retry)",
                    # Unexpected sub-key — must be dropped.
                    "case_results": [{"id": "leak"}],
                },
            },
        }
        agg = extract_aggregate(summary)
        re = agg["retry_effectiveness"]
        self.assertEqual(6, re["cases_with_retry"])
        self.assertAlmostEqual(0.667, re["cross_ablation"]["retry_precision"])
        self.assertNotIn("case_results", re["cross_ablation"])
        # CI sub-block preserved
        self.assertIn("recovery_rate", re["ci"])
        # No FORBIDDEN_KEYS leakage anywhere
        from scripts.run_real_eval_delta import _assert_no_forbidden

        _assert_no_forbidden(re)

    def test_run_manifest_drops_filesystem_path(self) -> None:
        """run_manifest must omit config_path (filesystem layout) but keep
        the SHA. The aggregate is committable, so a path like
        'eval/real_config.local.yaml' is not safe to publish."""
        summary = {
            **FULL_SUMMARY,
            "run_manifest": {
                "git_commit": "abc123def456",
                "git_dirty": False,
                "config_path": "/Users/hskim/private/real_config.local.yaml",
                "config_sha256": "0123456789abcdef",
                "generated_at": "2026-05-11T10:30:00Z",
            },
        }
        agg = extract_aggregate(summary)
        manifest = agg["run_manifest"]
        self.assertEqual("abc123def456", manifest["git_commit"])
        self.assertEqual("0123456789abcdef", manifest["config_sha256"])
        self.assertNotIn("config_path", manifest)
        # The dropped path should not appear anywhere in the serialized output.
        self.assertNotIn("hskim", json.dumps(agg))

    def test_render_includes_retry_effectiveness_section(self) -> None:
        summary_with_re = {
            **FULL_SUMMARY,
            "retry_effectiveness": {
                "cases_with_retry": 6,
                "cases_without_retry": 36,
                "recovery_rate": 0.5,
                "residual_failure_rate": 0.5,
                "retry_resolution_rate": 0.83,
                "retry_lift_vs_no_retry": -0.1,
            },
        }
        base = extract_aggregate(summary_with_re)
        head = extract_aggregate({**summary_with_re, "retry_effectiveness": {
            **summary_with_re["retry_effectiveness"],
            "recovery_rate": 0.8,
        }})
        md = render_markdown(base, head, "test")
        self.assertIn("Retry effectiveness", md)
        self.assertIn("recovery_rate", md)
        self.assertIn("0.500", md)
        self.assertIn("0.800", md)

    def test_judge_ragas_sub_keys_whitelisted(self) -> None:
        """ADR 0012: judge_ragas aggregate must round-trip the four metric
        means + CI sub-block, and drop any unexpected sub-keys (e.g.,
        per-case payload smuggled in by a future maintainer)."""
        summary = {
            **FULL_SUMMARY,
            "judge_ragas": {
                "faithfulness": 0.92,
                "answer_relevance": 0.85,
                "context_precision": 0.78,
                "context_recall": 0.81,
                "n": 42,
                "ci": {
                    "faithfulness": {"mean": 0.92, "ci_lo": 0.85, "ci_hi": 0.97, "n": 42},
                    "answer_relevance": {"mean": 0.85, "ci_lo": 0.78, "ci_hi": 0.92, "n": 42},
                },
                # Unexpected sub-keys must be dropped.
                "cases": [{"id": "leak", "query": "leak"}],
                "raw_prompts": "leak prompt content",
            },
        }
        agg = extract_aggregate(summary)
        ragas = agg["judge_ragas"]
        self.assertAlmostEqual(0.92, ragas["faithfulness"])
        self.assertAlmostEqual(0.78, ragas["context_precision"])
        self.assertEqual(42, ragas["n"])
        self.assertIn("faithfulness", ragas["ci"])
        # Unexpected sub-keys dropped.
        self.assertNotIn("cases", ragas)
        self.assertNotIn("raw_prompts", ragas)
        # Privacy: leaked strings should not appear anywhere in the aggregate.
        self.assertNotIn("leak", json.dumps(agg))

    def test_render_includes_judge_ragas_section(self) -> None:
        summary_with_ragas = {
            **FULL_SUMMARY,
            "judge_ragas": {
                "faithfulness": 0.92,
                "answer_relevance": 0.85,
                "context_precision": 0.78,
                "context_recall": 0.81,
                "n": 42,
            },
        }
        base = extract_aggregate(summary_with_ragas)
        head = extract_aggregate({**summary_with_ragas, "judge_ragas": {
            **summary_with_ragas["judge_ragas"],
            "faithfulness": 0.95,
        }})
        md = render_markdown(base, head, "test")
        self.assertIn("RAGAS judge", md)
        self.assertIn("faithfulness", md)
        self.assertIn("0.920", md)
        self.assertIn("0.950", md)


class CIBlockExtractTest(unittest.TestCase):
    """Bootstrap CI block (#166 leaderboard / #267 chart bands) must
    round-trip the headline-metric subset and drop unknown sub-keys
    or per-case payload smuggled in by a future maintainer."""

    SUMMARY_WITH_CI = {
        **FULL_SUMMARY,
        "ci": {
            "accuracy": {
                "mean": 0.471,
                "ci_lo": 0.286,
                "ci_hi": 0.667,
                "n": 21,
                "num_resamples": 1000,
                "alpha": 0.05,
            },
            "groundedness": {
                "mean": 0.476,
                "ci_lo": 0.286,
                "ci_hi": 0.667,
                "n": 21,
            },
            # Unknown metric — must be dropped.
            "made_up_metric": {"mean": 0.99, "ci_lo": 0.98, "ci_hi": 1.0},
            # Per-case smuggling attempt — extractor must drop the entire
            # entry because the inner shape is wrong (list, not dict).
            "case_results": [{"id": "leak", "query": "leak"}],
        },
    }

    def test_ci_block_round_trips_for_whitelisted_metrics(self) -> None:
        agg = extract_aggregate(self.SUMMARY_WITH_CI)
        ci = agg["ci"]
        self.assertIn("accuracy", ci)
        self.assertIn("groundedness", ci)
        self.assertAlmostEqual(0.286, ci["accuracy"]["ci_lo"])
        self.assertAlmostEqual(0.667, ci["accuracy"]["ci_hi"])
        self.assertEqual(21, ci["accuracy"]["n"])
        self.assertEqual(1000, ci["accuracy"]["num_resamples"])

    def test_ci_unknown_metrics_dropped(self) -> None:
        agg = extract_aggregate(self.SUMMARY_WITH_CI)
        self.assertNotIn("made_up_metric", agg["ci"])
        self.assertNotIn("case_results", agg["ci"])

    def test_ci_no_leak_strings(self) -> None:
        agg = extract_aggregate(self.SUMMARY_WITH_CI)
        self.assertNotIn("leak", json.dumps(agg))

    def test_ci_unknown_sub_keys_dropped(self) -> None:
        summary = {
            **FULL_SUMMARY,
            "ci": {
                "accuracy": {
                    "mean": 0.5,
                    "ci_lo": 0.3,
                    "ci_hi": 0.7,
                    # Smuggling attempts — must be dropped.
                    "raw_scores": [0.1, 0.2, 0.3],
                    "case_ids": ["c1", "c2"],
                }
            },
        }
        agg = extract_aggregate(summary)
        self.assertEqual(
            set(agg["ci"]["accuracy"].keys()),
            {"mean", "ci_lo", "ci_hi"},
        )

    def test_ci_omitted_when_summary_has_no_ci(self) -> None:
        agg = extract_aggregate(FULL_SUMMARY)
        self.assertNotIn("ci", agg)


class NAwareSilenceTest(unittest.TestCase):
    """Issue #463: silence band must grow as ``num_predictions`` shrinks.

    On a real eval of N=21 a single case is ±4.76 pp, so the original
    fixed 5e-4 floor silenced only rounding noise and let sub-case
    wobble look like real movement. The N-aware rule sizes the band to
    half a case.
    """

    def test_silence_threshold_falls_back_to_floor_for_unknown_n(self) -> None:
        self.assertAlmostEqual(_silence_threshold(None), 5e-4)

    def test_silence_threshold_floor_for_large_n(self) -> None:
        # 0.5 / 10000 = 5e-5 < 5e-4 floor, so the floor wins.
        self.assertAlmostEqual(_silence_threshold(10000), 5e-4)

    def test_silence_threshold_scales_for_small_n(self) -> None:
        # 0.5 / 21 ~= 0.02381
        self.assertAlmostEqual(_silence_threshold(21), 0.5 / 21)

    def test_fmt_delta_silences_sub_half_case_on_small_n(self) -> None:
        # delta = 0.010 is well under 0.5/21 ~ 0.024 → ·
        self.assertEqual(_fmt_delta(0.50, 0.51, True, n_min=21), "·")

    def test_fmt_delta_surfaces_above_half_case_on_small_n(self) -> None:
        # delta = 0.050 > 0.024 → renders with direction arrow
        rendered = _fmt_delta(0.50, 0.55, True, n_min=21)
        self.assertIn("+0.050", rendered)
        self.assertIn("✅", rendered)

    def test_fmt_delta_silences_below_floor_when_n_omitted(self) -> None:
        # Back-compat: callers without n_min still observe the 5e-4 floor.
        self.assertEqual(_fmt_delta(0.500, 0.5003, True), "·")
        rendered = _fmt_delta(0.500, 0.5010, True)
        self.assertIn("+0.001", rendered)

    def test_min_num_predictions_handles_missing_and_invalid(self) -> None:
        self.assertIsNone(_min_num_predictions({}, {}))
        self.assertIsNone(
            _min_num_predictions({"num_predictions": -1}, {"num_predictions": 0})
        )
        self.assertEqual(
            _min_num_predictions({"num_predictions": 42}, {"num_predictions": 21}),
            21,
        )


class BaseHeadCIRenderTest(unittest.TestCase):
    """Issue #463: surface single-run bootstrap CI next to base/head
    values so reviewers can eyeball whether a delta sits inside the
    noise band. The CI block is already aggregate-safe per ADR 0005."""

    SUMMARY_WITH_CI = {
        **FULL_SUMMARY,
        "ci": {
            "accuracy": {
                "mean": 0.471,
                "ci_lo": 0.235,
                "ci_hi": 0.706,
                "n": 21,
                "num_resamples": 1000,
            }
        },
    }

    def test_render_includes_ci_bracket_for_metric_with_ci(self) -> None:
        base = extract_aggregate(self.SUMMARY_WITH_CI)
        head = extract_aggregate({**self.SUMMARY_WITH_CI, "accuracy": 0.6})
        md = render_markdown(base, head, "test")
        # Bracketed CI appears next to the value.
        self.assertIn("[0.235, 0.706]", md)

    def test_render_skips_ci_bracket_for_dotted_path(self) -> None:
        # latency.p50 has no `ci` block under its dotted path; render
        # must not invent one.
        base = extract_aggregate(self.SUMMARY_WITH_CI)
        head = extract_aggregate({**self.SUMMARY_WITH_CI, "accuracy": 0.6})
        md = render_markdown(base, head, "test")
        # latency_p50_ms row should not have a [lo, hi] bracket on it.
        # We assert the value 100.000 (base latency p50) is not followed
        # by a bracket.
        self.assertNotIn("100.000 [", md)

    def test_render_omits_bracket_when_ci_absent(self) -> None:
        base = extract_aggregate(FULL_SUMMARY)
        head = extract_aggregate({**FULL_SUMMARY, "accuracy": 0.6})
        md = render_markdown(base, head, "test")
        # No CI block in FULL_SUMMARY → no brackets.
        self.assertNotIn("[0.", md)

    def test_render_shows_silence_band_header_when_n_known(self) -> None:
        base = extract_aggregate(self.SUMMARY_WITH_CI)
        head = extract_aggregate({**self.SUMMARY_WITH_CI, "accuracy": 0.6})
        md = render_markdown(base, head, "test")
        self.assertIn("silence band", md)
        self.assertIn("N=21", md)


class AbstentionOutcomeBreakdownTest(unittest.TestCase):
    """Issue #463: intended-abstention bimodality (0/1) collapsed two
    distinct failure modes (hallucination vs ambiguous boundary).
    The 3-bin breakdown surfaces them separately while staying within
    the ADR 0005 aggregate-only commit boundary."""

    SUMMARY_WITH_OUTCOMES = {
        **FULL_SUMMARY,
        "abstention_outcomes": {
            "correct_refusal": 2,
            "incorrect_answer": 1,
            "boundary_partial": 1,
        },
        "by_query_type": {
            **FULL_SUMMARY["by_query_type"],
            "abstention": {
                "num_predictions": 4,
                "abstention": 0.5,
                "abstention_outcomes": {
                    "correct_refusal": 2,
                    "incorrect_answer": 1,
                    "boundary_partial": 1,
                },
            },
        },
    }

    def test_outcomes_round_trip_at_top_level(self) -> None:
        agg = extract_aggregate(self.SUMMARY_WITH_OUTCOMES)
        self.assertIn("abstention_outcomes", agg)
        outcomes = agg["abstention_outcomes"]
        self.assertEqual(outcomes["correct_refusal"], 2)
        self.assertEqual(outcomes["incorrect_answer"], 1)
        self.assertEqual(outcomes["boundary_partial"], 1)
        for value in outcomes.values():
            self.assertIsInstance(value, int)

    def test_outcomes_round_trip_in_slice(self) -> None:
        agg = extract_aggregate(self.SUMMARY_WITH_OUTCOMES)
        slice_payload = agg["by_query_type"]["abstention"]
        self.assertIn("abstention_outcomes", slice_payload)
        self.assertEqual(slice_payload["abstention_outcomes"]["correct_refusal"], 2)

    def test_outcomes_extractor_drops_unknown_bin_keys(self) -> None:
        summary = {
            **FULL_SUMMARY,
            "abstention_outcomes": {
                "correct_refusal": 2,
                "incorrect_answer": 1,
                "boundary_partial": 1,
                # Smuggling attempt — must be dropped.
                "case_results": [{"id": "leak", "query": "leak"}],
                "made_up_bin": 99,
            },
        }
        agg = extract_aggregate(summary)
        outcomes = agg["abstention_outcomes"]
        self.assertEqual(set(outcomes.keys()), set(SAFE_ABSTENTION_OUTCOME_KEYS))
        self.assertNotIn("made_up_bin", outcomes)
        self.assertNotIn("leak", json.dumps(agg))

    def test_outcomes_in_slice_drops_unknown_keys(self) -> None:
        summary = {
            **FULL_SUMMARY,
            "by_query_type": {
                "abstention": {
                    "num_predictions": 4,
                    "abstention_outcomes": {
                        "correct_refusal": 1,
                        "case_results": [{"id": "leak"}],
                    },
                }
            },
        }
        agg = extract_aggregate(summary)
        slice_outcomes = agg["by_query_type"]["abstention"]["abstention_outcomes"]
        self.assertEqual(set(slice_outcomes.keys()), {"correct_refusal"})
        self.assertNotIn("leak", json.dumps(agg))

    def test_render_includes_outcome_breakdown_table(self) -> None:
        base = extract_aggregate(self.SUMMARY_WITH_OUTCOMES)
        head = extract_aggregate(
            {
                **self.SUMMARY_WITH_OUTCOMES,
                "by_query_type": {
                    **self.SUMMARY_WITH_OUTCOMES["by_query_type"],
                    "abstention": {
                        "num_predictions": 4,
                        "abstention": 0.75,
                        "abstention_outcomes": {
                            "correct_refusal": 3,
                            "incorrect_answer": 0,
                            "boundary_partial": 1,
                        },
                    },
                },
            }
        )
        md = render_markdown(base, head, "test")
        self.assertIn("Abstention outcome breakdown", md)
        for key in SAFE_ABSTENTION_OUTCOME_KEYS:
            self.assertIn(key, md)


class FullScriptInvocationTest(unittest.TestCase):
    """Smoke-test the full script end-to-end via subprocess so the
    CLI argument plumbing is exercised."""

    def test_end_to_end_renders_table(self) -> None:
        import subprocess
        import sys

        with TemporaryDirectory() as tmp:
            base_path = Path(tmp) / "base.json"
            head_path = Path(tmp) / "head.json"
            base_path.write_text(json.dumps(FULL_SUMMARY))
            # Mutate head accuracy upward.
            head_path.write_text(json.dumps({**FULL_SUMMARY, "accuracy": 0.6}))
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_real_eval_delta.py",
                    "--base",
                    str(base_path),
                    "--head",
                    str(head_path),
                    "--title",
                    "smoke",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("smoke", result.stdout)
            self.assertIn("accuracy", result.stdout)
            self.assertIn("0.471", result.stdout)
            self.assertIn("0.600", result.stdout)
            self.assertIn("+0.129", result.stdout)
            # Privacy assertion at the CLI boundary:
            for leak in ["real_secret_case", "진짜 비공개", "private_doc_1"]:
                self.assertNotIn(leak, result.stdout)


if __name__ == "__main__":
    unittest.main()
