"""Regression tests for the distinguishing-power gauge (issue #945, ADR 0053).

The script (``scripts/distinguishing_power.py``) is the "is the signal alive"
gauge from ADR 0053 §Consequences. These tests lock in:

1. **Math**: ``(default - floor) / (1 - floor)`` formula correctness on
   hand-computable fixtures.
2. **Schema**: the output JSON has the exact shape PR-D (README auto-regen)
   will consume.
3. **Verdict logic (CI-aware, ADR 0053 amendment, #1367 F1)**: ``signal_state``
   is ``alive`` only when default beats BOTH floors on point gap AND its 95% CI
   is strictly above both floors' CIs. A positive gap with overlapping/absent CI
   is ``uncertain``; ``gap <= 0`` against either floor is ``dead``.
   ``signal_alive == (signal_state == "alive")`` — the gauge no longer
   over-claims on noise.
4. **Missing-data tolerance**: floors with ``None`` for a metric produce
   ``signal_state: "n/a"`` and ``gap: None`` rather than raising.
5. **Required-runs validation**: missing one of the 3 ablations exits
   non-zero with a useful error message (not a stack trace).
6. **Provenance (#1367 F2)**: the aggregate propagates the source eval_summary's
   ``provenance`` + ``run_manifest``; ``check_provenance_skew`` warns when those
   are absent / stale-vs-HEAD / dirty.

The fixtures are inline dicts — no real eval_summary.json read — so these
tests are stable against future schema additions and have zero runtime cost.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.distinguishing_power import (
    DEFAULT_RUN,
    FLOOR_RUNS,
    GAUGED_METRICS,
    REQUIRED_RUNS,
    check_provenance_skew,
    compute_gauge,
    main,
    render_markdown,
)


def _ci(metric_to_bounds: dict[str, tuple[float, float]]) -> dict[str, dict]:
    """Build a per-run ``ci`` block from ``{metric: (ci_lo, ci_hi)}`` pairs."""
    return {
        metric: {
            "ci_lo": lo,
            "ci_hi": hi,
            "mean": (lo + hi) / 2,
            "n": 118,
            "num_resamples": 1000,
            "alpha": 0.05,
        }
        for metric, (lo, hi) in metric_to_bounds.items()
    }


def _make_summary(
    full: dict[str, float | None],
    random_retrieval: dict[str, float | None],
    single_chunk: dict[str, float | None],
    n: int = 221,
    full_ci: dict[str, dict] | None = None,
    random_ci: dict[str, dict] | None = None,
    single_ci: dict[str, dict] | None = None,
    ci_n: dict[str, dict[str, int]] | None = None,
    provenance: dict | None = None,
    run_manifest: dict | None = None,
) -> dict:
    """Build a minimal eval_summary.json shape with 3 ablation runs.

    ``*_ci`` blocks (per-metric ``{ci_lo, ci_hi, ...}``) are optional — when
    absent the gauge cannot assess CI separation and reports ``signal_state``
    as ``uncertain`` for any positive-gap metric (#1367 F1).

    ``ci_n`` (optional) attaches per-(metric, run) ``n`` denominators into the
    same ``ci`` block — mirrors the real eval_summary shape so tests can assert
    the ADR 0054 per-metric denominator disclosure (#1368). Omitting both keeps
    the legacy (ci-less) fixture shape that the older tests rely on.
    """

    def _run(name: str, values: dict[str, float | None], ci: dict | None) -> dict:
        run: dict = {
            "name": name,
            "num_predictions": n,
            **values,
        }
        if ci is not None:
            run["ci"] = ci
        if ci_n and name in ci_n:
            block = run.setdefault("ci", {})
            for metric, cnt in ci_n[name].items():
                block.setdefault(metric, {})["n"] = cnt
        return run

    summary: dict = {
        "num_predictions": n,
        "ablation": {
            "runs": [
                _run("full", full, full_ci),
                _run("random_retrieval", random_retrieval, random_ci),
                _run("single_chunk", single_chunk, single_ci),
            ]
        },
    }
    if provenance is not None:
        summary["provenance"] = provenance
    if run_manifest is not None:
        summary["run_manifest"] = run_manifest
    return summary


class GaugeMathTest(unittest.TestCase):
    """The (default - floor) / (1 - floor) formula on hand-computable inputs."""

    def test_perfect_signal(self) -> None:
        # Wide-apart, non-overlapping CIs → CI-separated from both floors → alive.
        summary = _make_summary(
            full={m: 0.50 for m in GAUGED_METRICS},
            random_retrieval={m: 0.10 for m in GAUGED_METRICS},
            single_chunk={m: 0.20 for m in GAUGED_METRICS},
            full_ci=_ci({m: (0.45, 0.55) for m in GAUGED_METRICS}),
            random_ci=_ci({m: (0.05, 0.15) for m in GAUGED_METRICS}),
            single_ci=_ci({m: (0.15, 0.25) for m in GAUGED_METRICS}),
        )
        g = compute_gauge(summary)
        for metric in GAUGED_METRICS:
            cell = g["gauge"][metric]
            self.assertAlmostEqual(cell["vs_random"]["gap"], 0.40, places=6)
            # (0.50 - 0.10) / (1 - 0.10) == 0.4444...
            self.assertAlmostEqual(
                cell["vs_random"]["normalized"], 0.40 / 0.90, places=6
            )
            self.assertAlmostEqual(cell["vs_single"]["gap"], 0.30, places=6)
            self.assertAlmostEqual(
                cell["vs_single"]["normalized"], 0.30 / 0.80, places=6
            )
            self.assertTrue(cell["vs_random"]["ci_separated"])
            self.assertTrue(cell["vs_single"]["ci_separated"])
            self.assertEqual("alive", cell["signal_state"])
            self.assertTrue(cell["signal_alive"])

    def test_dead_signal_below_random(self) -> None:
        # default LOSES to random — random_retrieval beats real pipeline.
        # This is the Goodhart warning state the gauge exists to surface.
        summary = _make_summary(
            full={m: 0.10 for m in GAUGED_METRICS},
            random_retrieval={m: 0.30 for m in GAUGED_METRICS},
            single_chunk={m: 0.05 for m in GAUGED_METRICS},
        )
        g = compute_gauge(summary)
        for metric in GAUGED_METRICS:
            cell = g["gauge"][metric]
            self.assertLess(cell["vs_random"]["gap"], 0)
            self.assertEqual("dead", cell["signal_state"])
            self.assertFalse(
                cell["signal_alive"],
                f"{metric}: default 0.10 < random 0.30 must mark signal dead",
            )

    def test_partial_signal_only_beats_single(self) -> None:
        # Beats single_chunk but loses to random — ADR 0053 strict version
        # still says signal_alive=False (both floors must be beaten).
        summary = _make_summary(
            full={m: 0.15 for m in GAUGED_METRICS},
            random_retrieval={m: 0.20 for m in GAUGED_METRICS},
            single_chunk={m: 0.05 for m in GAUGED_METRICS},
        )
        g = compute_gauge(summary)
        for metric in GAUGED_METRICS:
            cell = g["gauge"][metric]
            self.assertGreater(cell["vs_single"]["gap"], 0)
            self.assertLess(cell["vs_random"]["gap"], 0)
            self.assertEqual("dead", cell["signal_state"])
            self.assertFalse(cell["signal_alive"])


class SchemaTest(unittest.TestCase):
    """Output JSON shape is the contract PR-D (README auto-regen) will read."""

    def test_top_level_keys(self) -> None:
        summary = _make_summary(
            full={m: 0.5 for m in GAUGED_METRICS},
            random_retrieval={m: 0.1 for m in GAUGED_METRICS},
            single_chunk={m: 0.2 for m in GAUGED_METRICS},
        )
        g = compute_gauge(summary)
        self.assertEqual(
            {"num_predictions", "provenance", "run_manifest", "runs", "gauge"},
            set(g.keys()),
        )
        self.assertEqual(set(REQUIRED_RUNS), set(g["runs"].keys()))
        self.assertEqual(set(GAUGED_METRICS), set(g["gauge"].keys()))

    def test_per_metric_keys(self) -> None:
        summary = _make_summary(
            full={m: 0.5 for m in GAUGED_METRICS},
            random_retrieval={m: 0.1 for m in GAUGED_METRICS},
            single_chunk={m: 0.2 for m in GAUGED_METRICS},
        )
        g = compute_gauge(summary)
        for metric in GAUGED_METRICS:
            cell = g["gauge"][metric]
            self.assertEqual(
                {
                    "default",
                    "default_ci",
                    "vs_random",
                    "vs_single",
                    "signal_state",
                    "signal_alive",
                },
                set(cell.keys()),
            )
            for floor_key in ("vs_random", "vs_single"):
                self.assertEqual(
                    {"gap", "normalized", "floor_ci", "ci_separated"},
                    set(cell[floor_key].keys()),
                )

    def test_floor_runs_constant_matches_decision(self) -> None:
        # ADR 0053 names exactly two floors. Lock the constant against drift.
        self.assertEqual(("random_retrieval", "single_chunk"), FLOOR_RUNS)
        self.assertEqual("full", DEFAULT_RUN)


class MissingDataTest(unittest.TestCase):
    """Tolerate ``None`` metric values (slice n=0) without crashing."""

    def test_none_floor_marks_signal_not_alive(self) -> None:
        summary = _make_summary(
            full={m: 0.5 for m in GAUGED_METRICS},
            random_retrieval={m: None for m in GAUGED_METRICS},
            single_chunk={m: 0.2 for m in GAUGED_METRICS},
        )
        g = compute_gauge(summary)
        for metric in GAUGED_METRICS:
            cell = g["gauge"][metric]
            self.assertIsNone(cell["vs_random"]["gap"])
            self.assertIsNone(cell["vs_random"]["normalized"])
            self.assertEqual("n/a", cell["signal_state"])
            self.assertFalse(cell["signal_alive"])


class CLITest(unittest.TestCase):
    """End-to-end via main() — writes both artifacts to a tmpdir."""

    def test_writes_both_artifacts(self) -> None:
        summary = _make_summary(
            full={m: 0.5 for m in GAUGED_METRICS},
            random_retrieval={m: 0.1 for m in GAUGED_METRICS},
            single_chunk={m: 0.2 for m in GAUGED_METRICS},
        )
        with TemporaryDirectory() as td:
            tdp = Path(td)
            summary_path = tdp / "eval_summary.json"
            summary_path.write_text(json.dumps(summary))
            out_md = tdp / "distinguishing_power.md"
            out_json = tdp / "distinguishing_power.aggregate.json"
            rc = main(
                [
                    "--summary",
                    str(summary_path),
                    "--out-md",
                    str(out_md),
                    "--out-json",
                    str(out_json),
                ]
            )
            self.assertEqual(0, rc)
            self.assertTrue(out_md.exists())
            self.assertTrue(out_json.exists())
            written = json.loads(out_json.read_text())
            self.assertEqual(
                {"num_predictions", "provenance", "run_manifest", "runs", "gauge"},
                set(written.keys()),
            )
            md = out_md.read_text()
            # Header + verdict section must be present.
            self.assertIn("Distinguishing-power gauge", md)
            self.assertIn("## Verdict", md)
            self.assertIn("ADR 0005", md)  # privacy-boundary footer

    def test_missing_required_run_exits_nonzero(self) -> None:
        # Drop single_chunk — script must refuse with a useful error.
        bad_summary = {
            "num_predictions": 10,
            "ablation": {
                "runs": [
                    {"name": "full", "num_predictions": 10, "accuracy": 0.5},
                    {"name": "random_retrieval", "num_predictions": 10, "accuracy": 0.1},
                ]
            },
        }
        with TemporaryDirectory() as td:
            tdp = Path(td)
            summary_path = tdp / "eval_summary.json"
            summary_path.write_text(json.dumps(bad_summary))
            with self.assertRaises(SystemExit) as ctx:
                main(["--summary", str(summary_path), "--print-only"])
            # SystemExit with the human-readable error string (not exit code 0).
            self.assertNotEqual(0, ctx.exception.code)

    def test_missing_summary_file_exits_nonzero(self) -> None:
        with TemporaryDirectory() as td:
            missing = Path(td) / "does-not-exist.json"
            with self.assertRaises(SystemExit) as ctx:
                main(["--summary", str(missing), "--print-only"])
            self.assertNotEqual(0, ctx.exception.code)


class MarkdownRenderTest(unittest.TestCase):
    """Render output is human-readable and surfaces the warning state."""

    def test_warning_glyph_appears_for_dead_signal(self) -> None:
        summary = _make_summary(
            full={m: 0.10 for m in GAUGED_METRICS},
            random_retrieval={m: 0.30 for m in GAUGED_METRICS},
            single_chunk={m: 0.05 for m in GAUGED_METRICS},
        )
        g = compute_gauge(summary)
        md = render_markdown(g)
        # The verdict line uses the warning glyph + 'NOT alive' phrase.
        self.assertIn("⚠️", md)
        self.assertIn("signal NOT alive", md)


class PerMetricDenominatorTest(unittest.TestCase):
    """ADR 0054 — gauge discloses per-(metric, run) CI n (issue #1368).

    The quality metrics are conditional on a substantive answer attempt, so
    accuracy/groundedness/citation_precision carry a smaller denominator (118
    in the real run) than answer_format_compliance (199) and
    claim_citation_alignment (173), which stay measurable on over-answered /
    answered cases. The gauge must surface this divergence rather than imply
    every quality metric shares the single per-run effective_n.
    """

    # Mirrors the real baseline.aggregate.json denominator divergence.
    _CI_N = {
        "full": {
            "accuracy": 118,
            "groundedness": 118,
            "citation_precision": 118,
            "answer_format_compliance": 199,
            "claim_citation_alignment": 173,
        },
        "random_retrieval": {
            "accuracy": 118,
            "groundedness": 118,
            "citation_precision": 118,
            "answer_format_compliance": 144,
            "claim_citation_alignment": 68,
        },
        "single_chunk": {
            "accuracy": 118,
            "groundedness": 118,
            "citation_precision": 118,
            "answer_format_compliance": 214,
            "claim_citation_alignment": 188,
        },
    }

    def _summary_with_ci(self) -> dict:
        return _make_summary(
            full={m: 0.30 for m in GAUGED_METRICS},
            random_retrieval={m: 0.10 for m in GAUGED_METRICS},
            single_chunk={m: 0.05 for m in GAUGED_METRICS},
            ci_n=self._CI_N,
        )

    def test_per_metric_n_in_json(self) -> None:
        g = compute_gauge(self._summary_with_ci())
        for run_name, per_metric in self._CI_N.items():
            run = g["runs"][run_name]
            self.assertIn("metric_n", run)
            for metric, expected_n in per_metric.items():
                self.assertEqual(run["metric_n"][metric], expected_n)

    def test_quality_and_format_denominators_diverge(self) -> None:
        # The whole point: a reader must NOT assume one shared denominator.
        g = compute_gauge(self._summary_with_ci())
        full = g["runs"]["full"]["metric_n"]
        self.assertEqual(full["accuracy"], 118)
        self.assertEqual(full["answer_format_compliance"], 199)
        self.assertEqual(full["claim_citation_alignment"], 173)
        self.assertNotEqual(full["accuracy"], full["answer_format_compliance"])
        self.assertNotEqual(full["accuracy"], full["claim_citation_alignment"])

    def test_per_metric_n_rendered_in_markdown(self) -> None:
        md = render_markdown(compute_gauge(self._summary_with_ci()))
        # Raw-values table cells carry their own denominator.
        self.assertIn("(n=118)", md)  # accuracy/groundedness/citation_precision
        self.assertIn("(n=199)", md)  # answer_format_compliance (full)
        self.assertIn("(n=173)", md)  # claim_citation_alignment (full)
        # The effective_n column is scoped to the quality-metric subset, not
        # presented as a shared denominator for every metric.
        self.assertIn("accuracy/groundedness/citation_precision denom", md)

    def test_missing_ci_renders_without_n_suffix(self) -> None:
        # Backward-compat: a ci-less summary (older fixtures / absent slice)
        # must not crash and must omit the "(n=...)" suffix entirely.
        g = compute_gauge(
            _make_summary(
                full={m: 0.5 for m in GAUGED_METRICS},
                random_retrieval={m: 0.1 for m in GAUGED_METRICS},
                single_chunk={m: 0.2 for m in GAUGED_METRICS},
            )
        )
        for run_name in REQUIRED_RUNS:
            for metric in GAUGED_METRICS:
                self.assertIsNone(g["runs"][run_name]["metric_n"][metric])
        self.assertNotIn("(n=", render_markdown(g))


class CISignalTest(unittest.TestCase):
    """CI-aware signal_state (#1367 F1) — the core hardening contract."""

    def test_small_positive_gap_overlapping_ci_is_uncertain(self) -> None:
        # default beats both floors on point estimate by a hair, but its CI
        # overlaps both floors → must be "uncertain", NOT "alive".
        summary = _make_summary(
            full={m: 0.32 for m in GAUGED_METRICS},
            random_retrieval={m: 0.28 for m in GAUGED_METRICS},
            single_chunk={m: 0.29 for m in GAUGED_METRICS},
            full_ci=_ci({m: (0.22, 0.42) for m in GAUGED_METRICS}),
            random_ci=_ci({m: (0.18, 0.38) for m in GAUGED_METRICS}),
            single_ci=_ci({m: (0.19, 0.39) for m in GAUGED_METRICS}),
        )
        g = compute_gauge(summary)
        for metric in GAUGED_METRICS:
            cell = g["gauge"][metric]
            self.assertGreater(cell["vs_random"]["gap"], 0)
            self.assertGreater(cell["vs_single"]["gap"], 0)
            self.assertFalse(cell["vs_random"]["ci_separated"])
            self.assertEqual("uncertain", cell["signal_state"])
            self.assertFalse(cell["signal_alive"])

    def test_large_gap_nonoverlapping_ci_is_alive(self) -> None:
        summary = _make_summary(
            full={m: 0.50 for m in GAUGED_METRICS},
            random_retrieval={m: 0.05 for m in GAUGED_METRICS},
            single_chunk={m: 0.10 for m in GAUGED_METRICS},
            full_ci=_ci({m: (0.42, 0.58) for m in GAUGED_METRICS}),
            random_ci=_ci({m: (0.01, 0.10) for m in GAUGED_METRICS}),
            single_ci=_ci({m: (0.05, 0.16) for m in GAUGED_METRICS}),
        )
        g = compute_gauge(summary)
        for metric in GAUGED_METRICS:
            cell = g["gauge"][metric]
            self.assertTrue(cell["vs_random"]["ci_separated"])
            self.assertTrue(cell["vs_single"]["ci_separated"])
            self.assertEqual("alive", cell["signal_state"])
            self.assertTrue(cell["signal_alive"])

    def test_separated_from_one_floor_only_is_uncertain(self) -> None:
        # CI-separated from random but overlapping single_chunk → uncertain
        # (both floors must be CI-separated for "alive").
        summary = _make_summary(
            full={m: 0.40 for m in GAUGED_METRICS},
            random_retrieval={m: 0.05 for m in GAUGED_METRICS},
            single_chunk={m: 0.35 for m in GAUGED_METRICS},
            full_ci=_ci({m: (0.32, 0.48) for m in GAUGED_METRICS}),
            random_ci=_ci({m: (0.01, 0.10) for m in GAUGED_METRICS}),
            single_ci=_ci({m: (0.28, 0.42) for m in GAUGED_METRICS}),
        )
        g = compute_gauge(summary)
        for metric in GAUGED_METRICS:
            cell = g["gauge"][metric]
            self.assertTrue(cell["vs_random"]["ci_separated"])
            self.assertFalse(cell["vs_single"]["ci_separated"])
            self.assertEqual("uncertain", cell["signal_state"])

    def test_missing_ci_with_positive_gap_is_uncertain(self) -> None:
        # No ci blocks at all + positive point gap → cannot verify separation,
        # so the gauge refuses to claim "alive".
        summary = _make_summary(
            full={m: 0.50 for m in GAUGED_METRICS},
            random_retrieval={m: 0.10 for m in GAUGED_METRICS},
            single_chunk={m: 0.20 for m in GAUGED_METRICS},
        )
        g = compute_gauge(summary)
        for metric in GAUGED_METRICS:
            cell = g["gauge"][metric]
            self.assertGreater(cell["vs_random"]["gap"], 0)
            self.assertIsNone(cell["vs_random"]["ci_separated"])
            self.assertIsNone(cell["default_ci"])
            self.assertEqual("uncertain", cell["signal_state"])
            self.assertFalse(cell["signal_alive"])

    def test_markdown_surfaces_uncertain_state(self) -> None:
        summary = _make_summary(
            full={m: 0.32 for m in GAUGED_METRICS},
            random_retrieval={m: 0.28 for m in GAUGED_METRICS},
            single_chunk={m: 0.29 for m in GAUGED_METRICS},
            full_ci=_ci({m: (0.22, 0.42) for m in GAUGED_METRICS}),
            random_ci=_ci({m: (0.18, 0.38) for m in GAUGED_METRICS}),
            single_ci=_ci({m: (0.19, 0.39) for m in GAUGED_METRICS}),
        )
        md = render_markdown(compute_gauge(summary))
        self.assertIn("signal uncertain", md)
        self.assertIn("CI-sep vs random", md)


class ProvenanceTest(unittest.TestCase):
    """Aggregate provenance propagation + skew detection (#1367 F2)."""

    def _summary(self, **kw) -> dict:
        return _make_summary(
            full={m: 0.5 for m in GAUGED_METRICS},
            random_retrieval={m: 0.1 for m in GAUGED_METRICS},
            single_chunk={m: 0.2 for m in GAUGED_METRICS},
            **kw,
        )

    def test_provenance_propagated_into_aggregate(self) -> None:
        prov = {"git_commit": "abc123", "git_dirty": False, "generated_at": "2026-05-23T00:00:00Z"}
        manifest = {"git_commit": "abc123", "config_sha256": "deadbeef", "config_path": "eval/real_config.local.yaml"}
        g = compute_gauge(self._summary(provenance=prov, run_manifest=manifest))
        self.assertEqual(prov, g["provenance"])
        self.assertEqual(manifest, g["run_manifest"])

    def test_missing_provenance_is_none(self) -> None:
        g = compute_gauge(self._summary())
        self.assertIsNone(g["provenance"])
        self.assertIsNone(g["run_manifest"])

    def test_skew_warns_when_provenance_absent(self) -> None:
        g = compute_gauge(self._summary())
        warnings = check_provenance_skew(g, head_provenance={"git_commit": "head99"})
        self.assertEqual(1, len(warnings))
        self.assertIn("no provenance", warnings[0])

    def test_skew_warns_on_commit_mismatch(self) -> None:
        prov = {"git_commit": "old111", "git_dirty": False, "generated_at": "x"}
        g = compute_gauge(self._summary(provenance=prov))
        warnings = check_provenance_skew(g, head_provenance={"git_commit": "head99"})
        self.assertTrue(any("skew" in w for w in warnings))

    def test_skew_warns_on_dirty_source(self) -> None:
        prov = {"git_commit": "head99", "git_dirty": True, "generated_at": "x"}
        g = compute_gauge(self._summary(provenance=prov))
        warnings = check_provenance_skew(g, head_provenance={"git_commit": "head99"})
        self.assertTrue(any("git_dirty" in w for w in warnings))

    def test_no_skew_when_clean_and_matching(self) -> None:
        prov = {"git_commit": "head99", "git_dirty": False, "generated_at": "x"}
        g = compute_gauge(self._summary(provenance=prov))
        warnings = check_provenance_skew(g, head_provenance={"git_commit": "head99"})
        self.assertEqual([], warnings)

    def test_strict_mode_exits_nonzero_on_skew(self) -> None:
        prov = {"git_commit": "old111", "git_dirty": True, "generated_at": "x"}
        summary = self._summary(provenance=prov)
        with TemporaryDirectory() as td:
            tdp = Path(td)
            summary_path = tdp / "eval_summary.json"
            summary_path.write_text(json.dumps(summary))
            rc = main(["--summary", str(summary_path), "--print-only", "--strict"])
            # old111 != real HEAD (and dirty) → strict refuses with non-zero rc.
            self.assertEqual(1, rc)


if __name__ == "__main__":
    unittest.main()
