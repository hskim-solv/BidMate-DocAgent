"""Regression tests for leaderboard HWP slice rendering (issue #657 / ADR 0039).

Verifies that:
1. `load_history` extracts ``by_format_hwp`` from aggregate snapshots.
2. `_chart_data` includes a ``hwp_format`` series for every headline metric.
3. ``hwp_format.values`` carries the correct accuracy from ``by_format.hwp``.
4. Pre-#650 rows (no ``by_format``) yield ``None`` values (ADR 0030 gaps).
5. `render_markdown_table` contains the HWP Slice section header.
6. `render_page` includes the ``hwp_format`` dataset label in the JS payload.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.leaderboard import (
    HEADLINE_METRICS,
    _chart_data,
    _hwp_format_row_view,
    load_history,
    render_markdown_table,
    render_page,
)


def _make_row(
    *,
    accuracy: float | None = 0.8,
    by_format_hwp: dict | None = None,
) -> dict:
    return {
        "file": "20260514.aggregate.json",
        "commit": "abc123def456",
        "date": "2026-05-14",
        "num_predictions": 10,
        "accuracy": accuracy,
        "groundedness": 0.75,
        "citation_precision": 0.9,
        "answer_format_compliance": 1.0,
        "abstention": None,
        "retry": 0.0,
        "ci": {},
        "ablation_full": {},
        "by_format_hwp": by_format_hwp or {},
    }


def _make_aggregate_file(tmp_dir: Path, by_format: dict | None = None) -> None:
    payload = {
        "provenance": {"git_commit": "abc123def456", "generated_at": "2026-05-14T12:00:00Z"},
        "num_predictions": 10,
        "accuracy": 0.8,
        "groundedness": 0.75,
        "citation_precision": 0.9,
        "answer_format_compliance": 1.0,
        "abstention": None,
        "retry": 0.0,
    }
    if by_format is not None:
        payload["by_format"] = by_format
    (tmp_dir / "20260514.aggregate.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


class TestLoadHistoryByFormatHwp(unittest.TestCase):
    def test_extracts_by_format_hwp_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            _make_aggregate_file(tmp_dir, by_format={"hwp": {"accuracy": 0.65, "num_predictions": 2}})
            rows = load_history(tmp_dir)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["by_format_hwp"].get("accuracy"), 0.65)

    def test_by_format_hwp_empty_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            _make_aggregate_file(tmp_dir, by_format=None)
            rows = load_history(tmp_dir)
        self.assertEqual(rows[0]["by_format_hwp"], {})

    def test_unknown_format_bucket_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            _make_aggregate_file(
                tmp_dir,
                by_format={"hwp": {"accuracy": 0.5}, "secret_format": {"accuracy": 0.0}},
            )
            rows = load_history(tmp_dir)
        # extract_aggregate is fail-closed; secret_format must not appear
        self.assertNotIn("secret_format", rows[0].get("by_format_hwp", {}))


class TestChartDataHwpFormatSeries(unittest.TestCase):
    def test_hwp_format_key_present_for_all_metrics(self) -> None:
        rows = [_make_row(by_format_hwp={"accuracy": 0.6})]
        data = _chart_data(rows)
        for key, _ in HEADLINE_METRICS:
            self.assertIn("hwp_format", data["metrics"][key], f"Missing hwp_format in {key}")

    def test_hwp_format_accuracy_value_correct(self) -> None:
        rows = [_make_row(by_format_hwp={"accuracy": 0.6, "groundedness": 0.55})]
        data = _chart_data(rows)
        self.assertEqual(data["metrics"]["accuracy"]["hwp_format"]["values"], [0.6])
        self.assertEqual(data["metrics"]["groundedness"]["hwp_format"]["values"], [0.55])

    def test_hwp_format_none_when_by_format_absent(self) -> None:
        rows = [_make_row(by_format_hwp={})]
        data = _chart_data(rows)
        for key, _ in HEADLINE_METRICS:
            values = data["metrics"][key]["hwp_format"]["values"]
            self.assertEqual(values, [None], f"{key}: expected [None] for missing by_format_hwp")

    def test_multiple_rows_correct_lengths(self) -> None:
        rows = [
            _make_row(by_format_hwp={"accuracy": 0.7}),
            _make_row(by_format_hwp={}),
        ]
        data = _chart_data(rows)
        values = data["metrics"]["accuracy"]["hwp_format"]["values"]
        self.assertEqual(len(values), 2)
        self.assertEqual(values[0], 0.7)
        self.assertIsNone(values[1])


class TestHwpFormatRowView(unittest.TestCase):
    def test_projects_hwp_metrics(self) -> None:
        row = _make_row(by_format_hwp={"accuracy": 0.6, "num_predictions": 3})
        view = _hwp_format_row_view(row)
        self.assertEqual(view["accuracy"], 0.6)
        self.assertEqual(view["num_predictions"], 3)
        self.assertEqual(view["date"], "2026-05-14")
        self.assertEqual(view["commit"], "abc123def456")

    def test_none_metrics_when_empty(self) -> None:
        row = _make_row(by_format_hwp={})
        view = _hwp_format_row_view(row)
        self.assertIsNone(view["accuracy"])
        self.assertIsNone(view["num_predictions"])


class TestRenderMarkdownTableHwpSection(unittest.TestCase):
    def test_hwp_slice_header_present(self) -> None:
        rows = [_make_row(by_format_hwp={"accuracy": 0.6})]
        md = render_markdown_table(rows)
        self.assertIn("HWP Slice", md)

    def test_hwp_slice_section_after_agentic_full(self) -> None:
        rows = [_make_row(by_format_hwp={"accuracy": 0.6})]
        md = render_markdown_table(rows)
        agentic_pos = md.find("agentic_full")
        hwp_pos = md.find("HWP Slice")
        self.assertGreater(hwp_pos, agentic_pos)

    def test_adr_0039_reference_present(self) -> None:
        rows = [_make_row()]
        md = render_markdown_table(rows)
        self.assertIn("ADR 0039", md)


class TestRenderPageHwpDataset(unittest.TestCase):
    def test_hwp_format_dataset_label_in_js(self) -> None:
        rows = [_make_row(by_format_hwp={"accuracy": 0.6})]
        page = render_page(rows)
        self.assertIn("hwp_format", page)

    def test_leaderboard_data_contains_hwp_format(self) -> None:
        rows = [_make_row(by_format_hwp={"accuracy": 0.7})]
        page = render_page(rows)
        # The JSON payload is inlined; verify the hwp_format key appears
        self.assertIn('"hwp_format"', page)


if __name__ == "__main__":
    unittest.main()
