"""Regression tests for ADR 0044 §case selection criteria #3 — doc_coverage
prioritization in the case proposer (issue #846).

Three layers:

1. Pure helper ``_select_uncovered_docs``: ordering invariants, fallback when
   the uncovered pool is smaller than ``n_seed_docs``, edge cases.
2. Pure helper ``_read_real_config_covered_doc_ids``: missing file is empty
   set (fresh-clone behavior), malformed YAML raises, multi-case + multi-doc
   union semantics.
3. Integration through ``propose_cases_from_files``: when ``real_config_path``
   is set and ``prioritize_uncovered=True``, uncovered docs are seeded first;
   when either knob is off, the PR2 byte-equal contract is preserved.
"""
from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from eval.case_proposer import (
    CSV_COLUMN_AGENCY,
    CSV_COLUMN_FILE_FORMAT,
    CSV_COLUMN_FILE_NAME,
    CSV_COLUMN_NOTICE_ID,
    CSV_COLUMN_PROJECT,
    CSV_COLUMN_TEXT,
    CaseProposerInputError,
    REQUIRED_CSV_COLUMNS,
    _read_real_config_covered_doc_ids,
    _select_uncovered_docs,
    propose_cases_from_files,
)
from rag_core import INDEX_SCHEMA_VERSION


NOW_FIXED = "2026-05-15T08:00:00Z"


