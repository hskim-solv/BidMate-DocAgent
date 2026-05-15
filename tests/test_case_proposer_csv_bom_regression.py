"""Regression test for case_proposer reading UTF-8 BOM-prefixed data_list.csv
(issue #873).

Several Korean spreadsheet tools save CSVs with a leading UTF-8 BOM
(``\\ufeff``). ``ingestion.py`` uses ``encoding="utf-8-sig"`` to strip
it transparently, but ``eval/case_proposer.py::_read_data_list_csv``
historically used plain ``"utf-8"`` and so reported the first header
as ``"\\ufeff공고 번호"`` instead of ``"공고 번호"``. The required-column
check then raised ``CaseProposerInputError("missing required columns:
['공고 번호']")``.

This test pins the fix: writing a BOM-prefixed CSV must round-trip
through ``propose_cases_from_files`` without raising.
"""
from __future__ import annotations

import csv
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from eval.case_proposer import (
    CSV_COLUMN_AGENCY,
    CSV_COLUMN_FILE_FORMAT,
    CSV_COLUMN_FILE_NAME,
    CSV_COLUMN_NOTICE_ID,
    CSV_COLUMN_PROJECT,
    CSV_COLUMN_TEXT,
    REQUIRED_CSV_COLUMNS,
    propose_cases_from_files,
)
from rag_core import INDEX_SCHEMA_VERSION


NOW_FIXED = "2026-05-15T08:00:00Z"


def _make_csv_with_bom(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a CSV that starts with a UTF-8 BOM (``\\xef\\xbb\\xbf``).

    Mirrors what Korean spreadsheet tools (e.g. Excel "Save as CSV
    UTF-8") produce. We write through an in-memory StringIO so the
    csv module's quoting + newline handling is identical to the
    non-BOM path; only the byte-level prefix differs.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(REQUIRED_CSV_COLUMNS))
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    path.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))


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


class TestCaseProposerCsvBomRegression(unittest.TestCase):
    def test_bom_prefixed_csv_round_trips_through_propose(self) -> None:
        with TemporaryDirectory() as td:
            td_path = Path(td)
            csv_path = td_path / "data_list.csv"
            index_dir = td_path / "index"
            index_dir.mkdir()

            _make_csv_with_bom(
                csv_path,
                [_sample_row("K2026-001"), _sample_row("K2026-002", "B기관", "사업B")],
            )
            _make_index(index_dir / "index.json", ["K2026-001", "K2026-002"])

            cases = propose_cases_from_files(
                metadata_csv=csv_path,
                index_dir=index_dir,
                n_seed_docs=2,
                backend="stub",
                now_iso=NOW_FIXED,
            )
            # 2 seed docs × 2 templates per doc (single_doc + abstention).
            self.assertEqual(len(cases), 4)

    def test_bom_byte_is_actually_present_in_fixture(self) -> None:
        """Sanity check on the fixture: without this, a regression in
        ``_make_csv_with_bom`` could silently turn the BOM test into a
        plain-UTF-8 test and the fix below would never be exercised."""
        with TemporaryDirectory() as td:
            csv_path = Path(td) / "data_list.csv"
            _make_csv_with_bom(csv_path, [_sample_row()])
            self.assertEqual(csv_path.read_bytes()[:3], b"\xef\xbb\xbf")


if __name__ == "__main__":
    unittest.main()
