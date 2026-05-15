"""Regression tests for ADR ↔ README index parity (issue #803).

The CI gate ``tests/test_governance.py::test_no_unlinked_adr_files_on_disk``
fires *after* push and cascades red Pytest across every open PR when an
ADR PR merges with the row missing from ``docs/adr/README.md`` (see
#730 / #732 / #750 recurrence trail). The pre-commit hook calls
``adr_readme_parity_violations`` to shift the same check left so the
author finds out at ``git commit`` time.

These tests pin the helper behavior + the CLI wrapper so a refactor of
either side cannot silently regress the pre-commit guard.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts._governance import adr_readme_parity_violations

REPO_ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE_CLI = REPO_ROOT / "scripts" / "_governance.py"


# ---- adr_readme_parity_violations ----------------------------------------


def _readme_with(rows: list[tuple[str, str, str]]) -> str:
    """Build a minimal README fragment with the canonical row format.

    Each row tuple is ``(NNNN, filename, "status | title")``.
    """
    body = ["# ADRs\n", "## Index\n"]
    body.append("| ADR | Status | Title |\n")
    body.append("|---|---|---|\n")
    for num, filename, suffix in rows:
        body.append(f"| [{num}](./{filename}) | {suffix} |\n")
    return "".join(body)


def test_parity_empty_input_returns_empty() -> None:
    # Empty ADR list should never report violations even if README is empty.
    assert adr_readme_parity_violations([], "") == []
    assert adr_readme_parity_violations([], "no rows here") == []


def test_parity_matching_row_passes() -> None:
    readme = _readme_with(
        [("0044", "0044-realN-eval-case-expansion.md", "proposed | realN")]
    )
    missing = adr_readme_parity_violations(
        ["docs/adr/0044-realN-eval-case-expansion.md"],
        readme,
    )
    assert missing == []


def test_parity_missing_row_returns_filename() -> None:
    readme = _readme_with([("0001", "0001-other.md", "accepted | other")])
    missing = adr_readme_parity_violations(
        ["docs/adr/0044-realN-eval-case-expansion.md"],
        readme,
    )
    assert missing == ["0044-realN-eval-case-expansion.md"]


def test_parity_accepts_just_basename() -> None:
    # Helper must use only the basename so callers can pass full paths
    # (pre-commit hook) or bare filenames (CLI tests) interchangeably.
    readme = _readme_with([("0044", "0044-realN.md", "proposed | x")])
    assert adr_readme_parity_violations(["0044-realN.md"], readme) == []
    assert (
        adr_readme_parity_violations(
            ["docs/adr/0044-realN.md"], readme,
        )
        == []
    )


def test_parity_reports_only_missing_subset() -> None:
    readme = _readme_with(
        [
            ("0001", "0001-alpha.md", "accepted | a"),
            ("0002", "0002-beta.md", "accepted | b"),
        ]
    )
    missing = adr_readme_parity_violations(
        [
            "docs/adr/0001-alpha.md",
            "docs/adr/0002-beta.md",
            "docs/adr/0003-gamma.md",
        ],
        readme,
    )
    assert missing == ["0003-gamma.md"]


def test_parity_row_must_use_canonical_format() -> None:
    # A bare `0044-x.md` mention in prose does NOT count — the row must
    # use the canonical `| [NNNN](./...md) |` pipe-table form because
    # that is what the CI gate parses.
    prose_only = "See 0044-x.md for details.\n"
    missing = adr_readme_parity_violations(["0044-x.md"], prose_only)
    assert missing == ["0044-x.md"]


# ---- CLI wrapper (working-tree mode) -------------------------------------


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GOVERNANCE_CLI), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


def test_cli_passes_when_readme_has_row(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        _readme_with([("0099", "0099-test.md", "proposed | test")]),
        encoding="utf-8",
    )
    result = _run_cli(
        "--check-adr-readme-parity",
        "docs/adr/0099-test.md",
        "--readme-path",
        str(readme),
    )
    assert result.returncode == 0, result.stderr


def test_cli_fails_with_message_when_missing(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(_readme_with([]), encoding="utf-8")
    result = _run_cli(
        "--check-adr-readme-parity",
        "docs/adr/0099-test.md",
        "--readme-path",
        str(readme),
    )
    assert result.returncode == 1
    assert "0099-test.md has no row" in result.stderr
    # The error must point the author at the canonical row format and
    # explain the cascade rationale — losing either is a docs regression.
    assert "| [NNNN](./NNNN-slug.md) |" in result.stderr
    assert "issue #803" in result.stderr


# ---- Real-repo smoke ------------------------------------------------------


def test_repo_adr_dir_parity_today() -> None:
    """Sentinel: every ADR file on disk has a matching README row right
    now. This is the same invariant the CI gate enforces; we duplicate
    it here so a parity drift fails this faster, isolated test before
    failing the slower governance suite.
    """
    adr_dir = REPO_ROOT / "docs" / "adr"
    readme = (adr_dir / "README.md").read_text(encoding="utf-8")
    on_disk = [str(p) for p in sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))]
    missing = adr_readme_parity_violations(on_disk, readme)
    assert missing == [], (
        "ADR ↔ README parity drift on main:\n  - "
        + "\n  - ".join(missing)
    )


# ---- argparse mutex sanity ------------------------------------------------


def test_cli_mutex_with_other_governance_modes(tmp_path: Path) -> None:
    """``--check-adr-readme-parity`` must live in the same mutually
    exclusive group as the other governance commands. Combining two
    modes should fail argparse, not silently run one. This pins the
    group placement so a future refactor cannot accidentally move it
    to a separate group (which would let the hook + CI gate diverge
    on which mode "wins").
    """
    result = _run_cli(
        "--check-adr-readme-parity",
        "docs/adr/0099-x.md",
        "--next-adr-number",
    )
    assert result.returncode != 0
    assert "not allowed with" in result.stderr or "argument" in result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
