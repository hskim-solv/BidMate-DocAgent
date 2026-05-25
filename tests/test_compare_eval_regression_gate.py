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

import hashlib
import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _eval_delta import (  # noqa: E402
    ABSTENTION_OUTCOME_RATE_THRESHOLD,
    detect_abstention_outcome_regressions,
    detect_regressions,
    fmt_delta,
    min_num_predictions,
    silence_threshold,
)
from compare_eval import (  # noqa: E402
    classify_eval_surface,
    missing_required_provenance,
    provenance_mismatches,
)


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


def _provenanced_summary(**overrides: object) -> dict:
    summary = dict(
        _base_summary(),
        benchmark_type="public_fixture_smoke_regression",
        provenance={
            "git_commit": "abc123def456",
            "git_dirty": False,
            "generated_at": "2026-05-25T00:00:00Z",
        },
        run_manifest={
            "git_commit": "abc123def456",
            "git_dirty": False,
            "config_sha256": "cfg1111111111111",
            "embedding_backend": "hashing",
            "embedding_model_id": "hashing",
            "generated_at": "2026-05-25T00:00:00Z",
        },
        dataset_summary={
            "id": "public-fixture-smoke-v1",
            "num_questions": 42,
            "num_docs": 5,
            "num_chunks": 100,
        },
    )
    summary.update(overrides)
    return summary


def _path_label(value: str) -> str:
    return f"{Path(value).name}#{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"


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


class SilenceBandTest(unittest.TestCase):
    """Issue #463: ``fmt_delta`` silences sub-rounding noise on large N
    but widens the band to half a case width when N is small, so 1-case
    wobble on a tiny eval doesn't look like real signal."""

    def test_silence_threshold_floor_when_n_omitted(self) -> None:
        self.assertAlmostEqual(silence_threshold(None), 5e-4)

    def test_silence_threshold_floor_for_large_n(self) -> None:
        self.assertAlmostEqual(silence_threshold(10000), 5e-4)

    def test_silence_threshold_scales_for_small_n(self) -> None:
        self.assertAlmostEqual(silence_threshold(42), 0.5 / 42)
        self.assertAlmostEqual(silence_threshold(21), 0.5 / 21)

    def test_fmt_delta_silences_below_band_with_n_min(self) -> None:
        # 0.5 / 21 ~= 0.024; a 0.010 delta sits below it.
        self.assertEqual(fmt_delta(0.50, 0.51, True, n_min=21), "·")

    def test_fmt_delta_surfaces_above_band_with_n_min(self) -> None:
        rendered = fmt_delta(0.50, 0.55, True, n_min=21)
        self.assertIn("+0.050", rendered)
        self.assertIn("✅", rendered)

    def test_fmt_delta_back_compat_without_n_min(self) -> None:
        # Existing callers without n_min keep the original 5e-4 floor.
        self.assertEqual(fmt_delta(0.500, 0.5002, True), "·")
        self.assertIn("+0.001", fmt_delta(0.500, 0.5010, True))

    def test_min_num_predictions_picks_smaller_side(self) -> None:
        self.assertEqual(
            min_num_predictions(
                {"num_predictions": 42}, {"num_predictions": 21}
            ),
            21,
        )
        self.assertIsNone(min_num_predictions({}, None))


class AbstentionOutcomeRegressionTest(unittest.TestCase):
    """Issue #624 — abstention 3-bin composition gate."""

    def _outcomes(self, cr: int, ia: int, bp: int) -> dict:
        base = _base_summary()
        base["abstention_outcomes"] = {
            "correct_refusal": cr,
            "incorrect_answer": ia,
            "boundary_partial": bp,
        }
        return base

    def test_identical_outcomes_no_regression(self) -> None:
        s = self._outcomes(6, 16, 0)
        self.assertEqual(detect_abstention_outcome_regressions(s, s), [])

    def test_ia_increase_beyond_threshold_is_regression(self) -> None:
        # base: IA=16/22 ≈ 0.727; head: IA=20/22 ≈ 0.909 → Δ≈+0.182 > 0.10
        base = self._outcomes(6, 16, 0)
        head = self._outcomes(2, 20, 0)
        regressions = detect_abstention_outcome_regressions(base, head)
        labels = [r["metric"] for r in regressions]
        self.assertIn("abstention: incorrect_answer_rate", labels)

    def test_cr_decrease_beyond_threshold_is_regression(self) -> None:
        # base: CR=10/20 = 0.50; head: CR=1/20 = 0.05 → Δ=-0.45 < -0.10
        base = self._outcomes(10, 10, 0)
        head = self._outcomes(1, 19, 0)
        regressions = detect_abstention_outcome_regressions(base, head)
        labels = [r["metric"] for r in regressions]
        self.assertIn("abstention: correct_refusal_rate", labels)

    def test_abstention_rate_flat_but_ia_grows_is_regression(self) -> None:
        # Overall abstention stays same; IA grows from 50% to 90% of abstentions.
        base = self._outcomes(cr=5, ia=5, bp=0)   # ia_rate = 0.50
        head = self._outcomes(cr=1, ia=9, bp=0)   # ia_rate = 0.90 → Δ=+0.40
        regressions = detect_abstention_outcome_regressions(base, head)
        self.assertTrue(len(regressions) > 0)

    def test_small_ia_shift_within_threshold_no_regression(self) -> None:
        # Δ ia_rate = 0.05 < ABSTENTION_OUTCOME_RATE_THRESHOLD = 0.10 → pass
        base = self._outcomes(cr=10, ia=10, bp=0)   # ia_rate = 0.50
        head = self._outcomes(cr=9, ia=11, bp=0)    # ia_rate = 0.55 → Δ=+0.05
        self.assertEqual(detect_abstention_outcome_regressions(base, head), [])

    def test_missing_abstention_outcomes_skips_silently(self) -> None:
        base = _base_summary()
        head = _base_summary()
        self.assertEqual(detect_abstention_outcome_regressions(base, head), [])

    def test_zero_total_skips_silently(self) -> None:
        base = self._outcomes(0, 0, 0)
        head = self._outcomes(0, 0, 0)
        self.assertEqual(detect_abstention_outcome_regressions(base, head), [])


