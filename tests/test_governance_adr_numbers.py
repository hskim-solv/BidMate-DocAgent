"""Regression tests for ADR number reservation helpers (issue #757).

A2 fix from `~/.claude/plans/fizzy-splashing-cherny-adr-governance.md`:
CLAUDE.md `Reserve ADR numbers up front` was manual + repeatedly broken
under concurrent worktree work. These tests pin the helpers that the
pre-commit hook (`.githooks/pre-commit`) calls so future refactors do
not silently break collision detection.
"""

from __future__ import annotations

from pathlib import Path

from scripts._governance import (
    existing_adr_numbers,
    find_duplicate_adr_numbers,
    next_adr_number,
)


def _touch(dir_: Path, name: str) -> None:
    (dir_ / name).write_text("# stub\n", encoding="utf-8")


# ---- existing_adr_numbers ------------------------------------------------


def test_existing_adr_numbers_empty_dir(tmp_path: Path) -> None:
    assert existing_adr_numbers(tmp_path) == set()


def test_existing_adr_numbers_missing_dir(tmp_path: Path) -> None:
    assert existing_adr_numbers(tmp_path / "nope") == set()


def test_existing_adr_numbers_ignores_non_adr_files(tmp_path: Path) -> None:
    _touch(tmp_path, "README.md")
    _touch(tmp_path, "_template.md")
    _touch(tmp_path, "notes.txt")
    _touch(tmp_path, "0001-naive.md")
    _touch(tmp_path, "0002-metadata-first.md")
    assert existing_adr_numbers(tmp_path) == {1, 2}


def test_existing_adr_numbers_strict_filename_pattern(tmp_path: Path) -> None:
    # 4 digits exactly, kebab slug starting with [a-z0-9], lowercase only.
    _touch(tmp_path, "001-too-short.md")
    _touch(tmp_path, "00001-too-long.md")
    _touch(tmp_path, "0001-UPPER.md")
    _touch(tmp_path, "0001-with-dash.md")
    _touch(tmp_path, "0002-ok.md")
    assert existing_adr_numbers(tmp_path) == {1, 2}


# ---- next_adr_number -----------------------------------------------------


def test_next_adr_number_empty_dir_returns_one(tmp_path: Path) -> None:
    assert next_adr_number(tmp_path) == 1


def test_next_adr_number_returns_max_plus_one(tmp_path: Path) -> None:
    _touch(tmp_path, "0001-a.md")
    _touch(tmp_path, "0005-b.md")
    _touch(tmp_path, "0042-c.md")
    assert next_adr_number(tmp_path) == 43


def test_next_adr_number_ignores_gaps(tmp_path: Path) -> None:
    # A gap in the sequence does NOT renumber — the next is still max+1.
    # This pins ADR-README "Numbers are never reused or renumbered".
    _touch(tmp_path, "0001-a.md")
    _touch(tmp_path, "0010-b.md")
    assert next_adr_number(tmp_path) == 11


# ---- find_duplicate_adr_numbers ------------------------------------------


def test_find_duplicate_adr_numbers_clean(tmp_path: Path) -> None:
    _touch(tmp_path, "0001-a.md")
    _touch(tmp_path, "0002-b.md")
    assert find_duplicate_adr_numbers(tmp_path) == {}


def test_find_duplicate_adr_numbers_catches_collision(tmp_path: Path) -> None:
    _touch(tmp_path, "0044-foo.md")
    _touch(tmp_path, "0044-bar.md")
    _touch(tmp_path, "0045-clean.md")
    dups = find_duplicate_adr_numbers(tmp_path)
    assert dups == {44: ["0044-bar.md", "0044-foo.md"]}


def test_find_duplicate_adr_numbers_missing_dir(tmp_path: Path) -> None:
    assert find_duplicate_adr_numbers(tmp_path / "nope") == {}


# ---- real-data smoke test (sentinel for the live repo) -------------------


def test_repo_adr_dir_has_no_collisions() -> None:
    """If the repo itself ever gains a duplicate, this test catches it
    before CI runs the pre-commit hook in someone else's worktree."""
    assert find_duplicate_adr_numbers("docs/adr") == {}
