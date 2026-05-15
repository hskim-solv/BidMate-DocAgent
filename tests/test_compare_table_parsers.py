"""Unit tests for scripts/compare_table_parsers.py (issue #781, PR-A2)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import compare_table_parsers as cmp  # noqa: E402


def _record(
    doc_id: str,
    table_index: int,
    cells: list[tuple[int, int, str]],
    *,
    extractor: str = "pyhwp_native_tables",
) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "source_path": f"/tmp/{doc_id}.hwp",
        "page": None,
        "table_index": table_index,
        "rows": max((r for r, _, _ in cells), default=-1) + 1,
        "cols": max((c for _, c, _ in cells), default=-1) + 1,
        "caption": None,
        "table_kind": None,
        "cells": [
            {"row": r, "col": c, "rowspan": 1, "colspan": 1, "text": t}
            for r, c, t in cells
        ],
        "extractor": extractor,
        "extracted_at": "2026-05-14T00:00:00+00:00",
        "notes": None,
    }


# --- normalize_text ----------------------------------------------------


def test_normalize_text_nfkc_and_whitespace() -> None:
    # full-width "６０" → ascii "60"; surrounding spaces collapse.
    assert cmp._normalize_text("  ６０ ") == "60"


def test_normalize_text_casefold() -> None:
    assert cmp._normalize_text("Mixed") == "mixed"


def test_normalize_text_preserves_punctuation() -> None:
    # FR-007 keeps the hyphen — RFP IDs are meaningful with punctuation.
    assert cmp._normalize_text("FR-007") == "fr-007"


# --- diff_pair ---------------------------------------------------------


def test_diff_pair_exact_match() -> None:
    a = _record("doc1", 0, [(0, 0, "a"), (0, 1, "b")])
    b = _record("doc1", 0, [(0, 0, "A"), (0, 1, "b")])  # casefold matches
    result = cmp.diff_pair(a, b)
    assert result["left_cell_count"] == 2
    assert result["right_cell_count"] == 2
    assert result["common_coord_count"] == 2
    assert result["exact_match_count"] == 2
    assert result["exact_match_rate"] == 1.0
    assert result["only_left_coords_sample"] == []
    assert result["only_right_coords_sample"] == []
    assert result["mismatched_coords_sample"] == []


def test_diff_pair_text_mismatch_recorded() -> None:
    a = _record("doc1", 0, [(0, 0, "a"), (0, 1, "b")])
    b = _record("doc1", 0, [(0, 0, "a"), (0, 1, "different")])
    result = cmp.diff_pair(a, b)
    assert result["common_coord_count"] == 2
    assert result["exact_match_count"] == 1
    assert result["exact_match_rate"] == 0.5
    assert result["mismatched_coords_sample"] == [[0, 1]]


def test_diff_pair_only_left_and_only_right_coords() -> None:
    a = _record("doc1", 0, [(0, 0, "a"), (1, 0, "left-only")])
    b = _record("doc1", 0, [(0, 0, "a"), (0, 1, "right-only")])
    result = cmp.diff_pair(a, b)
    assert result["left_cell_count"] == 2
    assert result["right_cell_count"] == 2
    assert result["cell_count_delta"] == 0
    assert result["common_coord_count"] == 1
    assert result["exact_match_count"] == 1
    assert result["only_left_coords_sample"] == [[1, 0]]
    assert result["only_right_coords_sample"] == [[0, 1]]


def test_diff_pair_empty_both_sides_handles_zero_division() -> None:
    a = _record("doc1", 0, [])
    b = _record("doc1", 0, [])
    result = cmp.diff_pair(a, b)
    assert result["common_coord_count"] == 0
    assert result["exact_match_rate"] == 0.0


# --- compare (top-level) ----------------------------------------------


def test_compare_micro_average_match_rate() -> None:
    left = [
        _record("doc1", 0, [(0, 0, "a"), (0, 1, "b")]),
        _record("doc1", 1, [(0, 0, "x")]),
    ]
    right = [
        _record("doc1", 0, [(0, 0, "a"), (0, 1, "b")]),
        _record("doc1", 1, [(0, 0, "different")]),
    ]
    report = cmp.compare(left, right)
    summary = report["summary"]
    assert summary["left_table_count"] == 2
    assert summary["right_table_count"] == 2
    assert summary["common_table_count"] == 2
    # 3 common coords (2 match in table 0 + 0 match in table 1) / 3 coords
    assert summary["aggregate_common_coord_count"] == 3
    assert summary["aggregate_exact_match_count"] == 2
    assert summary["aggregate_exact_match_rate"] == round(2 / 3, 4)


def test_compare_lists_tables_missing_on_each_side() -> None:
    left = [_record("doc1", 0, [(0, 0, "a")]), _record("doc1", 1, [(0, 0, "b")])]
    right = [_record("doc1", 0, [(0, 0, "a")]), _record("doc1", 2, [(0, 0, "c")])]
    report = cmp.compare(left, right)
    summary = report["summary"]
    assert summary["only_left_table_count"] == 1
    assert summary["only_right_table_count"] == 1
    assert ["doc1", 1] in summary["only_left_keys_sample"]
    assert ["doc1", 2] in summary["only_right_keys_sample"]


def test_compare_per_doc_table_counts() -> None:
    left = [
        _record("docA", 0, [(0, 0, "x")]),
        _record("docA", 1, [(0, 0, "y")]),
        _record("docB", 0, [(0, 0, "z")]),
    ]
    right = [
        _record("docA", 0, [(0, 0, "x")]),
        _record("docB", 0, [(0, 0, "z")]),
        _record("docB", 1, [(0, 0, "w")]),
    ]
    report = cmp.compare(left, right)
    per_doc = report["summary"]["per_doc_table_counts"]
    assert per_doc["docA"] == {"left": 2, "right": 1}
    assert per_doc["docB"] == {"left": 1, "right": 2}


# --- I/O -------------------------------------------------------------


def test_load_jsonl_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "in.jsonl"
    path.write_text(
        json.dumps({"doc_id": "a", "table_index": 0, "cells": []}) + "\n\n"
        + json.dumps({"doc_id": "b", "table_index": 0, "cells": []}) + "\n",
        encoding="utf-8",
    )
    records = cmp.load_jsonl(path)
    assert len(records) == 2
    assert records[0]["doc_id"] == "a"


def test_cli_writes_summary_and_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    left_path = tmp_path / "left.jsonl"
    right_path = tmp_path / "right.jsonl"
    out_path = tmp_path / "cmp.json"

    rec_left = _record("doc1", 0, [(0, 0, "match"), (0, 1, "left")])
    rec_right = _record("doc1", 0, [(0, 0, "match"), (0, 1, "right")])
    left_path.write_text(json.dumps(rec_left) + "\n", encoding="utf-8")
    right_path.write_text(json.dumps(rec_right) + "\n", encoding="utf-8")

    rc = cmp.main([
        "--left", str(left_path),
        "--right", str(right_path),
        "--out", str(out_path),
    ])
    assert rc == 0
    assert out_path.exists()
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["summary"]["common_table_count"] == 1
    assert report["summary"]["aggregate_common_coord_count"] == 2
    assert report["summary"]["aggregate_exact_match_count"] == 1


def test_cli_returns_2_when_input_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    left = tmp_path / "missing_left.jsonl"
    right = tmp_path / "missing_right.jsonl"
    right.write_text("", encoding="utf-8")
    rc = cmp.main(["--left", str(left), "--right", str(right), "--out", str(tmp_path / "o.json")])
    assert rc == 2
    captured = capsys.readouterr()
    assert "--left does not exist" in captured.err
