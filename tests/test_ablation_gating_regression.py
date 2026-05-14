"""Regression tests for ablation_runs() gating logic in eval/run_eval.py.

Covers two skip gates introduced alongside issue #447 (KURE-v1 Phase 1.5):

1. ``requires_module`` — existing gate: drop rows whose declared module
   is not importable (e.g. FlagEmbedding on a lean CI environment).
2. ``requires_torch_min_version`` — new gate: drop rows whose declared
   minimum torch version exceeds the installed torch (e.g. m3_full needs
   torch >= 2.6 for CVE-2025-32434 mitigation — ADR 0019 condition 1).

Both gates are transparent (stderr log) and additive — rows without
the field are unaffected.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib.util

# Import the function under test.
sys.path.insert(0, str(ROOT / "eval"))
from run_eval import ablation_runs  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(rows: list[dict]) -> dict:
    """Wrap rows in a minimal eval config dict."""
    return {
        "mode": "rag",
        "ablation_runs": rows,
        "cases": [],
    }


def _row(name: str, **extra) -> dict:
    """Build a minimal ablation row dict."""
    base = {
        "name": name,
        "pipeline": "naive_baseline",
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# requires_torch_min_version gate
# ---------------------------------------------------------------------------

class TestRequiresTorchMinVersion(unittest.TestCase):
    """requires_torch_min_version gate in ablation_runs()."""

    def _run(self, rows: list[dict]) -> tuple[list[dict], str]:
        """Return (kept_rows, stderr_text)."""
        buf = io.StringIO()
        with patch("sys.stderr", buf):
            kept = ablation_runs(_config(rows))
        return kept, buf.getvalue()

    def test_no_field_always_kept(self) -> None:
        """Row without requires_torch_min_version is always included."""
        kept, _ = self._run([_row("baseline")])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["name"], "baseline")

    def test_future_version_skipped(self) -> None:
        """Row requiring torch 9999.0 (far future) is skipped."""
        kept, stderr = self._run([_row("future", requires_torch_min_version="9999.0")])
        self.assertEqual(kept, [])
        self.assertIn("future", stderr)
        self.assertIn("9999.0", stderr)

    def test_past_version_kept(self) -> None:
        """Row requiring torch 1.0 (far past) is included."""
        kept, _ = self._run([_row("past", requires_torch_min_version="1.0")])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["name"], "past")

    def test_exact_installed_version_kept(self) -> None:
        """Row requiring the exact installed torch version is included."""
        import torch

        major, minor = torch.__version__.split(".")[:2]
        min_ver = f"{major}.{minor}"
        kept, _ = self._run([_row("exact", requires_torch_min_version=min_ver)])
        self.assertEqual(len(kept), 1)

    def test_mixed_rows(self) -> None:
        """Only rows with unsatisfied requires_torch_min_version are dropped."""
        rows = [
            _row("ok"),
            _row("future", requires_torch_min_version="9999.0"),
            _row("past", requires_torch_min_version="1.0"),
        ]
        kept, stderr = self._run(rows)
        names = [r["name"] for r in kept]
        self.assertIn("ok", names)
        self.assertNotIn("future", names)
        self.assertIn("past", names)
        self.assertIn("future", stderr)

    def test_stderr_log_contains_installed_version(self) -> None:
        """Skip log message includes the installed torch version for diagnosis."""
        _, stderr = self._run([_row("x", requires_torch_min_version="9999.0")])
        import torch

        installed = ".".join(torch.__version__.split(".")[:2])
        self.assertIn(installed, stderr)


# ---------------------------------------------------------------------------
# requires_module gate (existing — regression guard)
# ---------------------------------------------------------------------------

class TestRequiresModule(unittest.TestCase):
    """Existing requires_module gate still works after the new gate was added."""

    def _run(self, rows: list[dict]) -> tuple[list[dict], str]:
        buf = io.StringIO()
        with patch("sys.stderr", buf):
            kept = ablation_runs(_config(rows))
        return kept, buf.getvalue()

    def test_importable_module_kept(self) -> None:
        """Row with an importable requires_module is included."""
        kept, _ = self._run([_row("with_json", requires_module="json")])
        self.assertEqual(len(kept), 1)

    def test_missing_module_skipped(self) -> None:
        """Row requiring a nonexistent module is skipped."""
        kept, stderr = self._run([_row("missing", requires_module="_nonexistent_pkg_xyz")])
        self.assertEqual(kept, [])
        self.assertIn("missing", stderr)
        self.assertIn("_nonexistent_pkg_xyz", stderr)


# ---------------------------------------------------------------------------
# Combined gate interaction
# ---------------------------------------------------------------------------

class TestCombinedGates(unittest.TestCase):
    """Rows may declare both gates; either failing condition drops the row."""

    def _run(self, rows: list[dict]) -> tuple[list[dict], str]:
        buf = io.StringIO()
        with patch("sys.stderr", buf):
            kept = ablation_runs(_config(rows))
        return kept, buf.getvalue()

    def test_both_satisfied(self) -> None:
        """Row passes when both module is importable and torch is new enough."""
        kept, _ = self._run(
            [_row("ok", requires_module="json", requires_torch_min_version="1.0")]
        )
        self.assertEqual(len(kept), 1)

    def test_module_missing_drops_even_if_torch_ok(self) -> None:
        """Missing module drops the row regardless of torch version."""
        kept, stderr = self._run(
            [_row("x", requires_module="_nonexistent_xyz", requires_torch_min_version="1.0")]
        )
        self.assertEqual(kept, [])
        self.assertIn("_nonexistent_xyz", stderr)

    def test_torch_too_old_drops_even_if_module_ok(self) -> None:
        """Old torch drops the row regardless of module availability."""
        kept, stderr = self._run(
            [_row("x", requires_module="json", requires_torch_min_version="9999.0")]
        )
        self.assertEqual(kept, [])
        self.assertIn("9999.0", stderr)


if __name__ == "__main__":
    unittest.main()
