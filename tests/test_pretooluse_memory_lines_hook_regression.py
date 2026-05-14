"""Regression: PreToolUse memory-lines hook (issue #720, axis #5 memory hygiene).

Pins the basename match (MEMORY.md only), the aware/blocked thresholds,
Write-payload counting (file-does-not-exist-yet path), exit code contract
(0 silent / 0 aware / 2 blocked), and the 4-field `.hook-fires.log` format.

Tests isolate `.hook-fires.log` writes into a temp dir so local self-review
artifacts are never polluted.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).parents[1]
HOOK = REPO / "scripts" / "claude-hooks" / "pretooluse-memory-lines.sh"


def _run_hook(payload: dict, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


class TestMemoryLinesHook(unittest.TestCase):
    def setUp(self) -> None:
        # Isolate .hook-fires.log into a per-test temp REPO_ROOT clone.
        self._tmp = tempfile.mkdtemp()
        self._tmp_repo = Path(self._tmp) / "repo"
        (self._tmp_repo / ".claude").mkdir(parents=True)
        (self._tmp_repo / "scripts" / "claude-hooks").mkdir(parents=True)
        shutil.copy(HOOK, self._tmp_repo / "scripts" / "claude-hooks" / HOOK.name)
        self._hook = self._tmp_repo / "scripts" / "claude-hooks" / HOOK.name
        self._fires_log = self._tmp_repo / ".claude" / ".hook-fires.log"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self._hook)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_non_memory_path_is_noop(self) -> None:
        r = self._run({"tool_input": {"file_path": "/tmp/some_other.md"}})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")
        self.assertFalse(self._fires_log.exists())

    def test_existing_file_below_aware_threshold_is_silent(self) -> None:
        target = self._tmp_repo / "MEMORY.md"
        target.write_text("\n".join([f"- entry {i}" for i in range(10)]) + "\n")
        r = self._run({"tool_input": {"file_path": str(target)}})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")
        # action=ok still logs a fire so the ROI collector can count
        # silent-OK invocations too. If we later decide to only log on
        # ok→aware transitions, update both code and this test.
        self.assertTrue(self._fires_log.exists())
        line = self._fires_log.read_text().strip()
        self.assertIn("|ok|memory-lines|", line)

    def test_aware_threshold_emits_stderr_but_exits_zero(self) -> None:
        target = self._tmp_repo / "MEMORY.md"
        target.write_text("\n".join([f"- entry {i}" for i in range(25)]) + "\n")
        r = self._run({"tool_input": {"file_path": str(target)}})
        self.assertEqual(r.returncode, 0)
        self.assertIn("consolidate-memory", r.stderr)
        self.assertIn("25", r.stderr)
        self.assertIn("|aware|memory-lines|", self._fires_log.read_text())

    def test_block_threshold_exits_two(self) -> None:
        target = self._tmp_repo / "MEMORY.md"
        target.write_text("\n".join([f"- entry {i}" for i in range(35)]) + "\n")
        r = self._run({"tool_input": {"file_path": str(target)}})
        self.assertEqual(r.returncode, 2)
        self.assertIn("consolidate-memory", r.stderr)
        self.assertIn("35", r.stderr)
        self.assertIn("|blocked|memory-lines|", self._fires_log.read_text())

    def test_write_payload_counts_for_new_file(self) -> None:
        """Write tool creates a new MEMORY.md — file does not exist yet,
        but `tool_input.content` carries the future contents. Hook must
        count lines from that payload."""
        target = self._tmp_repo / "fresh" / "MEMORY.md"
        # Note: file does NOT exist on disk.
        big_content = "\n".join([f"- entry {i}" for i in range(32)])
        r = self._run({
            "tool_input": {"file_path": str(target), "content": big_content}
        })
        self.assertEqual(r.returncode, 2)
        self.assertIn("32", r.stderr)


if __name__ == "__main__":
    unittest.main()
