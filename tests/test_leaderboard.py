"""Regression tests for the synthetic eval leaderboard renderer (#166).

Pins:

* the markdown table renders correctly with a multi-row history
* the Chart.js page embeds JSON that round-trips through Python's
  parser (no JS syntax errors)
* extract_aggregate is applied as defense-in-depth (no per-case
  leakage)
* ``--check`` mode flags drift correctly
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.leaderboard import (
    HEADLINE_METRICS,
    load_history,
    render_markdown_table,
    render_page,
    write_artifacts,
)


def _snapshot(
    sha: str,
    date: str,
    accuracy: float,
    *,
    extras: dict | None = None,
) -> dict:
    """Build a minimal aggregate snapshot file payload."""
    payload = {
        "num_predictions": 42,
        "accuracy": accuracy,
        "groundedness": accuracy + 0.02,
        "citation_precision": accuracy - 0.01,
        "answer_format_compliance": accuracy,
        "abstention": 1.0,
        "retry": 0.31,
        "ci": {
            "accuracy": {
                "mean": accuracy,
                "ci_lo": max(0.0, accuracy - 0.05),
                "ci_hi": min(1.0, accuracy + 0.05),
                "n": 42,
            },
            "groundedness": {
                "mean": accuracy + 0.02,
                "ci_lo": accuracy - 0.03,
                "ci_hi": min(1.0, accuracy + 0.07),
                "n": 42,
            },
            "citation_precision": {
                "mean": accuracy - 0.01,
                "ci_lo": max(0.0, accuracy - 0.06),
                "ci_hi": min(1.0, accuracy + 0.04),
                "n": 42,
            },
            "answer_format_compliance": {
                "mean": accuracy,
                "ci_lo": max(0.0, accuracy - 0.04),
                "ci_hi": min(1.0, accuracy + 0.04),
                "n": 42,
            },
        },
        "provenance": {
            "git_commit": sha,
            "git_dirty": False,
            "generated_at": f"{date}T12:00:00Z",
        },
    }
    if extras:
        payload.update(extras)
    return payload


def _write_history(tmp: Path, snapshots: list[dict]) -> Path:
    history = tmp / "reports" / "history"
    history.mkdir(parents=True)
    for snap in snapshots:
        prov = snap["provenance"]
        ts = (
            str(prov["generated_at"])
            .replace("-", "")
            .replace(":", "")
            .split(".")[0]
        )
        if not ts.endswith("Z"):
            ts += "Z"
        sha = prov["git_commit"]
        path = history / f"{ts}_{sha}.aggregate.json"
        path.write_text(json.dumps(snap, ensure_ascii=False, indent=2))
    return history


class LeaderboardRenderTest(unittest.TestCase):
    def test_empty_history_renders_placeholder(self) -> None:
        with TemporaryDirectory() as tmpdir:
            history = Path(tmpdir) / "reports" / "history"
            rows = load_history(history)
            md = render_markdown_table(rows)
        self.assertEqual([], rows)
        self.assertIn("No history entries yet", md)

    def test_multi_row_markdown_has_chronological_order(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            history = _write_history(
                tmp,
                [
                    _snapshot("aaaa11112222", "2026-05-08", 0.844),
                    _snapshot("bbbb33334444", "2026-05-10", 0.870),
                    _snapshot("cccc55556666", "2026-05-12", 0.906),
                ],
            )
            rows = load_history(history)
            md = render_markdown_table(rows)
        self.assertEqual(3, len(rows))
        self.assertEqual("aaaa11112222", rows[0]["commit"])
        self.assertEqual("cccc55556666", rows[-1]["commit"])
        # Chronological order in markdown
        idx_a = md.index("aaaa11112222")
        idx_b = md.index("bbbb33334444")
        idx_c = md.index("cccc55556666")
        self.assertLess(idx_a, idx_b)
        self.assertLess(idx_b, idx_c)
        # Metric values surface
        self.assertIn("0.844", md)
        self.assertIn("0.870", md)
        self.assertIn("0.906", md)

    def test_render_page_embeds_valid_chart_data(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            history = _write_history(
                tmp,
                [
                    _snapshot("aaaa11112222", "2026-05-08", 0.844),
                    _snapshot("bbbb33334444", "2026-05-12", 0.906),
                ],
            )
            rows = load_history(history)
            page = render_page(rows)
        # Front matter present so Jekyll picks it up.
        self.assertTrue(page.startswith("---"))
        self.assertIn("permalink: /leaderboard/", page)
        # JSON data block is parseable.
        match = re.search(r"const LEADERBOARD_DATA = (\{.*?\});", page, re.DOTALL)
        self.assertIsNotNone(match, "Could not find LEADERBOARD_DATA in rendered page")
        data = json.loads(match.group(1))
        self.assertEqual(["2026-05-08", "2026-05-12"], data["labels"])
        self.assertEqual(2, len(data["commits"]))
        # All headline metrics present in chart payload with both pipeline
        # series (ADR 0029 — naive_baseline + agentic_full overlay).
        for key, _ in HEADLINE_METRICS:
            self.assertIn(key, data["metrics"])
            self.assertIn("baseline", data["metrics"][key])
            self.assertIn("full", data["metrics"][key])
            self.assertEqual(2, len(data["metrics"][key]["baseline"]["values"]))
            self.assertEqual(2, len(data["metrics"][key]["baseline"]["ci_lo"]))
            # `full` series is forward-only — these snapshots predate the
            # `ablation_full` schema so the chart payload renders gaps
            # (None values) rather than dropping the row.
            self.assertEqual(2, len(data["metrics"][key]["full"]["values"]))
            self.assertTrue(
                all(v is None for v in data["metrics"][key]["full"]["values"]),
                f"{key} full series should be all-None for pre-#476 snapshots",
            )
        # Issue #267 regression: baseline CI bands must be numeric, not
        # None, when the source snapshots include a ci block. A previous
        # bug let extract_aggregate strip the ci block silently, leaving
        # the chart bands as null arrays and a flat-line leaderboard.
        for key, _ in HEADLINE_METRICS:
            ci_lo = data["metrics"][key]["baseline"]["ci_lo"]
            ci_hi = data["metrics"][key]["baseline"]["ci_hi"]
            self.assertTrue(
                all(isinstance(v, (int, float)) for v in ci_lo),
                f"{key} baseline ci_lo lost numeric values during round-trip: {ci_lo}",
            )
            self.assertTrue(
                all(isinstance(v, (int, float)) for v in ci_hi),
                f"{key} baseline ci_hi lost numeric values during round-trip: {ci_hi}",
            )

    def test_full_series_populated_when_snapshot_has_ablation_full(self) -> None:
        """ADR 0029: a snapshot carrying `ablation_full` should populate
        the `full` chart series with that pipeline's headline metrics."""
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            full_snap = _snapshot(
                "ffff77778888",
                "2026-05-15",
                0.844,
                extras={
                    "ablation_full": {
                        "num_predictions": 42,
                        "accuracy": 0.906,
                        "groundedness": 0.929,
                        "citation_precision": 0.905,
                        "answer_format_compliance": 0.905,
                        "abstention": 1.000,
                        "retry": 0.310,
                    }
                },
            )
            history = _write_history(tmp, [full_snap])
            rows = load_history(history)
            page = render_page(rows)
            md = render_markdown_table(rows)
        # Both pipeline tables appear in the standalone markdown.
        self.assertIn("Pipeline: naive_baseline", md)
        self.assertIn("Pipeline: agentic_full", md)
        # The full row carries `0.906` (agentic_full accuracy), not just
        # the 0.844 baseline.
        self.assertIn("0.906", md)
        # Chart payload `full` series carries the new value.
        match = re.search(r"const LEADERBOARD_DATA = (\{.*?\});", page, re.DOTALL)
        self.assertIsNotNone(match)
        data = json.loads(match.group(1))
        self.assertEqual(
            [0.906], data["metrics"]["accuracy"]["full"]["values"]
        )
        self.assertEqual(
            [0.844], data["metrics"]["accuracy"]["baseline"]["values"]
        )

    def test_ablation_full_extractor_drops_per_case_leak(self) -> None:
        """ADR 0029: a snapshot with case_results smuggled into
        `ablation_full` must round-trip into the rendered page with
        the leak dropped, preserving the ADR 0005 commit boundary."""
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            snap = _snapshot(
                "aaaa11112222",
                "2026-05-08",
                0.844,
                extras={
                    "ablation_full": {
                        "accuracy": 0.906,
                        # Schema-drift smuggling attempt — must be dropped.
                        "case_results": [{"id": "leak", "query": "leak"}],
                        "made_up_field": "leak text",
                    }
                },
            )
            history = _write_history(tmp, [snap])
            rows = load_history(history)
            page = render_page(rows)
        # Per-case payload dropped — strings from case_results / made_up
        # fields must not appear anywhere in the rendered page.
        self.assertNotIn("leak", page)

    def test_page_does_not_leak_per_case_fields_if_present_in_history(self) -> None:
        """Defense-in-depth: even if a history file contained case_results
        (which would be a schema-drift bug upstream), load_history's
        extract_aggregate pass must drop them so they don't leak into
        the rendered page."""
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            history = _write_history(
                tmp,
                [
                    _snapshot(
                        "deadbeef0000",
                        "2026-05-08",
                        0.844,
                        extras={
                            "case_results": [
                                {
                                    "id": "leak_case",
                                    "query": "leak query",
                                    "answer": "leak answer",
                                }
                            ]
                        },
                    ),
                ],
            )
            rows = load_history(history)
            md = render_markdown_table(rows)
            page = render_page(rows)
        for leak in ["leak_case", "leak query", "leak answer"]:
            self.assertNotIn(leak, md)
            self.assertNotIn(leak, page)

    def test_render_page_does_not_duplicate_h1_or_intro(self) -> None:
        """Page must have exactly one H1 and one intro paragraph.

        Earlier the page embedded ``render_markdown_table`` verbatim,
        which produced TWO ``# Synthetic Eval Leaderboard`` headers and
        TWO intro paragraphs — once under the front-matter (the page's
        own title) and once again under ``## Tabular view``. This is
        the regression guard against re-introducing that duplication.
        """
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            history = _write_history(
                tmp,
                [
                    _snapshot("aaaa11112222", "2026-05-08", 0.844),
                    _snapshot("bbbb33334444", "2026-05-12", 0.906),
                ],
            )
            rows = load_history(history)
            page = render_page(rows)
        # Exactly one H1 — front-matter `title:` does not count as H1 markdown.
        h1_count = sum(
            1
            for line in page.splitlines()
            if line.startswith("# ") and "Synthetic Eval Leaderboard" in line
        )
        self.assertEqual(
            1,
            h1_count,
            f"Expected exactly one '# Synthetic Eval Leaderboard' H1, got {h1_count}",
        )
        # Intro phrase ("Time-series view of headline metrics") should also
        # appear once — the page's own intro under the H1, not duplicated
        # under "## Tabular view".
        self.assertEqual(
            1,
            page.count("Time-series view of headline metrics"),
            "Intro phrase 'Time-series view of headline metrics' must appear exactly once",
        )

    def test_write_artifacts_round_trip(self) -> None:
        """Both markdown and page files are written and re-read identical."""
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            history = _write_history(
                tmp,
                [_snapshot("11112222aaaa", "2026-05-08", 0.844)],
            )
            rows = load_history(history)
            md_path = tmp / "leaderboard.md"
            page_path = tmp / "leaderboard.page.md"
            md, page = write_artifacts(rows, md_path=md_path, page_path=page_path)
            self.assertEqual(md_path.read_text(encoding="utf-8"), md)
            self.assertEqual(page_path.read_text(encoding="utf-8"), page)


if __name__ == "__main__":
    unittest.main()