class EvalSurfaceClassificationTest(unittest.TestCase):
    def test_classifies_repo_relative_public_smoke_path(self) -> None:
        self.assertEqual(
            classify_eval_surface({}, path="reports/eval_summary.json"),
            "public_fixture_smoke",
        )

    def test_classifies_repo_relative_private_real_eval_path(self) -> None:
        self.assertEqual(
            classify_eval_surface({}, path="reports/real100/eval_summary.json"),
            "private_real_eval",
        )

    def test_classifies_repo_relative_harness_path(self) -> None:
        self.assertEqual(
            classify_eval_surface({}, path="artifacts/runs/run-1/metrics/eval_summary.json"),
            "harness_run",
        )


class EvalProvenanceTest(unittest.TestCase):
    def test_missing_required_provenance_reports_run_config_index(self) -> None:
        self.assertEqual(
            missing_required_provenance(_base_summary()),
            ["run", "config", "index", "dataset"],
        )

    def test_unknown_sentinel_does_not_count_as_present_provenance(self) -> None:
        summary = dict(
            _base_summary(),
            provenance={"git_commit": "unknown"},
            run_manifest={
                "config_sha256": "unknown",
                "embedding_backend": "unknown",
                "embedding_model_id": "unknown",
            },
            dataset={"id": "unknown"},
        )
        self.assertEqual(
            missing_required_provenance(summary),
            ["run", "config", "index", "dataset"],
        )

    def test_dataset_counts_without_identity_do_not_satisfy_required_provenance(self) -> None:
        summary = _provenanced_summary(
            dataset_summary={
                "num_questions": 42,
                "num_docs": 5,
                "num_chunks": 100,
            }
        )

        self.assertEqual(missing_required_provenance(summary), ["dataset"])

    def test_provenance_mismatch_ignores_run_commit_but_compares_config_index_dataset(self) -> None:
        base = _provenanced_summary(
            provenance={
                "git_commit": "basecommit",
                "generated_at": "2026-05-25T00:00:00Z",
            },
            run_manifest={
                "git_commit": "basecommit",
                "config_sha256": "cfg-base",
                "embedding_backend": "hashing",
                "embedding_model_id": "hashing",
            },
        )
        head = _provenanced_summary(
            provenance={
                "git_commit": "headcommit",
                "generated_at": "2026-05-25T01:00:00Z",
            },
            run_manifest={
                "git_commit": "headcommit",
                "config_sha256": "cfg-head",
                "embedding_backend": "sentence-transformers",
                "embedding_model_id": "model-v2",
            },
            dataset_summary={
                "id": "public-fixture-smoke-v2",
                "num_questions": 41,
                "num_docs": 5,
                "num_chunks": 100,
            },
        )
        mismatches = provenance_mismatches(base, head)
        self.assertEqual(set(mismatches), {"config", "index", "dataset"})
        self.assertNotIn("run", mismatches)

    def test_dataset_aliases_participate_in_provenance_mismatch(self) -> None:
        base = _provenanced_summary(
            dataset_summary={
                "id": "public-fixture-smoke-v1",
                "question_count": 42,
                "corpus_size": 5,
                "chunk_count": 100,
            }
        )
        head = _provenanced_summary(
            dataset_summary={
                "id": "public-fixture-smoke-v1",
                "question_count": 42,
                "corpus_size": 5,
                "chunk_count": 101,
            }
        )
        self.assertEqual(set(provenance_mismatches(base, head)), {"dataset"})

    def test_same_basename_paths_still_participate_in_provenance_mismatch(self) -> None:
        base = _provenanced_summary(
            run_manifest={
                "git_commit": "abc123def456",
                "git_dirty": False,
                "config_path": "/private/base/config.yaml",
                "embedding_backend": "hashing",
                "embedding_model_id": "hashing",
            },
        )
        head = _provenanced_summary(
            run_manifest={
                "git_commit": "abc123def456",
                "git_dirty": False,
                "config_path": "/private/head/config.yaml",
                "embedding_backend": "hashing",
                "embedding_model_id": "hashing",
            },
        )

        mismatches = provenance_mismatches(base, head)

        self.assertEqual(set(mismatches), {"config"})
        self.assertIn("config.yaml#", mismatches["config"][0])
        self.assertIn("config.yaml#", mismatches["config"][1])


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

    def test_scope_note_renders_under_title(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = self._run(
                Path(td),
                _base_summary(),
                _base_summary(),
                scope_note="Scope: public fixture smoke only.",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### Test\n\n> Scope: public fixture smoke only.", result.stdout)

    def test_surface_classification_renders_in_default_output(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = self._run(Path(td), _base_summary(), _base_summary())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- surface: base=`unknown_eval_summary` · head=`unknown_eval_summary`", result.stdout)

    def test_surface_mismatch_warning_is_non_blocking_by_default(self) -> None:
        import tempfile
        base = dict(_base_summary(), benchmark_type="private_real_eval")
        head = dict(_base_summary(), benchmark_type="naive_rag_benchmark")
        with tempfile.TemporaryDirectory() as td:
            result = self._run(Path(td), base, head, regression_threshold=0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("base=`private_real_eval` · head=`public_synthetic_benchmark`", result.stdout)
        self.assertIn("Surface mismatch", result.stdout)

    def test_surface_mismatch_can_fail_closed(self) -> None:
        import tempfile
        base = dict(_base_summary(), benchmark_type="private_real_eval")
        head = dict(_base_summary(), benchmark_type="naive_rag_benchmark")
        with tempfile.TemporaryDirectory() as td:
            result = self._run(
                Path(td),
                base,
                head,
                regression_threshold=0,
                fail_on_surface_mismatch=True,
            )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Surface mismatch", result.stdout)

    def test_missing_provenance_can_fail_closed(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = self._run(
                Path(td),
                _base_summary(),
                _base_summary(),
                regression_threshold=0,
                fail_on_missing_provenance=True,
            )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Missing provenance", result.stdout)
        self.assertIn("base missing `run`, `config`, `index`, `dataset`", result.stdout)

    def test_provenance_mismatch_can_fail_closed(self) -> None:
        import tempfile
        base = _provenanced_summary()
        head = _provenanced_summary(
            run_manifest={
                "git_commit": "abc123def456",
                "git_dirty": False,
                "config_sha256": "cfg2222222222222",
                "embedding_backend": "hashing",
                "embedding_model_id": "hashing",
                "generated_at": "2026-05-25T00:00:00Z",
            }
        )
        with tempfile.TemporaryDirectory() as td:
            result = self._run(
                Path(td),
                base,
                head,
                regression_threshold=0,
                fail_on_provenance_mismatch=True,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Provenance mismatch", result.stdout)
        self.assertIn(
            "`config` base=`sha=cfg1111111111111` "
            "head=`sha=cfg2222222222222`",
            result.stdout,
        )

    def test_provenance_renders_before_metric_table_and_redacts_paths(self) -> None:
        import tempfile
        base = dict(
            _base_summary(),
            provenance={"generated_at": "2026-05-25T00:00:00Z"},
            run_manifest={
                "config_path": "/Users/hskim/private/real_config.local.yaml",
                "embedding_backend": "local",
                "embedding_model_id": "data/private/model.bin",
                "generated_at": "2026-05-25T00:00:00Z",
            },
            dataset_path="file:///Users/hskim/private/questions.jsonl",
        )
        head = dict(base)
        with tempfile.TemporaryDirectory() as td:
            result = self._run(Path(td), base, head, regression_threshold=0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(
            result.stdout.index("- provenance(base):"),
            result.stdout.index("| metric |"),
        )
        self.assertIn(
            f"config=`path={_path_label('/Users/hskim/private/real_config.local.yaml')}`",
            result.stdout,
        )
        self.assertIn("index=`embedding=local/model.bin`", result.stdout)
        self.assertIn(
            f"dataset=`path={_path_label('file:///Users/hskim/private/questions.jsonl')}`",
            result.stdout,
        )
        self.assertNotIn("/Users/hskim/private", result.stdout)
        self.assertNotIn("data/private", result.stdout)

    def test_unknown_surface_does_not_fail_closed_against_known_surface(self) -> None:
        import tempfile
        base = _base_summary()
        head = dict(_base_summary(), benchmark_type="private_real_eval")
        with tempfile.TemporaryDirectory() as td:
            result = self._run(
                Path(td),
                base,
                head,
                regression_threshold=0,
                fail_on_surface_mismatch=True,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("base=`unknown_eval_summary` · head=`private_real_eval`", result.stdout)
        self.assertNotIn("Surface mismatch", result.stdout)

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
