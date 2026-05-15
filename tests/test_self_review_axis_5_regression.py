"""Regression tests for axis #5-B (memory content freshness) collector.

Pins the fresh-in-quarter rate contract: fraction of memory files whose
`mtime` (ISO date string) falls inside `[quarter_start, ∞)`. Pairs with
axis #5-A (governance_hooks fire counts) which is unchanged by this
collector. Issue #877.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "claude-hooks"))
import _self_review as sr


class TestComputeAxis5MemoryHygiene(unittest.TestCase):
    def test_empty_memory_returns_none_rate(self):
        result = sr.compute_axis_5_memory_hygiene(
            {"files": []}, quarter_start="2026-04-01"
        )
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["fresh_in_quarter"], 0)
        self.assertIsNone(result["fresh_rate"])
        self.assertIsNone(result["oldest_mtime"])

    def test_all_files_fresh(self):
        memory = {
            "files": [
                {"filename": "a.md", "mtime": "2026-05-10"},
                {"filename": "b.md", "mtime": "2026-04-15"},
                {"filename": "c.md", "mtime": "2026-04-01"},
            ]
        }
        result = sr.compute_axis_5_memory_hygiene(
            memory, quarter_start="2026-04-01"
        )
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["fresh_in_quarter"], 3)
        self.assertEqual(result["fresh_rate"], 1.0)
        self.assertEqual(result["stale_count"], 0)
        self.assertEqual(result["oldest_mtime"], "2026-04-01")

    def test_all_files_stale(self):
        memory = {
            "files": [
                {"filename": "a.md", "mtime": "2025-12-10"},
                {"filename": "b.md", "mtime": "2026-01-20"},
            ]
        }
        result = sr.compute_axis_5_memory_hygiene(
            memory, quarter_start="2026-04-01"
        )
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["fresh_in_quarter"], 0)
        self.assertEqual(result["fresh_rate"], 0.0)
        self.assertEqual(result["stale_count"], 2)
        self.assertEqual(result["oldest_mtime"], "2025-12-10")

    def test_half_fresh(self):
        memory = {
            "files": [
                {"filename": "a.md", "mtime": "2026-05-01"},
                {"filename": "b.md", "mtime": "2026-04-05"},
                {"filename": "c.md", "mtime": "2026-01-01"},
                {"filename": "d.md", "mtime": "2025-11-01"},
            ]
        }
        result = sr.compute_axis_5_memory_hygiene(
            memory, quarter_start="2026-04-01"
        )
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["fresh_in_quarter"], 2)
        self.assertEqual(result["fresh_rate"], 0.5)
        self.assertEqual(result["stale_count"], 2)
        self.assertEqual(result["oldest_mtime"], "2025-11-01")

    def test_missing_mtime_field_treated_as_stale(self):
        memory = {
            "files": [
                {"filename": "a.md", "mtime": "2026-05-01"},
                {"filename": "b.md"},
            ]
        }
        result = sr.compute_axis_5_memory_hygiene(
            memory, quarter_start="2026-04-01"
        )
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["fresh_in_quarter"], 1)
        self.assertEqual(result["fresh_rate"], 0.5)


class TestCollectMemoryEmitsMtime(unittest.TestCase):
    """collect_memory writes ISO-date mtime that compute_axis_5 reads."""

    def test_collect_memory_then_compute_axis_5_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            fresh_file = tdir / "feedback_a.md"
            fresh_file.write_text(
                "---\nname: A\ntype: feedback\n---\nbody"
            )
            stale_file = tdir / "project_b.md"
            stale_file.write_text(
                "---\nname: B\ntype: project\n---\nbody"
            )
            stale_ts = datetime(2025, 1, 15, tzinfo=timezone.utc).timestamp()
            os.utime(stale_file, (stale_ts, stale_ts))
            fresh_ts = time.time()
            os.utime(fresh_file, (fresh_ts, fresh_ts))

            memory = sr.collect_memory(str(tdir))
            result = sr.compute_axis_5_memory_hygiene(
                memory, quarter_start="2026-04-01"
            )
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["fresh_in_quarter"], 1)
            self.assertEqual(result["fresh_rate"], 0.5)
            self.assertEqual(result["oldest_mtime"], "2025-01-15")


if __name__ == "__main__":
    unittest.main()
