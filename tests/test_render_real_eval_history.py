"""Tests for the real-data history renderer.

The renderer must:
* Round-trip aggregate-only snapshots into a markdown table.
* Refuse to leak per-case fields even if the source files contain them.
* Be idempotent (re-running --check passes after a write).
* Splice cleanly into a doc that may or may not have prior markers.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


def _write_snapshot(history_dir: Path, run_id: str, payload: dict) -> Path:
    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_dir / f"{run_id}.aggregate.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _run_renderer(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/render_real_eval_history.py", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


class RealEvalHistoryRendererTest(unittest.TestCase):
    def setUp(self) -> None:
        # Mirror the real layout in an isolated temp dir so we don't
        # touch the actual repo's docs/ during tests.
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "reports" / "real100" / "history").mkdir(parents=True)
        # Copy the scripts module so subprocess can find it.
        repo_root = Path(__file__).resolve().parents[1]
        # `_eval_delta.py` is the single-source helper module that
        # `run_real_eval_delta.py` imports for fmt_delta / silence_threshold
        # (issue #473). Stage it alongside the other scripts so the
        # subprocess can resolve the sibling import.
        for fname in (
            "_utils.py",
            "_eval_delta.py",
            "run_real_eval_delta.py",
            "render_real_eval_history.py",
        ):
            shutil.copy(repo_root / "scripts" / fname, self.root / "scripts" / fname)
        # __init__.py so `import scripts.run_real_eval_delta` works.
        (self.root / "scripts" / "__init__.py").write_text("")
        self.doc_path = self.root / "docs" / "private-100-doc-experiments.md"
        self.doc_path.write_text(
            "# Private 100-doc Experiments\n\nSome existing content.\n",
            encoding="utf-8",
        )

    def _make_snapshot(self, run_id: str, **overrides) -> Path:
        payload = {
            "num_predictions": 21,
            "accuracy": 0.471,
            "groundedness": 0.476,
            "abstention": 0.5,
            "answer_format_compliance": 0.429,
            "retry": 0.429,
            "provenance": {
                "git_commit": "deadbeefcafe",
                "generated_at": "2026-05-11T00:00:00Z",
            },
            # Forbidden territory — must not leak into rendered table.
            "case_results": [
                {"id": "sensitive_case_id", "query": "비공개 텍스트"}
            ],
        }
        payload.update(overrides)
        return _write_snapshot(
            self.root / "reports" / "real100" / "history", run_id, payload
        )

    def test_writes_table_with_aggregate_only_data(self) -> None:
        self._make_snapshot("20260511T000000Z_deadbeefcafe")
        result = _run_renderer("--doc", str(self.doc_path), cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.doc_path.read_text(encoding="utf-8")
        # Markers + table present:
        self.assertIn("<!-- real-eval-history-start -->", text)
        self.assertIn("<!-- real-eval-history-end -->", text)
        self.assertIn("0.471", text)
        self.assertIn("deadbeefcafe", text)
        self.assertIn("2026-05-11", text)
        # Forbidden strings absent:
        self.assertNotIn("sensitive_case_id", text)
        self.assertNotIn("비공개 텍스트", text)

    def test_check_mode_passes_after_render(self) -> None:
        self._make_snapshot("20260511T000000Z_deadbeefcafe")
        _run_renderer("--doc", str(self.doc_path), cwd=self.root)
        # Second run with --check should report OK.
        result = _run_renderer("--check", "--doc", str(self.doc_path), cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_mode_fails_when_stale(self) -> None:
        # Write nothing yet; add a snapshot; --check should fail because
        # the doc has no marker section.
        self._make_snapshot("20260511T000000Z_deadbeefcafe")
        result = _run_renderer("--check", "--doc", str(self.doc_path), cwd=self.root)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_multiple_snapshots_sorted_chronologically(self) -> None:
        self._make_snapshot(
            "20260601T000000Z_bbb",
            provenance={"git_commit": "bbbbbbbbbbbb", "generated_at": "2026-06-01T00:00:00Z"},
        )
        self._make_snapshot(
            "20260501T000000Z_aaa",
            provenance={"git_commit": "aaaaaaaaaaaa", "generated_at": "2026-05-01T00:00:00Z"},
            accuracy=0.300,
        )
        _run_renderer("--doc", str(self.doc_path), cwd=self.root)
        text = self.doc_path.read_text(encoding="utf-8")
        # The older entry (aaa, accuracy 0.300) must appear before the newer (bbb).
        aaa_pos = text.find("aaaaaaaaaaaa")
        bbb_pos = text.find("bbbbbbbbbbbb")
        self.assertGreater(aaa_pos, 0)
        self.assertGreater(bbb_pos, aaa_pos)

    def test_empty_history_renders_placeholder(self) -> None:
        # No snapshot files at all.
        result = _run_renderer("--doc", str(self.doc_path), cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.doc_path.read_text(encoding="utf-8")
        self.assertIn("No real-data history entries yet", text)


if __name__ == "__main__":
    unittest.main()
