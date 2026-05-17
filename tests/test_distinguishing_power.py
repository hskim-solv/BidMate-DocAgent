"""Regression tests for the distinguishing-power gauge (issue #945, ADR 0053).

The script (``scripts/distinguishing_power.py``) is the "is the signal alive"
gauge from ADR 0053 §Consequences. These tests lock in:

1. **Math**: ``(default - floor) / (1 - floor)`` formula correctness on
   hand-computable fixtures.
2. **Schema**: the output JSON has the exact shape PR-D (README auto-regen)
   will consume.
3. **Verdict logic**: ``signal_alive`` is ``True`` iff default beats BOTH
   floors on raw gap (gap > 0). Beating only one floor is ``False`` — the
   strict version of the gauge per ADR 0053 §Decision ("falsifiable lower
   bounds — any future improvement that doesn't beat random_retrieval is by
   definition not a real improvement").
4. **Missing-data tolerance**: floors with ``None`` for a metric produce
   ``signal_alive: False`` and ``gap: None`` rather than raising.
5. **Required-runs validation**: missing one of the 3 ablations exits
   non-zero with a useful error message (not a stack trace).

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
    compute_gauge,
    main,
    render_markdown,
)


def _make_summary(
    full: dict[str, float | None],
    random_retrieval: dict[str, float | None],
    single_chunk: dict[str, float | None],
    n: int = 221,
) -> dict:
    """Build a minimal eval_summary.json shape with 3 ablation runs."""

    def _run(name: str, values: dict[str, float | None]) -> dict:
        return {
            "name": name,
            "num_predictions": n,
            **values,
        }

    return {
        "num_predictions": n,
        "ablation": {
            "runs": [
                _run("full", full),
                _run("random_retrieval", random_retrieval),
                _run("single_chunk", single_chunk),
            ]
        },
    }


class GaugeMathTest(unittest.TestCase):
    """The (default - floor) / (1 - floor) formula on hand-computable inputs."""

    def test_perfect_signal(self) -> None:
        summary = _make_summary(
            full={m: 0.50 for m in GAUGED_METRICS},
            random_retrieval={m: 0.10 for m in GAUGED_METRICS},
            single_chunk={m: 0.20 for m in GAUGED_METRICS},
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
        self.assertEqual({"num_predictions", "runs", "gauge"}, set(g.keys()))
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
                {"default", "vs_random", "vs_single", "signal_alive"},
                set(cell.keys()),
            )
            for floor_key in ("vs_random", "vs_single"):
                self.assertEqual(
                    {"gap", "normalized"}, set(cell[floor_key].keys())
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
            self.assertEqual({"num_predictions", "runs", "gauge"}, set(written.keys()))
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


if __name__ == "__main__":
    unittest.main()
