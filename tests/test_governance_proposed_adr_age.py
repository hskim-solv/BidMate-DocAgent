"""Regression tests for the proposed-ADR lifecycle SLA collector (ADR 0047).

ADR 0047 declared a 30-day proposed-status SLA but explicitly deferred the
measurement collector. `proposed_adr_age()` implements that follow-up. These
tests pin the status parsing, grandfather cutoff, and SLA arithmetic with an
injected date resolver so they run without a git repo.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from scripts._governance import (
    ADR_SLA_GRANDFATHER_DATE,
    THRESHOLDS,
    _cmd_proposed_adr_age,
    adr_has_resolution_section,
    parse_adr_status,
    proposed_adr_age,
)


def _adr(dir_: Path, name: str, status: str, *, resolution: bool = False) -> None:
    body = f"# {name}\n\n- **Status**: {status}\n\n## Context\nstub\n"
    if resolution:
        # ADR 0047 decision #2 in-place resolution: a `## Resolution` H2 append
        # while Status legitimately stays as-is.
        body += "\n## Resolution\n\nResolved in place per ADR 0047 decision #2.\n"
    (dir_ / name).write_text(body, encoding="utf-8")


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


def test_parse_status_table_metablock_form(tmp_path: Path) -> None:
    # ADR 0052 shape: 2-column metablock table, value in the next cell with
    # no colon. The pre-#1151 colon-only regex returned None here (fail-open).
    (tmp_path / "0052-t.md").write_text(
        "# 0052: x\n\n"
        "| Field       | Value                                    |\n"
        "|-------------|------------------------------------------|\n"
        "| **Status**  | Proposed                                 |\n"
        "| **Date**    | 2026-05-17                               |\n",
        encoding="utf-8",
    )
    assert parse_adr_status(tmp_path / "0052-t.md") == "proposed"


def test_parse_status_table_form_with_annotation(tmp_path: Path) -> None:
    # ADR 0044 shape: table value carries a trailing annotation; not proposed.
    (tmp_path / "0044-t.md").write_text(
        "# 0044: x\n\n"
        "| Field       | Value                              |\n"
        "|-------------|------------------------------------|\n"
        "| **Status**  | Accepted (Superseded by ADR 0052)  |\n",
        encoding="utf-8",
    )
    assert parse_adr_status(tmp_path / "0044-t.md") == "accepted (superseded by adr 0052)"


# ---- adr_has_resolution_section (ADR 0047 in-place marker) ----------------


def test_resolution_section_detected(tmp_path: Path) -> None:
    _adr(tmp_path, "0050-x.md", "proposed", resolution=True)
    assert adr_has_resolution_section(tmp_path / "0050-x.md") is True


def test_resolution_section_absent(tmp_path: Path) -> None:
    _adr(tmp_path, "0050-x.md", "proposed")  # only `## Context`, no Resolution
    assert adr_has_resolution_section(tmp_path / "0050-x.md") is False


def test_resolution_section_h3_not_detected(tmp_path: Path) -> None:
    # H3 is not the sanctioned marker — exact `## Resolution` H2 only.
    (tmp_path / "0050-x.md").write_text(
        "# t\n\n- **Status**: proposed\n\n### Resolution\n\nnot an H2\n",
        encoding="utf-8",
    )
    assert adr_has_resolution_section(tmp_path / "0050-x.md") is False


def test_resolution_section_inline_suffix_not_detected(tmp_path: Path) -> None:
    # `## Resolution notes` is a different heading; the detector is anchored.
    (tmp_path / "0050-x.md").write_text(
        "# t\n\n- **Status**: proposed\n\n## Resolution notes\n\ntext\n",
        encoding="utf-8",
    )
    assert adr_has_resolution_section(tmp_path / "0050-x.md") is False


def test_resolution_section_missing_file_returns_false(tmp_path: Path) -> None:
    assert adr_has_resolution_section(tmp_path / "nope.md") is False


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


def test_table_form_proposed_included_in_collector(tmp_path: Path) -> None:
    # Regression for #1151: a table-form proposed ADR must reach the collector
    # (and be SLA-flaggable), not be silently exempted.
    (tmp_path / "0052-t.md").write_text(
        "# 0052: x\n\n| Field | Value |\n|---|---|\n| **Status** | Proposed |\n",
        encoding="utf-8",
    )
    recs = proposed_adr_age(
        tmp_path,
        date_resolver=lambda p: date(2026, 5, 16),  # after grandfather
        now=date(2026, 6, 25),  # 40 days > 30
    )
    assert [r.number for r in recs] == [52]
    assert recs[0].over_sla is True


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


def test_future_dated_commit_clamps_to_zero(tmp_path: Path) -> None:
    # KST/+09:00 author date can resolve a calendar day ahead of the runner's
    # UTC `now`; age must floor at 0 (not -1) and never flag over_sla.
    _adr(tmp_path, "0011-x.md", "proposed")
    recs = proposed_adr_age(
        tmp_path,
        date_resolver=lambda p: date(2026, 5, 22),  # one day ahead of `now`
        now=date(2026, 5, 21),
    )
    assert recs[0].age_days == 0
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


# ---- proposed_adr_age: ## Resolution in-place resolution (#1178) ----------
# ADR 0047 decision #2 sanctions a `## Resolution` append as a resolution even
# when Status stays `proposed`. The collector must stop flagging such an ADR
# OVER_SLA and surface `resolved_in_place` instead.


def test_resolution_append_suppresses_over_sla(tmp_path: Path) -> None:
    # The before/after pair: an otherwise-OVER_SLA ADR (40d > 30d, post-
    # grandfather) flips to resolved_in_place once `## Resolution` is appended.
    _adr(tmp_path, "0050-x.md", "proposed", resolution=True)
    recs = proposed_adr_age(
        tmp_path,
        date_resolver=lambda p: date(2026, 5, 16),  # after grandfather
        now=date(2026, 6, 25),  # 40 days > 30
    )
    assert recs[0].age_days == 40
    assert recs[0].grandfathered is False
    assert recs[0].resolved_in_place is True
    assert recs[0].over_sla is False
    assert recs[0].status == "proposed"  # Status legitimately unchanged


def test_no_resolution_still_over_sla(tmp_path: Path) -> None:
    # Control for the pair above: identical dates, no `## Resolution` → still
    # OVER_SLA, resolved_in_place False.
    _adr(tmp_path, "0050-x.md", "proposed")
    recs = proposed_adr_age(
        tmp_path,
        date_resolver=lambda p: date(2026, 5, 16),
        now=date(2026, 6, 25),
    )
    assert recs[0].over_sla is True
    assert recs[0].resolved_in_place is False


def test_resolution_independent_of_grandfather(tmp_path: Path) -> None:
    # A grandfathered ADR with a `## Resolution` is marked resolved_in_place;
    # over_sla stays False either way (grandfather already exempts it).
    _adr(tmp_path, "0011-old.md", "proposed", resolution=True)
    recs = proposed_adr_age(
        tmp_path,
        date_resolver=lambda p: date(2026, 5, 1),  # before grandfather
        now=date(2026, 7, 1),  # 61 days
    )
    assert recs[0].grandfathered is True
    assert recs[0].resolved_in_place is True
    assert recs[0].over_sla is False


def test_resolution_within_sla_still_marked_resolved(tmp_path: Path) -> None:
    # resolved_in_place reflects file content, not age — a young ADR resolved
    # early is still resolved_in_place (not merely "ok").
    _adr(tmp_path, "0050-x.md", "proposed", resolution=True)
    recs = proposed_adr_age(
        tmp_path,
        date_resolver=lambda p: date(2026, 5, 16),
        now=date(2026, 6, 10),  # 25 days <= 30
    )
    assert recs[0].over_sla is False
    assert recs[0].resolved_in_place is True


def test_resolved_in_place_defaults_false_without_marker(tmp_path: Path) -> None:
    # Every record carries the new field; absent the marker it is False.
    _adr(tmp_path, "0050-x.md", "proposed")
    recs = proposed_adr_age(
        tmp_path, date_resolver=lambda p: date(2026, 5, 16), now=date(2026, 6, 1)
    )
    assert recs[0].resolved_in_place is False


def test_cmd_output_shows_resolved_in_place_flag(tmp_path, capsys) -> None:
    # CLI flag-string mapping: resolved_in_place outranks ok/OVER_SLA in the
    # printed flag column, and the summary notes the resolved count.
    _adr(tmp_path, "0099-x.md", "proposed", resolution=True)
    rc = _cmd_proposed_adr_age(str(tmp_path))
    captured = capsys.readouterr()
    assert rc == 0
    # Data row goes to stdout; the resolved ADR shows the resolved flag.
    assert "\tresolved_in_place\t" in captured.out
    assert "OVER_SLA" not in captured.out
    # Summary (stderr) reports the in-place count.
    assert "resolved in place" in captured.err


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
        # New field is populated for every live record (exercises
        # adr_has_resolution_section against real ADR files).
        assert isinstance(r.resolved_in_place, bool)
        # A resolved-in-place ADR is never simultaneously OVER_SLA.
        assert not (r.resolved_in_place and r.over_sla)


# ---- README ↔ collector parity (anti-fail-open) --------------------------


def test_readme_proposed_rows_all_in_collector() -> None:
    """Every ADR the README main index marks `proposed` must be returned by
    the collector. This is the format-agnostic guard: it fails whenever a live
    ADR uses a Status form `parse_adr_status` cannot read — the table-form
    fail-open (#1151, ADR 0052) was the original instance.

    Forward direction only. The `## Roadmap (proposed, not yet committed)`
    section is excluded: its rows carry a *title* in column 2, not a status,
    so the collector legitimately reports more than the main index. An injected
    date_resolver keeps this a pure status-parity check (no git, no ages).
    """
    readme = Path("docs/adr/README.md").read_text(encoding="utf-8")
    main_index = readme.split("## Roadmap", 1)[0]
    row_re = re.compile(
        r"^\|\s*\[(\d{4})\]\([^)]+\)\s*\|\s*([^|]+?)\s*\|", re.MULTILINE
    )
    readme_proposed = {
        int(num)
        for num, status in row_re.findall(main_index)
        if status.strip().lower().startswith("proposed")
    }
    # Guard against a silently-empty README parse making this vacuously pass.
    assert readme_proposed, "README main index parsed zero proposed rows"

    collector = {
        r.number
        for r in proposed_adr_age("docs/adr", date_resolver=lambda p: date(2026, 1, 1))
    }
    missing = readme_proposed - collector
    assert not missing, (
        "README marks these ADRs proposed but the collector missed them "
        f"(Status-format fail-open): {sorted(missing)}"
    )
