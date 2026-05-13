"""Privacy regression guard for _self_review.assemble_stats (issue #501).

assemble_stats() must never include body text (message content, tool
arguments, code diffs, memory body) in the stats dict it produces.
This test verifies the invariant holds without any external fixtures —
it synthesises minimal in-memory transcripts and memory files to drive
the collectors.

Two independent checks:
1. ``collect_sessions`` — pass a synthetic .jsonl that embeds body text
   in tool arguments; verify body text does NOT appear in the output.
2. ``collect_memory`` — pass a synthetic memory dir whose files have rich
   body content; verify body text does NOT appear in the output.

The git/governance collectors read only metadata (SHA, dates, file paths),
so they are covered by structural assertion rather than injection test.
"""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

SCRIPTS_HOOKS = Path(__file__).parents[1] / "scripts" / "claude-hooks"
if str(SCRIPTS_HOOKS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_HOOKS))

from _self_review import assemble_stats, collect_memory, collect_sessions


# ---------------------------------------------------------------------------
# Forbidden token set — any of these appearing in stats output is a leak
# ---------------------------------------------------------------------------

FORBIDDEN_TOKENS = [
    "user said",
    "사용자가 말",
    "SECRET_BODY_TEXT",
    "MEMORY_BODY_SECRET",
    "```",
    "---\n",   # diff marker (multiline)
    "+++",
]


def _serialized(obj: object) -> str:
    """Flatten any dict/list/scalar to a single JSON string for token scanning.

    json.dumps captures both keys and values, so forbidden tokens embedded
    in either position are caught.
    """
    return json.dumps(obj, ensure_ascii=False)


def _assert_no_forbidden(stats: dict, test_case: unittest.TestCase) -> None:
    combined = _serialized(stats)
    for token in FORBIDDEN_TOKENS:
        test_case.assertNotIn(
            token,
            combined,
            f"Privacy leak: forbidden token '{token}' found in stats output.",
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class CollectSessionsNoBodyLeakTest(unittest.TestCase):
    """collect_sessions must not capture tool arguments or message body."""

    def _make_jsonl(self, tmp: Path) -> Path:
        """Synthetic .jsonl with body-containing tool_use records."""
        record = {
            "sessionId": "session-abc",
            "timestamp": "2026-05-01T12:00:00Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {
                            "command": "echo SECRET_BODY_TEXT",
                            "description": "user said run this",
                        },
                    },
                    {
                        "type": "tool_use",
                        "name": "Agent",
                        "input": {
                            "subagent_type": "Explore",
                            "prompt": "MEMORY_BODY_SECRET embedded prompt",
                        },
                    },
                ],
            },
        }
        f = tmp / "test_session.jsonl"
        f.write_text(json.dumps(record) + "\n")
        return tmp

    def test_session_stats_contain_no_body_text(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self._make_jsonl(tmp)
            result = collect_sessions(
                str(tmp / "*.jsonl"),
                start="2026-05-01",
                end="2026-05-31",
            )
            combined = _serialized(result)
            self.assertNotIn("SECRET_BODY_TEXT", combined)
            self.assertNotIn("user said", combined)
            self.assertNotIn("MEMORY_BODY_SECRET", combined)
            # Tool name and subagent_type (metadata keys) MUST appear
            self.assertIn("Bash", combined)
            self.assertIn("Explore", combined)


class CollectMemoryNoBodyLeakTest(unittest.TestCase):
    """collect_memory must read only frontmatter, never body."""

    def _make_memory_dir(self, tmp: Path) -> Path:
        """Synthetic memory dir with body-rich .md files."""
        mem_dir = tmp / "memory"
        mem_dir.mkdir()

        # A well-formed memory file with body content
        (mem_dir / "user_role.md").write_text(textwrap.dedent("""\
            ---
            name: user role
            description: test description
            type: user
            ---

            MEMORY_BODY_SECRET: user is a senior engineer. user said things.
            ```python
            SECRET_BODY_TEXT = True
            ```
        """))

        # MEMORY.md index — should be ignored by collect_memory
        (mem_dir / "MEMORY.md").write_text(textwrap.dedent("""\
            - [user_role](user_role.md) — SECRET_BODY_TEXT in index
        """))

        return mem_dir

    def test_memory_stats_contain_no_body_text(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            mem_dir = self._make_memory_dir(Path(d))
            result = collect_memory(str(mem_dir))
            combined = _serialized(result)
            self.assertNotIn("MEMORY_BODY_SECRET", combined)
            self.assertNotIn("SECRET_BODY_TEXT", combined)
            self.assertNotIn("user said", combined)
            # Frontmatter metadata IS allowed
            self.assertIn("user_role.md", combined)
            self.assertIn("user", combined)  # type field


class AssembleStatsStructuralTest(unittest.TestCase):
    """assemble_stats output has correct top-level keys, all metadata."""

    def test_top_level_keys_present(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            # Empty transcripts glob → no sessions
            # Empty memory dir → no memories
            # Use current repo dir for git/governance (existing repo)
            repo = str(Path(__file__).parents[1])
            stats = assemble_stats(
                quarter="Q2-2026",
                transcripts_glob=str(tmp / "*.jsonl"),
                memory_dir=str(tmp / "memory"),
                repo=repo,
            )
        expected_keys = {"quarter", "date_range", "sessions", "memory", "git", "governance_hooks"}
        self.assertEqual(set(stats.keys()), expected_keys)

    def test_sessions_keys_are_metadata_only(self) -> None:
        """sessions block must only contain count and distribution maps."""
        with tempfile.TemporaryDirectory() as d:
            repo = str(Path(__file__).parents[1])
            stats = assemble_stats(
                quarter="Q2-2026",
                transcripts_glob=str(Path(d) / "*.jsonl"),
                memory_dir=str(Path(d) / "memory"),
                repo=repo,
            )
        session_keys = set(stats["sessions"].keys())
        allowed = {"count", "tool_call_distribution", "agent_delegations"}
        self.assertLessEqual(session_keys, allowed,
                             f"sessions block has unexpected keys: {session_keys - allowed}")

    def test_git_block_no_commit_subjects(self) -> None:
        """git block must NOT contain full commit subjects (only SHAs/dates/numbers)."""
        with tempfile.TemporaryDirectory() as d:
            repo = str(Path(__file__).parents[1])
            stats = assemble_stats(
                quarter="Q2-2026",
                transcripts_glob=str(Path(d) / "*.jsonl"),
                memory_dir=str(Path(d) / "memory"),
                repo=repo,
            )
        # Each merged PR entry must have exactly {number, sha, date}
        for pr in stats["git"].get("prs_merged", []):
            pr_keys = set(pr.keys())
            self.assertLessEqual(pr_keys, {"number", "sha", "date"},
                                 f"PR entry has unexpected keys: {pr_keys}")

    def test_no_forbidden_tokens_in_real_repo_stats(self) -> None:
        """Full assemble_stats run against the real repo must have no body leaks."""
        with tempfile.TemporaryDirectory() as d:
            repo = str(Path(__file__).parents[1])
            stats = assemble_stats(
                quarter="Q2-2026",
                transcripts_glob=str(Path(d) / "*.jsonl"),
                memory_dir=str(Path(d) / "memory"),
                repo=repo,
            )
        _assert_no_forbidden(stats, self)


if __name__ == "__main__":
    unittest.main()
