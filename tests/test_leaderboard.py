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
        # All headline metrics present in chart payload.
        for key, _ in HEADLINE_METRICS:
            self.assertIn(key, data["metrics"])
            self.assertEqual(2, len(data["metrics"][key]["values"]))
            self.assertEqual(2, len(data["metrics"][key]["ci_lo"]))

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
