"""Regex tests for branch naming convention + Closes-#N parsing (ADR 0007).

The regexes live in `scripts/check_branch_and_issue.py` (single source of
truth used by both `.githooks/pre-push` and `.github/workflows/
branch-and-issue-check.yml`). We import them here so any future change
to the convention forces a corresponding test update.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import check_branch_and_issue as cbi  # noqa: E402


@pytest.mark.parametrize("name", [
    "feat/issue-79-senior-positioning",
    "feat/issue-104-mermaid-diagram",
    "fix/issue-87",
    "fix/issue-87-trailing-slug",
    "docs/issue-130-pre-commit-hook",
    "chore/issue-150-update-deps",
    "refactor/issue-12-extract-helper",
    "test/issue-50-regression",
    "ci/issue-100-add-workflow",
    "perf/issue-66-cache-embeddings",
    "build/issue-200",
    "style/issue-1-format",
])
def test_branch_regex_accepts_conventional(name):
    assert cbi.BRANCH_REGEX.match(name), f"expected accept: {name}"


@pytest.mark.parametrize("name", [
    "claude/issue-79-foo",
    "claude/epic-saha-0d9d25",
    "claude/agitated-shirley-dfa25e",
    "feat/79-foo",
    "feat/issue-abc-foo",
    "feat/issue--foo",
    "feature/issue-1-foo",
    "main",
    "develop",
    "fix-something",
    "feat/issue-1-WithUpperCase",
    "feat/issue-1-with_underscore",
    "feat/ISSUE-1-foo",
    "feat/issue-1-trailing-",
    "",
])
def test_branch_regex_rejects_off_pattern(name):
    assert not cbi.BRANCH_REGEX.match(name), f"expected reject: {name!r}"


@pytest.mark.parametrize("name", [
    "revert-123-old-branch",
    "dependabot/pip/requests-2.31.0",
    "renovate/python-3.x",
    "pre-commit-ci/update-config",
])
def test_exempt_regex_matches_bot_branches(name):
    assert cbi.EXEMPT_REGEX.match(name), f"expected exempt: {name}"


@pytest.mark.parametrize("name,expected", [
    ("feat/issue-79-foo", 79),
    ("fix/issue-104", 104),
    ("revert-123-old", None),
    ("dependabot/pip/x", None),
])
def test_parse_branch_returns_issue_number(name, expected):
    assert cbi.parse_branch(name) == expected


@pytest.mark.parametrize("name", [
    "claude/issue-1-foo",
    "main",
    "feat/no-issue",
])
def test_parse_branch_raises_on_violation(name):
    with pytest.raises(ValueError):
        cbi.parse_branch(name)


@pytest.mark.parametrize("body,expected", [
    ("Closes #42", ["42"]),
    ("closes #1, fixes #2", ["1", "2"]),
    ("Resolves #99\n\nMore text", ["99"]),
    ("Closes #5.", ["5"]),
    ("CLOSES #7", ["7"]),
    ("No issue ref here", []),
    ("Closes#5", []),
    ("Will close #5", []),
    ("discloses #5", []),
    ("", []),
])
def test_closes_regex_finds_issue_refs(body, expected):
    assert cbi.CLOSES_REGEX.findall(body) == expected
