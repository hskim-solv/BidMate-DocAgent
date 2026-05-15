"""Unit tests for eval/table_extraction_metrics.py (issue #790, PR-A3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval import table_extraction_metrics as m  # noqa: E402


def _record(
    doc_id: str,
    table_index: int,
    cells: list[tuple[int, int, str, int, int]] | list[tuple[int, int, str]],
) -> dict[str, Any]:
    norm_cells = []
    for cell in cells:
        if len(cell) == 5:
            r, c, t, rs, cs = cell
        else:
            r, c, t = cell  # type: ignore[misc]
            rs = cs = 1
        norm_cells.append(
            {"row": r, "col": c, "rowspan": rs, "colspan": cs, "text": t}
        )
    return {
        "doc_id": doc_id,
        "source_path": f"/tmp/{doc_id}.hwp",
        "page": None,
        "table_index": table_index,
        "rows": max((r for r, _, *_ in cells), default=-1) + 1,
        "cols": max((c for _, c, *_ in cells), default=-1) + 1,
        "caption": None,
        "table_kind": None,
        "cells": norm_cells,
        "extractor": "test",
        "extracted_at": "2026-05-14T00:00:00+00:00",
        "notes": None,
    }


# --- Levenshtein -----------------------------------------------------


def test_levenshtein_zero_for_equal_strings() -> None:
    assert m.levenshtein("abc", "abc") == 0


def test_levenshtein_substitution_insert_delete() -> None:
    assert m.levenshtein("kitten", "sitting") == 3


def test_levenshtein_empty_strings() -> None:
    assert m.levenshtein("", "abc") == 3
    assert m.levenshtein("abc", "") == 3
    assert m.levenshtein("", "") == 0


def test_levenshtein_swap_arguments_yields_same_distance() -> None:
    assert m.levenshtein("foo", "foobar") == m.levenshtein("foobar", "foo")


# --- similarity ------------------------------------------------------


def test_similarity_exact_after_normalization() -> None:
    # full-width "６０" → "60"; surrounding spaces collapse; casefold.
    assert m.similarity("  ６０ ", "60") == 1.0


def test_similarity_partial() -> None:
    # 'abcd' vs 'abce' → 1 edit / 4 chars = 0.75.
    assert m.similarity("abcd", "abce") == pytest.approx(0.75)


def test_similarity_empty_both_is_one() -> None:
    assert m.similarity("", "") == 1.0
    assert m.similarity(None, None) == 1.0


def test_similarity_disjoint() -> None:
    # 'abc' vs 'xyz' → 3 edits / 3 chars = 0.0.
    assert m.similarity("abc", "xyz") == pytest.approx(0.0)


# --- cell_f1 ----------------------------------------------------------


def test_cell_f1_all_match_at_threshold_0_9() -> None:
    g = _record("doc1", 0, [(0, 0, "항목"), (0, 1, "배점")])
    e = _record("doc1", 0, [(0, 0, "항목"), (0, 1, "배점")])
    result = m.cell_f1(g, e)
    assert result["tp"] == 2
    assert result["fp"] == 0
    assert result["fn"] == 0
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["f1"] == 1.0


def test_cell_f1_text_below_threshold_counts_as_fp_fn() -> None:
    # 'kitten' vs 'sitting' similarity ≈ 1 - 3/7 ≈ 0.571 < 0.9
    g = _record("doc1", 0, [(0, 0, "kitten")])
    e = _record("doc1", 0, [(0, 0, "sitting")])
    result = m.cell_f1(g, e)
    assert result["tp"] == 0
    assert result["fp"] == 1
    assert result["fn"] == 1


def test_cell_f1_extra_extracted_cell_is_fp_only() -> None:
    g = _record("doc1", 0, [(0, 0, "a")])
    e = _record("doc1", 0, [(0, 0, "a"), (0, 1, "extra")])
    result = m.cell_f1(g, e)
    assert result["tp"] == 1
    assert result["fp"] == 1
    assert result["fn"] == 0


def test_cell_f1_missing_extracted_cell_is_fn_only() -> None:
    g = _record("doc1", 0, [(0, 0, "a"), (0, 1, "b")])
    e = _record("doc1", 0, [(0, 0, "a")])
    result = m.cell_f1(g, e)
    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["fn"] == 1


def test_cell_f1_custom_threshold_lowers_bar() -> None:
    g = _record("doc1", 0, [(0, 0, "kitten")])
    e = _record("doc1", 0, [(0, 0, "sitting")])  # similarity ≈ 0.571
    result = m.cell_f1(g, e, similarity_threshold=0.5)
    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["fn"] == 0


# --- merge_cell_preservation ----------------------------------------


def test_merge_preservation_no_merged_cells_in_golden_returns_one() -> None:
    g = _record("doc1", 0, [(0, 0, "a", 1, 1)])
    e = _record("doc1", 0, [(0, 0, "a", 1, 1)])
    result = m.merge_cell_preservation(g, e)
    assert result["golden_merge_count"] == 0
    assert result["rate"] == 1.0


def test_merge_preservation_exact_span_match() -> None:
    # Two merged cells in golden; extractor reproduces both with matching dims.
    g = _record("doc1", 0, [(0, 0, "a", 2, 1), (0, 1, "b", 1, 2)])
    e = _record("doc1", 0, [(0, 0, "a", 2, 1), (0, 1, "b", 1, 2)])
    result = m.merge_cell_preservation(g, e)
    assert result["golden_merge_count"] == 2
    assert result["preserved"] == 2
    assert result["rate"] == 1.0


def test_merge_preservation_partial_dim_mismatch() -> None:
    # Golden has rowspan=2; extractor emits rowspan=1 (lost the merge).
    g = _record("doc1", 0, [(0, 0, "a", 2, 1)])
    e = _record("doc1", 0, [(0, 0, "a", 1, 1)])
    result = m.merge_cell_preservation(g, e)
    assert result["golden_merge_count"] == 1
    assert result["preserved"] == 0
    assert result["rate"] == 0.0


def test_merge_preservation_missing_extracted_cell() -> None:
    g = _record("doc1", 0, [(0, 0, "a", 2, 2)])
    e = _record("doc1", 0, [])
    result = m.merge_cell_preservation(g, e)
    assert result["preserved"] == 0
    assert result["rate"] == 0.0


# --- table_level_metrics --------------------------------------------


def test_table_level_metrics_all_match() -> None:
    g = [_record("d", 0, []), _record("d", 1, [])]
    e = [_record("d", 0, []), _record("d", 1, [])]
    result = m.table_level_metrics(g, e)
    assert result["tp"] == 2
    assert result["fp"] == 0
    assert result["fn"] == 0
    assert result["f1"] == 1.0


def test_table_level_metrics_missing_and_extra() -> None:
    g = [_record("d", 0, []), _record("d", 1, [])]
    e = [_record("d", 0, []), _record("d", 2, [])]
    result = m.table_level_metrics(g, e)
    assert result["tp"] == 1
    assert result["fp"] == 1
    assert result["fn"] == 1


# --- compute (integration) -------------------------------------------


def test_compute_aggregates_across_pairs() -> None:
    golden = [
        _record("d", 0, [(0, 0, "a"), (0, 1, "b")]),
        _record("d", 1, [(0, 0, "x")]),
    ]
    extracted = [
        _record("d", 0, [(0, 0, "a"), (0, 1, "b")]),
        _record("d", 1, [(0, 0, "y")]),  # mismatch
    ]
    report = m.compute(extracted=extracted, golden=golden)
    cell_micro = report["cell_level_micro"]
    assert cell_micro["tp"] == 2  # 2 from table 0
    assert cell_micro["fp"] == 1  # 1 from table 1 extraction
    assert cell_micro["fn"] == 1  # 1 from table 1 golden
    assert report["table_level"]["tp"] == 2
    assert report["common_table_pair_count"] == 2


def test_compute_returns_one_for_no_merge_cells_overall() -> None:
    golden = [_record("d", 0, [(0, 0, "a")])]
    extracted = [_record("d", 0, [(0, 0, "a")])]
    report = m.compute(extracted=extracted, golden=golden)
    assert report["merge_cell_preservation_micro"]["golden_merge_count"] == 0
    assert report["merge_cell_preservation_micro"]["rate"] == 1.0


# --- CLI -------------------------------------------------------------


def test_cli_writes_summary_and_returns_zero(tmp_path: Path) -> None:
    g_path = tmp_path / "g.jsonl"
    e_path = tmp_path / "e.jsonl"
    out = tmp_path / "metrics.json"
    g_path.write_text(
        json.dumps(_record("d", 0, [(0, 0, "a")])) + "\n", encoding="utf-8"
    )
    e_path.write_text(
        json.dumps(_record("d", 0, [(0, 0, "a")])) + "\n", encoding="utf-8"
    )
    rc = m.main(["--golden", str(g_path), "--extracted", str(e_path), "--out", str(out)])
    assert rc == 0
    assert out.exists()
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["cell_level_micro"]["tp"] == 1


def test_cli_returns_2_when_input_missing(tmp_path: Path) -> None:
    g_path = tmp_path / "missing.jsonl"
    e_path = tmp_path / "exists.jsonl"
    e_path.write_text("", encoding="utf-8")
    rc = m.main(["--golden", str(g_path), "--extracted", str(e_path), "--out", str(tmp_path / "o.json")])
    assert rc == 2
