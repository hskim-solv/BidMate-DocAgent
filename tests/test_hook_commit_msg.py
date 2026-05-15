"""Tests for the commit-msg hook (issue #826 Hook A).

The hook lives at ``.githooks/commit-msg``. It is invoked by git with the
path to ``COMMIT_EDITMSG`` as ``$1``. Tests exercise it via a temporary
git repository so the production hook script is exactly what runs in CI
/ developer workstations — no shim / mock.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
HOOK_PATH = ROOT_DIR / ".githooks" / "commit-msg"


def _run_hook(
    *,
    branch: str,
    message: str,
    tmp_path: Path,
) -> tuple[int, str]:
    """Invoke the production hook against ``message`` in a tmp git repo.

    Returns ``(exit_code, stderr_text)`` so callers can assert both the
    block decision and the operator-facing message.
    """
    # Tiny git repo — needed so ``git symbolic-ref --short HEAD`` inside
    # the hook returns the right branch name.
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-b", branch, str(repo)], check=True,
                   capture_output=True, env=env)
    # Write the candidate commit message to a temp file just like git would.
    msg_file = repo / ".git" / "COMMIT_EDITMSG_TEST"
    msg_file.write_text(message, encoding="utf-8")
    result = subprocess.run(
        [str(HOOK_PATH), str(msg_file)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stderr


class TestCommitMsgHook:
    """Behavioral contract for the ADR-0007 commit-level guard."""

    def test_passes_when_commit_references_branch_issue(self, tmp_path: Path) -> None:
        """The happy path: branch is feat/issue-99-x, message has 'closes #99'."""
        code, _ = _run_hook(
            branch="feat/issue-99-some-slug",
            message="feat: add widget X\n\nLong body...\nCloses #99\n",
            tmp_path=tmp_path,
        )
        assert code == 0

    def test_rejects_when_commit_missing_issue_reference(self, tmp_path: Path) -> None:
        """The core guard: branch claims #99 but message has no reference."""
        code, stderr = _run_hook(
            branch="feat/issue-99-foo",
            message="feat: add widget without ref\n\nNo closes line.\n",
            tmp_path=tmp_path,
        )
        assert code == 1
        assert "#99" in stderr
        assert "closes" in stderr.lower() or "fixes" in stderr.lower()

    def test_rejects_when_commit_references_wrong_issue(self, tmp_path: Path) -> None:
        """Cross-issue contamination: feat/issue-99 with 'closes #88' must fail."""
        code, _ = _run_hook(
            branch="feat/issue-99-x",
            message="feat: fixes a different bug\n\nCloses #88\n",
            tmp_path=tmp_path,
        )
        assert code == 1

    def test_accepts_fixes_keyword(self, tmp_path: Path) -> None:
        code, _ = _run_hook(
            branch="fix/issue-42-bug",
            message="fix: tweak\n\nFixes #42\n",
            tmp_path=tmp_path,
        )
        assert code == 0

    def test_accepts_resolves_keyword(self, tmp_path: Path) -> None:
        code, _ = _run_hook(
            branch="docs/issue-7-cleanup",
            message="docs: cleanup\n\nresolves #7\n",
            tmp_path=tmp_path,
        )
        assert code == 0

    def test_case_insensitive_keywords(self, tmp_path: Path) -> None:
        code, _ = _run_hook(
            branch="feat/issue-5-x",
            message="feat: thing\n\nCLOSES #5\n",
            tmp_path=tmp_path,
        )
        assert code == 0

    def test_word_boundary_rejects_substring_match(self, tmp_path: Path) -> None:
        """Branch #9 must not be satisfied by '#99' (word-boundary guard)."""
        code, _ = _run_hook(
            branch="feat/issue-9-x",
            message="feat: x\n\nCloses #99\n",
            tmp_path=tmp_path,
        )
        assert code == 1

    def test_skips_non_conventional_branch(self, tmp_path: Path) -> None:
        """Legacy / hotfix branches without ADR 0007 convention are exempt."""
        code, _ = _run_hook(
            branch="hotfix/some-thing",
            message="hotfix: emergency\n",
            tmp_path=tmp_path,
        )
        assert code == 0

    def test_skips_main_branch(self, tmp_path: Path) -> None:
        """Direct commits to main are covered by a separate guard."""
        code, _ = _run_hook(
            branch="main",
            message="chore: thing\n",
            tmp_path=tmp_path,
        )
        assert code == 0

    def test_skips_merge_commits(self, tmp_path: Path) -> None:
        """Merge commits inherit their refs from the rewritten history."""
        code, _ = _run_hook(
            branch="feat/issue-100-x",
            message="Merge branch 'main' into feat/issue-100-x\n",
            tmp_path=tmp_path,
        )
        assert code == 0

    @pytest.mark.parametrize("prefix", ["fixup!", "squash!"])
    def test_skips_fixup_and_squash(self, tmp_path: Path, prefix: str) -> None:
        """git autosquash messages don't need their own refs."""
        code, _ = _run_hook(
            branch="feat/issue-50-x",
            message=f"{prefix} the previous commit\n",
            tmp_path=tmp_path,
        )
        assert code == 0

    def test_skips_revert_commits(self, tmp_path: Path) -> None:
        code, _ = _run_hook(
            branch="feat/issue-77-x",
            message='Revert "feat: thing (closes #1)"\n\nThis reverts ...\n',
            tmp_path=tmp_path,
        )
        assert code == 0

    @pytest.mark.parametrize(
        "branch_type", ["feat", "fix", "docs", "chore", "refactor", "test", "ci", "perf", "build", "style"]
    )
    def test_all_branch_types_recognized(self, tmp_path: Path, branch_type: str) -> None:
        """All ADR-0007 branch type prefixes trigger the check."""
        code, _ = _run_hook(
            branch=f"{branch_type}/issue-1-slug",
            message=f"{branch_type}: x\n\nNo ref here.\n",
            tmp_path=tmp_path,
        )
        assert code == 1, f"branch type {branch_type!r} should have triggered check"

    def test_unknown_branch_type_skipped(self, tmp_path: Path) -> None:
        """A branch like ``release/v1.2`` is outside ADR 0007 — must skip."""
        code, _ = _run_hook(
            branch="release/v1.2",
            message="release: v1.2\n",
            tmp_path=tmp_path,
        )
        assert code == 0
