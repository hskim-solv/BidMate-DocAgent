"""Regression tests for the proposed-ADR lifecycle SLA collector (ADR 0047).

ADR 0047 declared a 30-day proposed-status SLA but explicitly deferred the
measurement collector. `proposed_adr_age()` implements that follow-up. These
tests pin the status parsing, grandfather cutoff, and SLA arithmetic with an
injected date resolver so they run without a git repo.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts._governance import (
    ADR_SLA_GRANDFATHER_DATE,
    THRESHOLDS,
    parse_adr_status,
    proposed_adr_age,
)


def _adr(dir_: Path, name: str, status: str) -> None:
    (dir_ / name).write_text(
        f"# {name}\n\n- **Status**: {status}\n\n## Context\nstub\n",
        encoding="utf-8",
    )


# ---- parse_adr_status ----------------------------------------------------


def test_parse_status_bold_format(tmp_path: Path) -> None:
    _adr(tmp_path, "0001-a.md", "proposed")
    assert parse_adr_status(tmp_path / "0001-a.md") == "proposed"


def test_parse_status_plain_mixed_case(tmp_path: Path) -> None:
    (tmp_path / "0002-b.md").write_text(
        "# t\n\n- Status: Proposed\n", encoding="utf-8"
    )
    assert parse_adr_status(tmp_path / "0002-b.md") == "proposed"


def test_parse_status_missing_file_returns_none(tmp_path: Path) -> None:
    assert parse_adr_status(tmp_path / "nope.md") is None


def test_parse_status_no_status_line_returns_none(tmp_path: Path) -> None:
    (tmp_path / "0003-c.md").write_text("# t\n\nno meta here\n", encoding="utf-8")
    assert parse_adr_status(tmp_path / "0003-c.md") is None


# ---- proposed_adr_age: status filtering ----------------------------------


def test_only_proposed_status_returned(tmp_path: Path) -> None:
    _adr(tmp_path, "0001-a.md", "proposed")
    _adr(tmp_path, "0002-b.md", "accepted")
    _adr(tmp_path, "0003-c.md", "superseded by 0009")
    _adr(tmp_path, "0004-d.md", "deprecated")
    recs = proposed_adr_age(
        tmp_path,
        date_resolver=lambda p: date(2026, 6, 1),
        now=date(2026, 6, 2),
    )
    assert [r.number for r in recs] == [1]


def test_non_adr_files_ignored(tmp_path: Path) -> None:
    _adr(tmp_path, "0001-a.md", "proposed")
    (tmp_path / "README.md").write_text("- **Status**: proposed\n", encoding="utf-8")
    (tmp_path / "_template.md").write_text("- **Status**: proposed\n", encoding="utf-8")
    recs = proposed_adr_age(
        tmp_path, date_resolver=lambda p: date(2026, 6, 1), now=date(2026, 6, 2)
    )
    assert [r.number for r in recs] == [1]


# ---- proposed_adr_age: SLA + grandfather arithmetic ----------------------


def test_over_sla_flagged_when_past_grandfather(tmp_path: Path) -> None:
    _adr(tmp_path, "0050-x.md", "proposed")
    recs = proposed_adr_age(
        tmp_path,
        date_resolver=lambda p: date(2026, 5, 16),  # after grandfather
        now=date(2026, 6, 25),  # 40 days > 30
    )
    assert recs[0].age_days == 40
    assert recs[0].grandfathered is False
    assert recs[0].over_sla is True


def test_within_sla_not_flagged(tmp_path: Path) -> None:
    _adr(tmp_path, "0050-x.md", "proposed")
    recs = proposed_adr_age(
        tmp_path,
        date_resolver=lambda p: date(2026, 5, 16),
        now=date(2026, 6, 10),  # 25 days <= 30
    )
    assert recs[0].age_days == 25
    assert recs[0].over_sla is False


def test_exactly_sla_days_not_over(tmp_path: Path) -> None:
    # Boundary: age == sla is NOT over (strict >).
    _adr(tmp_path, "0050-x.md", "proposed")
    recs = proposed_adr_age(
        tmp_path,
        date_resolver=lambda p: date(2026, 5, 16),
        now=date(2026, 6, 15),  # exactly 30 days
    )
    assert recs[0].age_days == 30
    assert recs[0].over_sla is False


def test_grandfathered_never_flagged(tmp_path: Path) -> None:
    _adr(tmp_path, "0011-old.md", "proposed")
    recs = proposed_adr_age(
        tmp_path,
        date_resolver=lambda p: date(2026, 5, 1),  # before grandfather
        now=date(2026, 7, 1),  # 61 days, but grandfathered
    )
    assert recs[0].grandfathered is True
    assert recs[0].over_sla is False


def test_uncommitted_age_none_not_over(tmp_path: Path) -> None:
    _adr(tmp_path, "0099-new.md", "proposed")
    recs = proposed_adr_age(
        tmp_path, date_resolver=lambda p: None, now=date(2026, 6, 1)
    )
    assert recs[0].age_days is None
    assert recs[0].over_sla is False
    assert recs[0].grandfathered is False


def test_sorted_oldest_first_uncommitted_last(tmp_path: Path) -> None:
    _adr(tmp_path, "0001-a.md", "proposed")  # newer
    _adr(tmp_path, "0002-b.md", "proposed")  # older
    _adr(tmp_path, "0003-c.md", "proposed")  # uncommitted
    dates = {
        "0001-a.md": date(2026, 5, 20),
        "0002-b.md": date(2026, 5, 16),
        "0003-c.md": None,
    }
    recs = proposed_adr_age(
        tmp_path,
        date_resolver=lambda p: dates[Path(p).name],
        now=date(2026, 6, 1),
    )
    assert [r.number for r in recs] == [2, 1, 3]


def test_custom_sla_days_override(tmp_path: Path) -> None:
    _adr(tmp_path, "0050-x.md", "proposed")
    recs = proposed_adr_age(
        tmp_path,
        date_resolver=lambda p: date(2026, 5, 16),
        now=date(2026, 5, 26),  # 10 days
        sla_days=7,
    )
    assert recs[0].over_sla is True


def test_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert proposed_adr_age(tmp_path / "nope") == []


# ---- constants -----------------------------------------------------------


def test_sla_days_threshold_is_30() -> None:
    assert THRESHOLDS["ADR_PROPOSED_SLA_DAYS"] == 30


def test_grandfather_date_is_adr_0047_acceptance() -> None:
    assert ADR_SLA_GRANDFATHER_DATE == date(2026, 5, 15)


# ---- live-repo smoke -----------------------------------------------------


def test_repo_proposed_adr_age_runs() -> None:
    """Sentinel: the collector runs against the live docs/adr without
    crashing and only returns proposed-status records. Robust to repo
    evolution — asserts invariants, not specific ADR numbers/ages (which
    change as ADRs resolve)."""
    recs = proposed_adr_age("docs/adr")
    for r in recs:
        assert r.status.startswith("proposed")
        assert r.number > 0
        assert (r.age_days is None) or (r.age_days >= 0)
