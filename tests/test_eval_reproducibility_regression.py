"""Reproducibility regression guard for the public synthetic eval pipeline.

Issue #160 surfaced two coupled problems with `make real-eval-delta`:
the policy gate that flags #69-class intended-abstention regressions
could not be trusted because (a) the committed baseline drifted from
git, and (b) re-running real-eval at the *same* commit produced
different aggregate metrics and even different slice keys
(``by_query_type.multi_doc`` → ``by_query_type.comparison``).

This test exercises the analogous public-synthetic pipeline ×2 against
an identical index, and asserts byte-equivalence of the aggregate
metrics and slice keys that the real-data delta gate consumes. If a
future change reintroduces ordering non-determinism (a sort missing a
tie-breaker, a dict iteration leaking into output, etc.) or a silent
slice-key rename, this test fails before the real-data baseline gets
quietly invalidated.

Notes:

* Uses the hashing embedding backend (default for ``scripts/build_index.py``
  when no backend is specified — see CLAUDE.md ``EMBEDDING_BACKEND=hashing``)
  so embedding output is deterministic.
* Uses a minimal inline config (one ``naive_baseline`` ablation_run, three
  cases — one per slice key) so the full ×2 cycle fits inside the default
  test budget.
* The full ``eval/config.yaml`` covers eight ablation runs across all
  cases; running that ×2 would be too slow for the regression layer.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]


# A minimal eval config that exercises the three slice keys most
# relevant to the #69/#160 intended-abstention regression class:
# ``single_doc``, ``comparison``, ``abstention``. The pipeline is
# ``naive_baseline`` (ADR 0001) for speed — it is the simplest path
# and still goes through the slice-classification + summary-write
# code that the bug surfaced.
MINIMAL_CONFIG = {
    "mode": "rag",
    "description": "Reproducibility regression — minimal slice coverage",
    "primary_run": "naive_baseline",
    "answer_policy": {
        "answerable_status": "supported",
        "unanswerable_status": "insufficient",
        "min_claims_answerable": 1,
        "require_claim_citations": True,
    },
    "ablation_runs": [
        {"name": "naive_baseline", "pipeline": "naive_baseline"},
    ],
    "cases": [
        {
            "id": "single_doc_security",
            "query_type": "single_doc",
            "query": "기관 A의 보안 통제 요구사항은?",
            "expected_doc_ids": ["rfp-agency-a-ai-quality"],
            "expected_terms": ["보안 통제"],
            "expected_citation_terms": ["보안 통제"],
            "answerable": True,
        },
        {
            "id": "comparison_ai_requirements",
            "query_type": "comparison",
            "query": "기관 A와 기관 B의 AI 요구사항 차이 알려줘",
            "expected_doc_ids": [
                "rfp-agency-a-ai-quality",
                "rfp-agency-b-mlops-governance",
            ],
            "expected_terms": ["MLOps", "품질관리"],
            "expected_citation_terms": ["MLOps"],
            "answerable": True,
        },
        {
            "id": "abstention_missing_blockchain",
            "query_type": "abstention",
            "query": "기관 A의 블록체인 납품 실적은?",
            "expected_doc_ids": [],
            "expected_terms": ["블록체인"],
            "answerable": False,
        },
    ],
}


# Metric fields that must be reproducible at the same commit. Excludes
# `provenance.generated_at` (timestamp differs per run by design).
REPRODUCIBLE_METRICS = (
    "accuracy",
    "groundedness",
    "citation_precision",
    "abstention",
    "answer_format_compliance",
)


def _run_eval(index_dir: Path, output_dir: Path, config_path: Path) -> dict:
    """Invoke eval/run_eval.py as a subprocess and return the parsed summary.

    Uses subprocess (rather than direct import) to exercise the same
    code path that `make real-eval` / `make eval` invoke — so any
    ordering leak through argparse, sys.path init, or environment
    propagation is caught.
    """
    result = subprocess.run(
        [
            sys.executable,
            "eval/run_eval.py",
            "--index_dir",
            str(index_dir),
            "--output_dir",
            str(output_dir),
            "--config",
            str(config_path),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"eval/run_eval.py exited {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return json.loads((output_dir / "eval_summary.json").read_text(encoding="utf-8"))


class EvalReproducibilityRegressionTest(unittest.TestCase):
    """Guard against the #160 failure mode on the public synthetic surface."""

    @classmethod
    def setUpClass(cls) -> None:
        import yaml

        cls._tmp = TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.index_dir = tmp / "index"
        cls.output_dir_a = tmp / "out_a"
        cls.output_dir_b = tmp / "out_b"
        cls.config_path = tmp / "config.yaml"
        cls.config_path.write_text(
            yaml.safe_dump(MINIMAL_CONFIG, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        # Build the index once with the deterministic hashing backend.
        # Both eval runs share this index so any reproducibility skew
        # is isolated to the eval pipeline, not the index build.
        build_result = subprocess.run(
            [
                sys.executable,
                "scripts/build_index.py",
                "--input_dir",
                "data/raw",
                "--output_dir",
                str(cls.index_dir),
                "--embedding_backend",
                "hashing",
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        if build_result.returncode != 0:
            raise AssertionError(
                f"scripts/build_index.py exited {build_result.returncode}.\n"
                f"stdout: {build_result.stdout}\nstderr: {build_result.stderr}"
            )

        cls.summary_a = _run_eval(cls.index_dir, cls.output_dir_a, cls.config_path)
        cls.summary_b = _run_eval(cls.index_dir, cls.output_dir_b, cls.config_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_slice_keys_match_between_runs(self) -> None:
        """Catches the #160 ``multi_doc`` → ``comparison`` rename regression
        class: if QUERY_TYPES or QUERY_TYPE_ALIASES change in a way that
        flips slice keys, this fails before the real-data baseline is
        silently invalidated.
        """
        keys_a = set((self.summary_a.get("by_query_type") or {}).keys())
        keys_b = set((self.summary_b.get("by_query_type") or {}).keys())
        self.assertEqual(
            keys_a,
            keys_b,
            f"by_query_type slice keys diverged between identical runs: "
            f"a={sorted(keys_a)} vs b={sorted(keys_b)}",
        )
        # Defensive: the slice keys must come from the QUERY_TYPES tuple
        # (post-4304b24 rename), not the legacy `multi_doc` alias.
        self.assertNotIn("multi_doc", keys_a)

    def test_num_predictions_matches_between_runs(self) -> None:
        self.assertEqual(
            self.summary_a["num_predictions"],
            self.summary_b["num_predictions"],
        )

    def test_aggregate_metrics_match_between_runs(self) -> None:
        """Hashing embedding backend is deterministic, so each metric
        should round-trip to byte-equivalent JSON. The 1e-9 tolerance is
        defensive against float-to-JSON-to-float drift.
        """
        for metric in REPRODUCIBLE_METRICS:
            a = self.summary_a.get(metric)
            b = self.summary_b.get(metric)
            if a is None and b is None:
                continue
            self.assertIsNotNone(
                a, f"Run A missing metric {metric!r}"
            )
            self.assertIsNotNone(
                b, f"Run B missing metric {metric!r}"
            )
            self.assertAlmostEqual(
                float(a),
                float(b),
                delta=1e-9,
                msg=f"metric {metric!r} diverged: a={a} vs b={b}",
            )

    def test_slice_metrics_match_between_runs(self) -> None:
        """Per-slice metrics drive the ``make real-eval-delta`` slice
        rendering and are the most sensitive to retrieval-ordering drift
        (the RRF tie-breaker fix in this PR pre-empts one such source).
        """
        slices_a = self.summary_a.get("by_query_type") or {}
        slices_b = self.summary_b.get("by_query_type") or {}
        for slice_name in slices_a:
            self.assertIn(slice_name, slices_b)
            for metric in ("num_predictions", "accuracy", "abstention"):
                a = (slices_a[slice_name] or {}).get(metric)
                b = (slices_b[slice_name] or {}).get(metric)
                if a is None and b is None:
                    continue
                self.assertEqual(
                    a,
                    b,
                    f"slice {slice_name!r} metric {metric!r} diverged: "
                    f"a={a} vs b={b}",
                )

    def test_provenance_block_present(self) -> None:
        """PR 1 of #160 adds a provenance block to eval_summary.json so
        the eval-vs-baseline commit skew that caused #160 becomes
        self-diagnosing. This test pins the contract.
        """
        for label, summary in (("a", self.summary_a), ("b", self.summary_b)):
            self.assertIn("provenance", summary, f"run {label} missing provenance")
            prov = summary["provenance"]
            self.assertIn("git_commit", prov)
            self.assertIn("git_dirty", prov)
            self.assertIn("generated_at", prov)
            # git_commit must be a string (12-char SHA or "unknown").
            self.assertIsInstance(prov["git_commit"], str)


if __name__ == "__main__":
    unittest.main()
