"""Regression tests for ADR Consequences verification lint (issue #793).

B3 fix from `~/.claude/plans/fizzy-splashing-cherny-adr-governance.md`:
without a verification circuit, ADR Consequences are unenforced promises
("Decision Theatre" risk). These tests pin the helpers that the
pre-commit hook (`.githooks/pre-commit`) calls when newly added ADR
files appear in a commit.
"""

from __future__ import annotations

from pathlib import Path

from scripts._governance import (
    adr_has_verification_section,
    extract_adr_verification_markers,
    lint_adr_verification,
)


def _adr(tmp_path: Path, name: str, body: str) -> Path:
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    return f


# ---- adr_has_verification_section ----------------------------------------


def test_adr_has_verification_section_present(tmp_path: Path) -> None:
    f = _adr(tmp_path, "0001-stub.md", "## Decision\n\n## Verification\n")
    assert adr_has_verification_section(f) is True


def test_adr_has_verification_section_absent(tmp_path: Path) -> None:
    f = _adr(tmp_path, "0001-stub.md", "## Decision\n\n## Consequences\n")
    assert adr_has_verification_section(f) is False


def test_adr_has_verification_section_missing_file(tmp_path: Path) -> None:
    assert adr_has_verification_section(tmp_path / "nope.md") is False


def test_adr_has_verification_section_case_sensitive(tmp_path: Path) -> None:
    # The h2 header must match exactly. `## verification` (lowercase) does NOT
    # qualify — pins the spec so a casual rename doesn't silently weaken the lint.
    f = _adr(tmp_path, "0001-stub.md", "## verification\n")
    assert adr_has_verification_section(f) is False


# ---- extract_adr_verification_markers ------------------------------------


def test_extract_markers_none(tmp_path: Path) -> None:
    f = _adr(tmp_path, "0001-stub.md", "## Verification\n\nprose only\n")
    assert extract_adr_verification_markers(f) == []


def test_extract_markers_single(tmp_path: Path) -> None:
    body = (
        "## Verification\n"
        "<!-- verifies-key: reports/eval_summary.json:stage_attempts -->\n"
    )
    f = _adr(tmp_path, "0001-stub.md", body)
    assert extract_adr_verification_markers(f) == [
        ("reports/eval_summary.json", "stage_attempts"),
    ]


def test_extract_markers_multiple_in_order(tmp_path: Path) -> None:
    body = (
        "## Verification\n"
        "<!-- verifies-key: a.json:keyA -->\n"
        "<!-- verifies-key: b.json:keyB -->\n"
        "<!-- verifies-key: c.json:keyC -->\n"
    )
    f = _adr(tmp_path, "0001-stub.md", body)
    assert extract_adr_verification_markers(f) == [
        ("a.json", "keyA"),
        ("b.json", "keyB"),
        ("c.json", "keyC"),
    ]


def test_extract_markers_strips_whitespace(tmp_path: Path) -> None:
    body = (
        "## Verification\n"
        "<!--   verifies-key:   reports/x.json   :   my_key   -->\n"
    )
    f = _adr(tmp_path, "0001-stub.md", body)
    assert extract_adr_verification_markers(f) == [("reports/x.json", "my_key")]


def test_extract_markers_missing_file(tmp_path: Path) -> None:
    assert extract_adr_verification_markers(tmp_path / "nope.md") == []


# ---- lint_adr_verification -----------------------------------------------


def test_lint_missing_section(tmp_path: Path) -> None:
    f = _adr(tmp_path, "0001-stub.md", "## Decision\n")
    errors = lint_adr_verification(f, tmp_path)
    assert errors == ["missing `## Verification` H2 section"]


def test_lint_section_present_zero_markers(tmp_path: Path) -> None:
    f = _adr(tmp_path, "0001-stub.md", "## Verification\nprose only\n")
    errors = lint_adr_verification(f, tmp_path)
    assert len(errors) == 1
    assert "zero" in errors[0]
    assert "verifies-key" in errors[0]


def test_lint_marker_with_missing_target_is_ok(tmp_path: Path) -> None:
    # Missing target file is informational only — many envs don't have
    # `reports/` (fresh clones, smoke runs). Lint stays silent so it doesn't
    # block commits on environments that can't produce the artifact.
    body = (
        "## Verification\n"
        "<!-- verifies-key: nonexistent/file.json:any_key -->\n"
    )
    f = _adr(tmp_path, "0001-stub.md", body)
    assert lint_adr_verification(f, tmp_path) == []


def test_lint_marker_with_present_key_passes(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_text('{"stage_attempts": [1, 2]}\n', encoding="utf-8")
    body = (
        "## Verification\n"
        "<!-- verifies-key: report.json:stage_attempts -->\n"
    )
    f = _adr(tmp_path, "0001-stub.md", body)
    assert lint_adr_verification(f, tmp_path) == []


def test_lint_marker_with_absent_key_fails(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_text('{"other_field": 1}\n', encoding="utf-8")
    body = (
        "## Verification\n"
        "<!-- verifies-key: report.json:stage_attempts -->\n"
    )
    f = _adr(tmp_path, "0001-stub.md", body)
    errors = lint_adr_verification(f, tmp_path)
    assert len(errors) == 1
    assert "stage_attempts" in errors[0]
    assert "report.json" in errors[0]
    assert "not wired up" in errors[0]


def test_lint_multiple_markers_partial_failure(tmp_path: Path) -> None:
    (tmp_path / "good.json").write_text('{"present": 1}\n', encoding="utf-8")
    (tmp_path / "bad.json").write_text('{"other": 1}\n', encoding="utf-8")
    body = (
        "## Verification\n"
        "<!-- verifies-key: good.json:present -->\n"
        "<!-- verifies-key: bad.json:missing_key -->\n"
        "<!-- verifies-key: ghost.json:any -->\n"  # missing file = informational
    )
    f = _adr(tmp_path, "0001-stub.md", body)
    errors = lint_adr_verification(f, tmp_path)
    # Only the bad.json:missing_key produces an error; ghost.json is silent.
    assert len(errors) == 1
    assert "missing_key" in errors[0]


def test_lint_missing_adr_file(tmp_path: Path) -> None:
    errors = lint_adr_verification(tmp_path / "nope.md", tmp_path)
    assert len(errors) == 1
    assert "not found" in errors[0]


# ---- real-data sentinel (live repo) --------------------------------------


def test_repo_template_passes_lint() -> None:
    """`docs/adr/_template.md` must always pass its own contract.

    The template ships with `## Verification` + one example marker
    pointing at a real path (`scripts/_governance.py` or
    `reports/eval_summary.json`). If a future edit breaks the template,
    this test catches it before the pre-commit hook does in someone
    else's worktree.
    """
    assert lint_adr_verification("docs/adr/_template.md", ".") == []
