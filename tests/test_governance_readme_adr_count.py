"""Regression tests for top-level README ADR-count parity (issue #1156).

``README.md`` states the ADR count in two human-facing spots — the prose
headline ("… 59개 설계 결정 (ADR).") and the 주요 링크 table row
("| ADR 인덱스 (59개 결정) | … |"). Both were hand-edited and re-staled every
time an ADR landed in a concurrent worktree; #1059 corrected the number but
not the mechanism, so it was off-by-one the moment it merged.

The count's source of truth is the number of ``NNNN-slug.md`` ADR *files*
(``existing_adr_numbers()``), NOT the ``docs/adr/README.md`` index — whose
reopen-condition tables re-list ADRs and so over-count. ``rewrite_readme_adr_count``
regenerates both spots (called by ``scripts/update_readme_metrics.py``);
``readme_adr_count_violations`` is the read-only gate so drift cannot merge
silently. These tests pin both helpers + a real-repo sentinel.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts._governance import (
    existing_adr_numbers,
    readme_adr_count_violations,
    rewrite_readme_adr_count,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---- helpers --------------------------------------------------------------


def _readme_with(count: int) -> str:
    """Minimal README fragment carrying both canonical ADR-count spots."""
    return (
        f"> 분리 평가 ([ADR 0005](docs/adr/0005-x.md)), {count}개 설계 결정 (ADR).\n\n"
        "## 주요 링크\n\n"
        "| 목적 | 링크 |\n|---|---|\n"
        f"| ADR 인덱스 ({count}개 결정) | [`docs/adr/README.md`](docs/adr/README.md) |\n"
    )


# ---- rewrite_readme_adr_count --------------------------------------------


def test_rewrite_sets_both_spots() -> None:
    out = rewrite_readme_adr_count(_readme_with(59), 65)
    assert "65개 설계 결정 (ADR)." in out
    assert "ADR 인덱스 (65개 결정)" in out
    assert "59" not in out


def test_rewrite_is_idempotent() -> None:
    fixed = _readme_with(65)
    assert rewrite_readme_adr_count(fixed, 65) == fixed


def test_rewrite_preserves_surrounding_text() -> None:
    src = _readme_with(59)
    out = rewrite_readme_adr_count(src, 65)
    # Only the digit runs change (59 and 65 are both 2-digit → equal length).
    assert len(out) == len(src)
    assert "분리 평가 ([ADR 0005](docs/adr/0005-x.md))" in out
    assert "[`docs/adr/README.md`](docs/adr/README.md)" in out


def test_rewrite_handles_multi_digit_growth() -> None:
    # 9 -> 123: replacement must be digit-length agnostic.
    out = rewrite_readme_adr_count(_readme_with(9), 123)
    assert "123개 설계 결정 (ADR)." in out
    assert "ADR 인덱스 (123개 결정)" in out


# ---- readme_adr_count_violations -----------------------------------------


def test_violations_empty_when_matching() -> None:
    assert readme_adr_count_violations(_readme_with(65), 65) == []


def test_violations_flag_both_stale_spots() -> None:
    out = readme_adr_count_violations(_readme_with(59), 65)
    assert len(out) == 2
    assert any("prose headline" in v for v in out)
    assert any("주요 링크 table" in v for v in out)
    assert all("states 59 ADRs" in v and "actual is 65" in v for v in out)


def test_violations_absence_is_not_a_violation() -> None:
    # Dropping the count entirely (the "bare pointer" option) is an
    # intentional act, not drift — so absence must not flag.
    assert readme_adr_count_violations("no ADR count anywhere here", 65) == []


def test_violations_flag_only_the_stale_spot() -> None:
    # Prose correct, table stale → exactly one violation, naming the table.
    mixed = "65개 설계 결정 (ADR).\n| ADR 인덱스 (59개 결정) | x |\n"
    out = readme_adr_count_violations(mixed, 65)
    assert len(out) == 1
    assert "주요 링크 table" in out[0]


# ---- real-repo sentinel ---------------------------------------------------


def test_repo_readme_adr_count_today() -> None:
    """Sentinel: the live README ADR count equals the ADR file count right
    now. This is the always-on gate — when an ADR lands in a concurrent
    worktree and the README is not regenerated, this fails fast (CI red) so
    the drift cannot merge silently. Regenerate with
    ``python scripts/update_readme_metrics.py``.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    expected = len(existing_adr_numbers(REPO_ROOT / "docs" / "adr"))
    violations = readme_adr_count_violations(readme, expected)
    assert violations == [], (
        "README ADR-count drift on main:\n  - " + "\n  - ".join(violations)
    )


def test_repo_readme_still_states_a_count() -> None:
    """Guard against silent deletion: the live README must carry both
    canonical ADR-count spots. If a future change intentionally drops the
    count (switching to a bare ``docs/adr/README.md`` pointer), update this
    test deliberately — otherwise a vacuous-pass sentinel would hide the
    removal and re-open the drift hole from the other side.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "개 설계 결정" in readme
    assert "ADR 인덱스 (" in readme


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
