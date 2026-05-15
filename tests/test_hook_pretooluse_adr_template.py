"""Regression: PreToolUse ADR-template hook (issue #826 Hook C / #866).

Pins the contract of ``scripts/claude-hooks/pretooluse-adr-template.sh``:

  - Allow Write of any file that isn't a new ADR (other path, wrong
    extension, existing ADR being edited).
  - Block Write of a new ``docs/adr/<NNNN>-*.md`` when payload lacks
    either the ``## Verification`` H2 section or any
    ``<!-- verifies-key: path:key -->`` marker.
  - Pass when payload has both, even minimally.
  - Fall through for non-Write tools (Edit / MultiEdit / Bash).
  - ``.hook-fires.log`` line format matches the bash-guard convention
    so ``_self_review.py`` rolling-window summaries pick up the event.
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
HOOK = REPO / "scripts" / "claude-hooks" / "pretooluse-adr-template.sh"


_GOOD_BODY = (
    "# ADR 9999 — Example\n\n"
    "## Context\n\nx\n\n"
    "## Decision\n\ny\n\n"
    "## Verification\n\n"
    "<!-- verifies-key: scripts/_governance.py:LOAD_BEARING_PATHS -->\n"
)

_MISSING_SECTION_BODY = (
    "# ADR 9999 — Example\n\n"
    "## Context\n\nx\n\n"
    "## Decision\n\ny\n\n"
    "<!-- verifies-key: scripts/_governance.py:LOAD_BEARING_PATHS -->\n"
)

_MISSING_MARKER_BODY = (
    "# ADR 9999 — Example\n\n"
    "## Context\n\nx\n\n"
    "## Decision\n\ny\n\n"
    "## Verification\n\n"
    "Will be filled in when G2 lands.\n"
)


class TestPreToolUseAdrTemplate(unittest.TestCase):
    """Contract for the new-ADR Write-time Verification guard."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._tmp_repo = Path(self._tmp) / "repo"
        (self._tmp_repo / ".claude").mkdir(parents=True)
        (self._tmp_repo / "scripts" / "claude-hooks").mkdir(parents=True)
        (self._tmp_repo / "docs" / "adr").mkdir(parents=True)
        shutil.copy(HOOK, self._tmp_repo / "scripts" / "claude-hooks" / HOOK.name)
        self._hook = self._tmp_repo / "scripts" / "claude-hooks" / HOOK.name
        self._fires_log = self._tmp_repo / ".claude" / ".hook-fires.log"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(
        self,
        *,
        tool_name: str = "Write",
        file_path: str | Path = "docs/adr/9999-example.md",
        content: str = _GOOD_BODY,
    ) -> subprocess.CompletedProcess:
        payload = {
            "tool_name": tool_name,
            "tool_input": {"file_path": str(file_path), "content": content},
        }
        return subprocess.run(
            ["bash", str(self._hook)],
            input=json.dumps(payload), text=True,
            capture_output=True, check=False,
            cwd=str(self._tmp_repo),
        )

    # ------------------------------------------------------------------
    # Pass-through cases
    # ------------------------------------------------------------------

    def test_non_write_tool_is_noop(self) -> None:
        """Edit / MultiEdit on existing files: pre-commit lint's domain."""
        r = self._run(tool_name="Edit",
                      file_path=self._tmp_repo / "docs" / "adr" / "9999-x.md",
                      content="")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")

    def test_non_adr_path_is_noop(self) -> None:
        r = self._run(file_path="src/foo.py", content="print('hi')\n")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")

    def test_adr_directory_but_non_numbered_filename_is_noop(self) -> None:
        """``docs/adr/_template.md`` and ``docs/adr/README.md`` are exempt."""
        for name in ("_template.md", "README.md", "_my-notes.md"):
            with self.subTest(name=name):
                r = self._run(file_path=f"docs/adr/{name}",
                              content="anything\n")
                self.assertEqual(r.returncode, 0)

    def test_existing_adr_file_is_passthrough(self) -> None:
        """An ADR file already on disk = edit, not a new ADR. Pass through."""
        adr = self._tmp_repo / "docs" / "adr" / "9000-already-there.md"
        adr.write_text("stale body\n")
        r = self._run(file_path=adr, content="rewritten body\n")
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stderr, "")

    def test_empty_command_payload_is_noop(self) -> None:
        """Malformed / empty JSON should fail-open per hook contract."""
        r = subprocess.run(
            ["bash", str(self._hook)],
            input="{}", text=True, capture_output=True, check=False,
            cwd=str(self._tmp_repo),
        )
        self.assertEqual(r.returncode, 0)

    # ------------------------------------------------------------------
    # Block cases
    # ------------------------------------------------------------------

    def test_new_adr_missing_verification_section_is_blocked(self) -> None:
        r = self._run(content=_MISSING_SECTION_BODY)
        self.assertEqual(r.returncode, 2, msg=r.stderr)
        self.assertIn("Verification", r.stderr)
        self.assertIn("section", r.stderr)
        self.assertTrue(self._fires_log.exists())
        line = self._fires_log.read_text().strip()
        self.assertIn("|blocked|adr-template|", line)
        self.assertIn("9999-example.md", line)
        self.assertIn("missing=section", line)

    def test_new_adr_missing_marker_is_blocked(self) -> None:
        r = self._run(content=_MISSING_MARKER_BODY)
        self.assertEqual(r.returncode, 2, msg=r.stderr)
        self.assertIn("verifies-key", r.stderr)
        line = self._fires_log.read_text().strip()
        self.assertIn("missing=marker", line)

    def test_new_adr_missing_both_lists_both_in_log(self) -> None:
        r = self._run(content="# ADR 9999\n\n## Context\n\njust prose\n")
        self.assertEqual(r.returncode, 2)
        line = self._fires_log.read_text().strip()
        self.assertIn("missing=section,marker", line)

    def test_block_message_quotes_template(self) -> None:
        """Operator-facing rationale must include the template inline."""
        r = self._run(content="# ADR 9999\n\n## Context\n\nx\n")
        self.assertEqual(r.returncode, 2)
        self.assertIn("## Verification", r.stderr)
        self.assertIn("verifies-key: <relative-path>:<key-substring>", r.stderr)
        self.assertIn("docs/adr/_template.md", r.stderr)

    # ------------------------------------------------------------------
    # Allow cases — payload is valid
    # ------------------------------------------------------------------

    def test_new_adr_with_complete_verification_is_allowed(self) -> None:
        r = self._run(content=_GOOD_BODY)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stderr, "")
        # No block log entry when payload is clean.
        self.assertFalse(self._fires_log.exists())

    def test_marker_recognized_with_extra_whitespace(self) -> None:
        """Mirrors ``_governance.py::ADR_VERIFIES_KEY_RE`` flexibility."""
        body = (
            "## Verification\n\n"
            "<!--   verifies-key:   scripts/_governance.py  :  LOAD_BEARING  -->\n"
        )
        r = self._run(content=body)
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_section_header_recognized_with_trailing_whitespace(self) -> None:
        body = (
            "## Verification   \n\n"
            "<!-- verifies-key: x.py:y -->\n"
        )
        r = self._run(content=body)
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_absolute_file_path_works(self) -> None:
        """``file_path`` from Claude is typically absolute. Match both."""
        abs_path = self._tmp_repo / "docs" / "adr" / "9999-abs.md"
        r = self._run(file_path=abs_path, content=_GOOD_BODY)
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_absolute_file_path_blocks_when_missing(self) -> None:
        abs_path = self._tmp_repo / "docs" / "adr" / "9999-abs.md"
        r = self._run(file_path=abs_path, content=_MISSING_SECTION_BODY)
        self.assertEqual(r.returncode, 2, msg=r.stderr)


if __name__ == "__main__":
    unittest.main()
