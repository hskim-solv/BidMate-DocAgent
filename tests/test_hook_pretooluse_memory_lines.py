"""Regression coverage for the memory-lines PreToolUse hook (issue #1683, #1685).

The hook (`scripts/claude-hooks/pretooluse-memory-lines.sh`) must gate the
MEMORY.md auto-memory index on the *resulting* line count, not the existing
one. The historical bug: Edit/MultiEdit payloads carry old_string/new_string
(not `content`), so the hook fell back to counting the existing file and
blocked even edits that shrink the index under the cap — making the
consolidate-memory remedy it asks for impossible to apply via Edit.

Each test runs a COPY of the hook under a throwaway REPO_ROOT (the hook +
_governance.py mirrored into a temp tree, the bash-guard test isolation
pattern). That keeps the hook's ``--emit-fire`` telemetry writes inside the
temp ``.claude/.hook-fires.log`` instead of polluting the developer's real
axis-#5 self-review fire log (issue #1685).
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "claude-hooks" / "pretooluse-memory-lines.sh"
GOVERNANCE = REPO_ROOT / "scripts" / "_governance.py"


def _threshold(name: str, default: int) -> int:
    """Read a threshold from the governance SSoT, falling back to a default."""
    try:
        out = subprocess.run(
            ["python3", str(GOVERNANCE), "--threshold", name],
            capture_output=True,
            text=True,
            check=False,
        )
        return int(out.stdout.strip())
    except (ValueError, OSError):
        return default


BLOCK = _threshold("MEMORY_LINE_BLOCK", 30)


def _index_lines(n: int) -> str:
    """Build an `n`-line MEMORY.md-style index body (trailing newline)."""
    return "".join(f"- [entry {i}](file_{i}.md) — hook for entry {i}\n" for i in range(1, n + 1))


class MemoryLinesHookTest(unittest.TestCase):
    """Exit-code contract for the memory-lines PreToolUse hook."""

    def setUp(self) -> None:
        # Mirror the production layout (scripts/claude-hooks/ under a repo
        # root) so the hook's REPO_ROOT resolution and `.hook-fires.log`
        # telemetry writes target this temp tree, not the developer's real
        # axis-#5 fire log (issue #1685). Same isolation pattern as the
        # bash-guard test.
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmpdir.name) / "repo"
        (self.repo / ".claude").mkdir(parents=True)
        (self.repo / "scripts" / "claude-hooks").mkdir(parents=True)
        self.hook = self.repo / "scripts" / "claude-hooks" / HOOK.name
        shutil.copy(HOOK, self.hook)
        shutil.copy(GOVERNANCE, self.repo / "scripts" / "_governance.py")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _run(self, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.hook)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )

    def _write_index(self, n: int) -> Path:
        """Create the temp-tree MEMORY.md with `n` index lines and return it."""
        path = self.repo / "MEMORY.md"
        path.write_text(_index_lines(n), encoding="utf-8")
        return path

    # --- Write -------------------------------------------------------------

    def test_write_shrink_under_cap_allowed(self) -> None:
        """Write that brings the index from cap -> cap-3 lines is ALLOWED."""
        path = self._write_index(BLOCK)
        proc = self._run(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(path), "content": _index_lines(BLOCK - 3)},
            }
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_write_grow_past_cap_blocked(self) -> None:
        """Write that grows the index from under-cap to over-cap is BLOCKED."""
        path = self._write_index(BLOCK - 3)
        proc = self._run(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(path), "content": _index_lines(BLOCK + 1)},
            }
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)

    def test_write_new_file_over_cap_blocked(self) -> None:
        """A brand-new index created over the cap is BLOCKED."""
        path = self.repo / "MEMORY.md"  # does not exist yet
        proc = self._run(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(path), "content": _index_lines(BLOCK + 1)},
            }
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)

    # --- Edit (the regression) --------------------------------------------

    def test_edit_shrink_under_cap_allowed(self) -> None:
        """Edit deleting lines from a cap-sized index down under cap is ALLOWED.

        This is the core #1683 fix: Edit carries old_string/new_string, not
        `content`, and previously the hook counted the existing (over-cap)
        file and refused the very consolidation it demanded.
        """
        path = self._write_index(BLOCK)
        # Remove three whole lines by replacing them with nothing.
        removed = "".join(
            f"- [entry {i}](file_{i}.md) — hook for entry {i}\n" for i in (BLOCK - 2, BLOCK - 1, BLOCK)
        )
        proc = self._run(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(path),
                    "old_string": removed,
                    "new_string": "",
                },
            }
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_edit_grow_past_cap_blocked(self) -> None:
        """Edit that grows an under-cap index past the cap is BLOCKED."""
        path = self._write_index(BLOCK - 1)
        anchor = "- [entry 1](file_1.md) — hook for entry 1\n"
        added = anchor + "".join(
            f"- [added {j}](added_{j}.md) — added line {j}\n" for j in range(1, 4)
        )
        proc = self._run(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(path),
                    "old_string": anchor,
                    "new_string": added,
                },
            }
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)

    # --- MultiEdit (issue #1685 coverage gap) -----------------------------

    def test_multiedit_shrink_under_cap_allowed(self) -> None:
        """MultiEdit deleting two lines from a cap-sized index is ALLOWED.

        Guards the MultiEdit branch of the resulting-count reconstruction,
        which is otherwise uncovered by the Write/Edit cases.
        """
        path = self._write_index(BLOCK)
        edits = [
            {"old_string": f"- [entry {i}](file_{i}.md) — hook for entry {i}\n", "new_string": ""}
            for i in (BLOCK - 1, BLOCK)
        ]
        proc = self._run(
            {
                "tool_name": "MultiEdit",
                "tool_input": {"file_path": str(path), "edits": edits},
            }
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    # --- Shrink that is still over cap ------------------------------------

    def test_shrink_still_over_cap_allowed(self) -> None:
        """A pure shrink is allowed even when the result is still over cap."""
        path = self._write_index(BLOCK + 5)
        proc = self._run(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(path), "content": _index_lines(BLOCK + 2)},
            }
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    # --- Non-target files -------------------------------------------------

    def test_non_memory_file_ignored(self) -> None:
        """A non-MEMORY.md path is never gated, regardless of size."""
        path = self.repo / "NOTES.md"
        proc = self._run(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(path), "content": _index_lines(BLOCK + 50)},
            }
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