def _make_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(REQUIRED_CSV_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _make_index(path: Path, doc_ids: list[str]) -> None:
    payload = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "build": {"documents": [{"doc_id": d} for d in doc_ids]},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _sample_row(
    notice_id: str = "K2026-001",
    agency: str = "A기관",
    project: str = "사업A",
) -> dict[str, str]:
    return {
        CSV_COLUMN_NOTICE_ID: notice_id,
        CSV_COLUMN_PROJECT: project,
        CSV_COLUMN_AGENCY: agency,
        CSV_COLUMN_FILE_FORMAT: "pdf",
        CSV_COLUMN_FILE_NAME: f"{notice_id}.pdf",
        CSV_COLUMN_TEXT: "본문 텍스트",
    }


def _rows(doc_ids: list[str]) -> list[dict[str, Any]]:
    return [{"doc_id": d} for d in doc_ids]


class TestSelectUncoveredDocs(unittest.TestCase):
    def test_uncovered_come_first_then_covered_fill_tail(self) -> None:
        rows = _rows(["d1", "d2", "d3", "d4"])
        out = _select_uncovered_docs(rows, {"d1", "d3"}, 4)
        self.assertEqual([r["doc_id"] for r in out], ["d2", "d4", "d1", "d3"])

    def test_preserves_within_group_original_order(self) -> None:
        rows = _rows(["d1", "d2", "d3", "d4", "d5"])
        out = _select_uncovered_docs(rows, {"d2", "d4"}, 5)
        self.assertEqual(
            [r["doc_id"] for r in out],
            ["d1", "d3", "d5", "d2", "d4"],
        )

    def test_n_seed_docs_caps_output(self) -> None:
        rows = _rows(["d1", "d2", "d3"])
        out = _select_uncovered_docs(rows, set(), 2)
        self.assertEqual([r["doc_id"] for r in out], ["d1", "d2"])

    def test_zero_and_negative_n_return_empty(self) -> None:
        rows = _rows(["d1"])
        self.assertEqual(_select_uncovered_docs(rows, set(), 0), [])
        self.assertEqual(_select_uncovered_docs(rows, set(), -1), [])

    def test_uncovered_pool_smaller_than_n_falls_back_to_covered(self) -> None:
        """A small uncovered pool must not starve the proposer — the tail
        is filled with covered rows so n_seed_docs is honored when possible."""
        rows = _rows(["d1", "d2", "d3"])
        out = _select_uncovered_docs(rows, {"d2", "d3"}, 3)
        self.assertEqual([r["doc_id"] for r in out], ["d1", "d2", "d3"])

    def test_all_covered_returns_covered_in_original_order(self) -> None:
        rows = _rows(["d1", "d2"])
        out = _select_uncovered_docs(rows, {"d1", "d2"}, 2)
        self.assertEqual([r["doc_id"] for r in out], ["d1", "d2"])

    def test_empty_rows_returns_empty(self) -> None:
        self.assertEqual(_select_uncovered_docs([], set(), 5), [])


class TestReadRealConfigCoveredDocIds(unittest.TestCase):
    def test_missing_file_returns_empty_set(self) -> None:
        """ADR 0005: real_config.local.yaml is gitignored. A fresh clone
        has no file — treat as empty coverage, not an error."""
        with TemporaryDirectory() as td:
            self.assertEqual(
                _read_real_config_covered_doc_ids(Path(td) / "nope.yaml"),
                set(),
            )

    def test_empty_cases_list_returns_empty_set(self) -> None:
        with TemporaryDirectory() as td:
            p = Path(td) / "rc.yaml"
            p.write_text("cases: []\n", encoding="utf-8")
            self.assertEqual(_read_real_config_covered_doc_ids(p), set())

    def test_no_cases_key_returns_empty_set(self) -> None:
        with TemporaryDirectory() as td:
            p = Path(td) / "rc.yaml"
            p.write_text("mode: rag\n", encoding="utf-8")
            self.assertEqual(_read_real_config_covered_doc_ids(p), set())

    def test_collects_doc_ids_across_multiple_cases(self) -> None:
        with TemporaryDirectory() as td:
            p = Path(td) / "rc.yaml"
            p.write_text(
                "cases:\n"
                "  - id: c1\n    expected_doc_ids: [doc-1, doc-2]\n"
                "  - id: c2\n    expected_doc_ids: [doc-3]\n"
                "  - id: c3\n    expected_doc_ids: []\n"
                "  - id: c4\n",
                encoding="utf-8",
            )
            self.assertEqual(
                _read_real_config_covered_doc_ids(p),
                {"doc-1", "doc-2", "doc-3"},
            )

    def test_strips_whitespace_and_skips_blank_ids(self) -> None:
        with TemporaryDirectory() as td:
            p = Path(td) / "rc.yaml"
            p.write_text(
                "cases:\n"
                "  - id: c1\n    expected_doc_ids: ['  doc-1  ', '', '  ']\n",
                encoding="utf-8",
            )
            self.assertEqual(
                _read_real_config_covered_doc_ids(p),
                {"doc-1"},
            )

    def test_top_level_list_raises(self) -> None:
        """A malformed top-level (list instead of mapping) must raise so the
        proposer never silently widens coverage to docs that ARE covered."""
        with TemporaryDirectory() as td:
            p = Path(td) / "rc.yaml"
            p.write_text("[]\n", encoding="utf-8")
            with self.assertRaises(CaseProposerInputError):
                _read_real_config_covered_doc_ids(p)


class TestProposeCasesFromFilesDocCoverage(unittest.TestCase):
    """Integration tests: real_config_path + prioritize_uncovered combo
    drives propose_cases_from_files selection in line with ADR 0044."""

    def _build_corpus(
        self, td: Path, doc_ids: list[str]
    ) -> tuple[Path, Path]:
        csv_path = td / "data_list.csv"
        index_dir = td / "index"
        index_dir.mkdir()
        _make_csv(
            csv_path,
            [_sample_row(d, f"기관{i}", f"사업{i}") for i, d in enumerate(doc_ids)],
        )
        _make_index(index_dir / "index.json", doc_ids)
        return csv_path, index_dir

    def test_uncovered_docs_seeded_first_when_real_config_given(self) -> None:
        with TemporaryDirectory() as td:
            td_path = Path(td)
            csv_path, index_dir = self._build_corpus(
                td_path, ["K2026-001", "K2026-002", "K2026-003"]
            )
            real_config = td_path / "real_config.local.yaml"
            real_config.write_text(
                "cases:\n"
                "  - id: existing\n    expected_doc_ids: [K2026-001]\n",
                encoding="utf-8",
            )

            cases = propose_cases_from_files(
                metadata_csv=csv_path,
                index_dir=index_dir,
                n_seed_docs=2,
                backend="stub",
                now_iso=NOW_FIXED,
                real_config_path=real_config,
            )
            # n_seed_docs=2 × 2 templates per doc = 4 cases.
            self.assertEqual(len(cases), 4)
            seed_doc_ids = sorted({c["proposer_meta"]["seed_doc_id"] for c in cases})
            self.assertEqual(seed_doc_ids, ["K2026-002", "K2026-003"])
            self.assertNotIn(
                "K2026-001",
                seed_doc_ids,
                "Covered doc must not be seeded ahead of uncovered ones",
            )

    def test_no_real_config_preserves_pr2_default_ordering(self) -> None:
        """Backward-compat: when real_config_path is None, selection is
        the same first-N-by-CSV-order behavior PR2 ships."""
        with TemporaryDirectory() as td:
            td_path = Path(td)
            csv_path, index_dir = self._build_corpus(
                td_path, ["K2026-001", "K2026-002", "K2026-003"]
            )
            cases = propose_cases_from_files(
                metadata_csv=csv_path,
                index_dir=index_dir,
                n_seed_docs=2,
                backend="stub",
                now_iso=NOW_FIXED,
            )
            seed_doc_ids = sorted({c["proposer_meta"]["seed_doc_id"] for c in cases})
            self.assertEqual(seed_doc_ids, ["K2026-001", "K2026-002"])

    def test_no_prioritize_uncovered_falls_back_to_default(self) -> None:
        """Even when real_config_path is set, prioritize_uncovered=False
        falls back to first-N CSV order — escape hatch for byte-equal
        reproductions of the PR2-era proposer."""
        with TemporaryDirectory() as td:
            td_path = Path(td)
            csv_path, index_dir = self._build_corpus(
                td_path, ["K2026-001", "K2026-002", "K2026-003"]
            )
            real_config = td_path / "real_config.local.yaml"
            real_config.write_text(
                "cases:\n"
                "  - id: existing\n    expected_doc_ids: [K2026-001]\n",
                encoding="utf-8",
            )

            cases = propose_cases_from_files(
                metadata_csv=csv_path,
                index_dir=index_dir,
                n_seed_docs=2,
                backend="stub",
                now_iso=NOW_FIXED,
                real_config_path=real_config,
                prioritize_uncovered=False,
            )
            seed_doc_ids = sorted({c["proposer_meta"]["seed_doc_id"] for c in cases})
            self.assertEqual(seed_doc_ids, ["K2026-001", "K2026-002"])

    def test_missing_real_config_does_not_raise(self) -> None:
        """Fresh-clone behavior: real_config_path points at a path that
        doesn't exist yet → empty coverage → all docs uncovered → same as
        default ordering. The proposer must NOT raise on a missing local
        config (it's gitignored under ADR 0005)."""
        with TemporaryDirectory() as td:
            td_path = Path(td)
            csv_path, index_dir = self._build_corpus(
                td_path, ["K2026-001", "K2026-002"]
            )
            cases = propose_cases_from_files(
                metadata_csv=csv_path,
                index_dir=index_dir,
                n_seed_docs=2,
                backend="stub",
                now_iso=NOW_FIXED,
                real_config_path=td_path / "does-not-exist.yaml",
            )
            self.assertEqual(len(cases), 4)

    def test_deterministic_across_runs_with_real_config(self) -> None:
        """Byte-equal contract preserved under coverage-aware mode."""
        with TemporaryDirectory() as td:
            td_path = Path(td)
            csv_path, index_dir = self._build_corpus(
                td_path, ["K2026-001", "K2026-002", "K2026-003"]
            )
            real_config = td_path / "real_config.local.yaml"
            real_config.write_text(
                "cases:\n"
                "  - id: existing\n    expected_doc_ids: [K2026-001]\n",
                encoding="utf-8",
            )

            kwargs = dict(
                metadata_csv=csv_path,
                index_dir=index_dir,
                n_seed_docs=3,
                backend="stub",
                now_iso=NOW_FIXED,
                real_config_path=real_config,
            )
            cases1 = propose_cases_from_files(**kwargs)
            cases2 = propose_cases_from_files(**kwargs)
            self.assertEqual(cases1, cases2)


if __name__ == "__main__":
    unittest.main()
