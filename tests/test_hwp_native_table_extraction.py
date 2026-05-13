"""HWP native table extraction regression suite (issue #506, PR-C1).

The native-tables path adds a third ``BIDMATE_HWP_LOADER`` mode on top
of the existing #167 spike:

* unset (default) → ``HwpCsvTextLoader`` (ADR 0001 baseline)
* ``native`` (#167) → ``HwpNativeLoader(with_tables=False)`` — paragraph
  plain text only, no table cell extraction.
* ``native_tables`` (#506) → ``HwpNativeLoader(with_tables=True)`` —
  paragraph text **plus** table cells with row/col/span metadata.

This file locks the following contracts so a future change cannot
silently regress them:

1. **Event-stream parsing.** ``_extract_hwp_native_with_tables`` walks
   the pyhwp xmlmodel ``Section.events()`` cooked stream, collecting
   plain ``Text`` payloads into either the body (no open table) or the
   currently-open cell. Verified with a faked Hwp5File / Section that
   yields the exact ``(STARTEVENT|ENDEVENT, (model, attrs, context))``
   sequence pyhwp emits for a 2×2 table.
2. **Never-raise fallback.** When pyhwp is missing or raises, the loader
   falls back to the CSV ``텍스트`` column and ``last_native_tables`` is
   reset to ``[]``. ``last_fallback_reason`` and ``RuntimeWarning``
   contracts from the #167 spike still hold.
3. **Section surface.** ``build_sections_with_native_tables`` is a pure
   helper: empty ``native_tables`` returns
   ``[{"heading": "본문", "text": text}]`` (ADR 0001 byte-identity);
   non-empty input appends one ``"표 N (HWP native)"`` section per
   table — pipe-joined non-empty cell text.
4. **Metadata sidecar.** ``normalize_ingestion_row`` writes
   ``metadata["native_table_count"]`` and ``metadata["native_tables"]``
   (table-level summary only) **only** when the loader returned tables.
   The default path leaves these keys absent.
5. **Dispatch surface.** ``_resolve_loader("hwp")`` returns the
   ``with_tables=True`` instance for ``BIDMATE_HWP_LOADER=native_tables``
   (case-insensitive, trimmed) and is unaffected for ``pdf``.
"""

from __future__ import annotations

import csv
import os
import tempfile
import unittest
import warnings
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from ingestion import (
    HwpCsvTextLoader,
    HwpNativeLoader,
    _resolve_loader,
    build_sections_with_native_tables,
    load_documents_from_metadata_csv,
)


FIELDNAMES = [
    "공고 번호",
    "공고 차수",
    "사업명",
    "사업 금액",
    "발주 기관",
    "공개 일자",
    "입찰 참여 시작일",
    "입찰 참여 마감일",
    "사업 요약",
    "파일형식",
    "파일명",
    "텍스트",
]


def _row(**kwargs: str) -> dict[str, str]:
    base = {column: "" for column in FIELDNAMES}
    base.update(kwargs)
    return base


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _build_single_hwp_corpus(root: Path) -> tuple[Path, Path]:
    files_dir = root / "files"
    files_dir.mkdir()
    (files_dir / "table.hwp").write_bytes(b"HWP DOC")
    csv_path = root / "data_list.csv"
    _write_csv(
        csv_path,
        [
            _row(
                **{
                    "공고 번호": "20240001",
                    "공고 차수": "0",
                    "사업명": "표 사업",
                    "발주 기관": "기관 A",
                    "파일형식": "hwp",
                    "파일명": "table.hwp",
                    "텍스트": "CSV fallback body.",
                }
            )
        ],
    )
    return csv_path, files_dir


class _EnvScope:
    """Restore ``BIDMATE_HWP_LOADER`` after each test regardless of outcome."""

    def __init__(self) -> None:
        self._saved: str | None = None
        self._had_key = False

    def __enter__(self) -> "_EnvScope":
        self._had_key = "BIDMATE_HWP_LOADER" in os.environ
        self._saved = os.environ.get("BIDMATE_HWP_LOADER")
        os.environ.pop("BIDMATE_HWP_LOADER", None)
        return self

    def set(self, value: str) -> None:
        os.environ["BIDMATE_HWP_LOADER"] = value

    def __exit__(self, *exc: object) -> None:
        if self._had_key:
            os.environ["BIDMATE_HWP_LOADER"] = self._saved or ""
        else:
            os.environ.pop("BIDMATE_HWP_LOADER", None)


class DispatchSurfaceTest(unittest.TestCase):
    """The new ``native_tables`` env value swaps the loader correctly."""

    def test_default_dispatch_csv_when_pyhwp_absent(self) -> None:
        with _EnvScope():
            with mock.patch("ingestion.importlib.util.find_spec", return_value=None):
                loader = _resolve_loader("hwp")
        self.assertIsInstance(loader, HwpCsvTextLoader)
        self.assertNotIsInstance(loader, HwpNativeLoader)

    def test_native_returns_text_only_native_loader(self) -> None:
        """#167 spike still produces ``with_tables=False`` (no regression)."""
        with _EnvScope() as scope:
            scope.set("native")
            loader = _resolve_loader("hwp")
            self.assertIsInstance(loader, HwpNativeLoader)
            self.assertFalse(loader.with_tables)

    def test_native_tables_returns_table_aware_native_loader(self) -> None:
        with _EnvScope() as scope:
            scope.set("native_tables")
            loader = _resolve_loader("hwp")
            self.assertIsInstance(loader, HwpNativeLoader)
            self.assertTrue(loader.with_tables)

    def test_native_tables_env_var_is_case_insensitive_and_trimmed(self) -> None:
        with _EnvScope() as scope:
            for variant in ("native_tables", "NATIVE_TABLES", "  Native_Tables  "):
                scope.set(variant)
                loader = _resolve_loader("hwp")
                self.assertIsInstance(loader, HwpNativeLoader)
                self.assertTrue(
                    loader.with_tables, f"native_tables should set with_tables=True ({variant!r})"
                )

    def test_pdf_dispatch_unaffected_by_native_tables(self) -> None:
        from ingestion import PdfCsvTextLoader

        with _EnvScope() as scope:
            scope.set("native_tables")
            self.assertIsInstance(_resolve_loader("pdf"), PdfCsvTextLoader)


class BuildSectionsHelperTest(unittest.TestCase):
    """``build_sections_with_native_tables`` is the pure section-surface helper."""

    def test_empty_tables_returns_byte_identical_default_sections(self) -> None:
        """ADR 0001 invariant: default sections list is exactly one entry."""
        sections = build_sections_with_native_tables("body text", [])
        self.assertEqual(sections, [{"heading": "본문", "text": "body text"}])

    def test_tables_with_only_empty_cells_are_dropped(self) -> None:
        """A table whose cells are all blank yields no extra section.

        Defensive: pyhwp can emit table shells with empty cells (form
        templates, layout-only tables); we should not pollute the
        section list with zero-information chunks.
        """
        sections = build_sections_with_native_tables(
            "body",
            [
                {"table_index": 0, "rows": 1, "cols": 2, "cells": []},
                {
                    "table_index": 1,
                    "rows": 1,
                    "cols": 2,
                    "cells": [
                        {"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": ""},
                        {"row": 0, "col": 1, "rowspan": 1, "colspan": 1, "text": "   "},
                    ],
                },
            ],
        )
        self.assertEqual(sections, [{"heading": "본문", "text": "body"}])

    def test_non_empty_tables_become_extra_sections(self) -> None:
        sections = build_sections_with_native_tables(
            "body",
            [
                {
                    "table_index": 0,
                    "rows": 2,
                    "cols": 2,
                    "cells": [
                        {"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "항목"},
                        {"row": 0, "col": 1, "rowspan": 1, "colspan": 1, "text": "값"},
                        {"row": 1, "col": 0, "rowspan": 1, "colspan": 1, "text": "예산"},
                        {"row": 1, "col": 1, "rowspan": 1, "colspan": 1, "text": "1억"},
                    ],
                },
                {
                    "table_index": 1,
                    "rows": 1,
                    "cols": 1,
                    "cells": [
                        {"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "단일 셀"}
                    ],
                },
            ],
        )
        self.assertEqual(len(sections), 3)
        self.assertEqual(sections[0], {"heading": "본문", "text": "body"})
        self.assertEqual(sections[1]["heading"], "표 1 (HWP native)")
        self.assertEqual(
            sections[1]["text"].splitlines(), ["항목", "값", "예산", "1억"]
        )
        self.assertEqual(sections[2]["heading"], "표 2 (HWP native)")
        self.assertEqual(sections[2]["text"], "단일 셀")

    def test_table_heading_is_not_weak(self) -> None:
        """Heading must trip section-aware chunking, not be folded into
        the catch-all parent (rag_core.WEAK_SECTION_HEADINGS)."""
        from rag_core import WEAK_SECTION_HEADINGS

        sections = build_sections_with_native_tables(
            "body",
            [
                {
                    "table_index": 0,
                    "rows": 1,
                    "cols": 1,
                    "cells": [
                        {"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "cell"}
                    ],
                }
            ],
        )
        table_heading = sections[1]["heading"].strip().lower()
        self.assertNotIn(table_heading, WEAK_SECTION_HEADINGS)


class _FakeTableBody:
    """Stand-in for pyhwp's ``TableBody`` model class identity."""


class _FakeTableCell:
    """Stand-in for pyhwp's ``TableCell`` model class identity."""


class _FakeText:
    """Stand-in for pyhwp's ``Text`` model class identity (cooked stream)."""


class _FakeStartEvent:
    pass


class _FakeEndEvent:
    pass


class _FakeSection:
    """Section yielding a pre-baked event stream from ``__init__``."""

    def __init__(self, events: list[tuple[Any, tuple[Any, dict, dict]]]):
        self._events = events

    def events(self) -> list[tuple[Any, tuple[Any, dict, dict]]]:
        return self._events


class _FakeBodyText:
    def __init__(self, sections: list[_FakeSection]):
        self._sections = sections

    def section_list(self) -> list[_FakeSection]:
        return self._sections


class _FakeHwp5File:
    def __init__(self, sections: list[_FakeSection]):
        self.bodytext = _FakeBodyText(sections)


def _events_for_2x2_table() -> list[tuple[Any, tuple[Any, dict, dict]]]:
    """Build the exact (STARTEVENT|ENDEVENT, (model, attrs, ctx)) sequence
    pyhwp's cooked stream emits for a 2x2 table interleaved with a
    pre-table and post-table paragraph in the body.
    """
    SE = _FakeStartEvent
    EE = _FakeEndEvent
    TB = _FakeTableBody
    TC = _FakeTableCell
    TX = _FakeText
    return [
        # Body text before the table
        (SE, (TX, {"text": "사업 개요"}, {})),
        (EE, (TX, {"text": "사업 개요"}, {})),
        # Open 2x2 table
        (SE, (TB, {"rows": 2, "cols": 2}, {})),
        # Cell (0,0)
        (SE, (TC, {"row": 0, "col": 0, "rowspan": 1, "colspan": 1}, {})),
        (SE, (TX, {"text": "항목"}, {})),
        (EE, (TX, {"text": "항목"}, {})),
        (EE, (TC, {"row": 0, "col": 0, "rowspan": 1, "colspan": 1}, {})),
        # Cell (0,1)
        (SE, (TC, {"row": 0, "col": 1, "rowspan": 1, "colspan": 1}, {})),
        (SE, (TX, {"text": "값"}, {})),
        (EE, (TX, {"text": "값"}, {})),
        (EE, (TC, {"row": 0, "col": 1, "rowspan": 1, "colspan": 1}, {})),
        # Cell (1,0)
        (SE, (TC, {"row": 1, "col": 0, "rowspan": 1, "colspan": 1}, {})),
        (SE, (TX, {"text": "예산"}, {})),
        (EE, (TX, {"text": "예산"}, {})),
        (EE, (TC, {"row": 1, "col": 0, "rowspan": 1, "colspan": 1}, {})),
        # Cell (1,1) — multi-Text payload to confirm concat
        (SE, (TC, {"row": 1, "col": 1, "rowspan": 1, "colspan": 1}, {})),
        (SE, (TX, {"text": "1"}, {})),
        (EE, (TX, {"text": "1"}, {})),
        (SE, (TX, {"text": "억"}, {})),
        (EE, (TX, {"text": "억"}, {})),
        (EE, (TC, {"row": 1, "col": 1, "rowspan": 1, "colspan": 1}, {})),
        # Close table
        (EE, (TB, {"rows": 2, "cols": 2}, {})),
        # Body text after the table
        (SE, (TX, {"text": "기타"}, {})),
        (EE, (TX, {"text": "기타"}, {})),
    ]


class EventStreamExtractionTest(unittest.TestCase):
    """``_extract_hwp_native_with_tables`` reads the cooked event stream.

    These tests need to patch real pyhwp module attributes
    (``hwp5.xmlmodel.Hwp5File`` / ``hwp5.binmodel.TableBody`` etc.) so the
    SUT's lazy imports resolve to our fakes. That requires importing
    ``hwp5`` in the test setup — which is not present in minimal CI
    installs. We gate the class with ``pytest.importorskip`` so the
    suite skips cleanly when pyhwp is unavailable; the rest of the file
    (dispatch / helper / loader / wiring tests) is pyhwp-independent.
    """

    @classmethod
    def setUpClass(cls) -> None:
        pytest.importorskip("hwp5")
        pytest.importorskip("hwp5.xmlmodel")
        pytest.importorskip("hwp5.binmodel")

    def _patched_extract(self, sections: list[_FakeSection]):
        """Patch the pyhwp imports in ``_extract_hwp_native_with_tables`` so
        the function exercises its real logic against our fake stream
        without requiring the real wheel to be importable."""
        import hwp5  # type: ignore[import-not-found]  # gated by setUpClass
        import hwp5.xmlmodel  # type: ignore[import-not-found]
        import hwp5.binmodel  # type: ignore[import-not-found]

        fake_hwp = _FakeHwp5File(sections)
        return mock.patch.multiple(
            hwp5.xmlmodel,
            Hwp5File=mock.Mock(return_value=fake_hwp),
            Text=_FakeText,
            STARTEVENT=_FakeStartEvent,
            ENDEVENT=_FakeEndEvent,
        ), mock.patch.multiple(
            hwp5.binmodel,
            TableBody=_FakeTableBody,
            TableCell=_FakeTableCell,
        )

    def test_2x2_table_yields_four_cells_with_correct_coordinates(self) -> None:
        from ingestion import _extract_hwp_native_with_tables

        xmlmodel_patch, binmodel_patch = self._patched_extract(
            [_FakeSection(_events_for_2x2_table())]
        )
        with xmlmodel_patch, binmodel_patch:
            text, tables = _extract_hwp_native_with_tables(Path("/dev/null"))

        self.assertEqual("사업 개요\n기타", text)
        self.assertEqual(1, len(tables))
        table = tables[0]
        self.assertEqual(table["table_index"], 0)
        self.assertEqual(table["rows"], 2)
        self.assertEqual(table["cols"], 2)
        self.assertEqual(4, len(table["cells"]))
        self.assertEqual(
            [(c["row"], c["col"], c["text"]) for c in table["cells"]],
            [(0, 0, "항목"), (0, 1, "값"), (1, 0, "예산"), (1, 1, "1억")],
        )

    def test_document_with_no_tables_returns_empty_table_list(self) -> None:
        from ingestion import _extract_hwp_native_with_tables

        events = [
            (_FakeStartEvent, (_FakeText, {"text": "본문 only"}, {})),
            (_FakeEndEvent, (_FakeText, {"text": "본문 only"}, {})),
        ]
        xmlmodel_patch, binmodel_patch = self._patched_extract([_FakeSection(events)])
        with xmlmodel_patch, binmodel_patch:
            text, tables = _extract_hwp_native_with_tables(Path("/dev/null"))
        self.assertEqual("본문 only", text)
        self.assertEqual([], tables)

    def test_body_text_outside_tables_excludes_cell_text(self) -> None:
        """Cell ``Text`` payloads MUST NOT leak into the body string —
        otherwise table cells would be double-indexed (once as body, once
        as table section), inflating BM25 scores against table content."""
        from ingestion import _extract_hwp_native_with_tables

        xmlmodel_patch, binmodel_patch = self._patched_extract(
            [_FakeSection(_events_for_2x2_table())]
        )
        with xmlmodel_patch, binmodel_patch:
            text, _ = _extract_hwp_native_with_tables(Path("/dev/null"))
        for cell_text in ("항목", "값", "예산", "1억"):
            self.assertNotIn(cell_text, text)

    def test_empty_sections_returns_none_text_and_empty_tables(self) -> None:
        from ingestion import _extract_hwp_native_with_tables

        xmlmodel_patch, binmodel_patch = self._patched_extract([])
        with xmlmodel_patch, binmodel_patch:
            text, tables = _extract_hwp_native_with_tables(Path("/dev/null"))
        # No body text → normalize_body_text yields '' which the function
        # returns as ``None`` (matching the existing _extract_hwp_native).
        self.assertIsNone(text)
        self.assertEqual([], tables)


class LoaderWithTablesTest(unittest.TestCase):
    """``HwpNativeLoader(with_tables=True)`` routes through the new path."""

    def test_with_tables_loader_uses_table_aware_extractor(self) -> None:
        loader = HwpNativeLoader(with_tables=True)
        with mock.patch(
            "ingestion._extract_hwp_native_with_tables",
            return_value=(
                "native body",
                [
                    {
                        "table_index": 0,
                        "rows": 1,
                        "cols": 1,
                        "cells": [
                            {"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "셀"}
                        ],
                    }
                ],
            ),
        ) as mock_extract:
            text = loader.load_text({"텍스트": "csv ignored"}, Path("/nonexistent.hwp"))
        mock_extract.assert_called_once()
        self.assertEqual("native body", text)
        self.assertEqual("hwp_native", loader.last_text_source)
        self.assertEqual(1, len(loader.last_native_tables))
        self.assertEqual(loader.last_native_tables[0]["cells"][0]["text"], "셀")

    def test_default_loader_does_not_call_table_extractor(self) -> None:
        """The #167 default (``with_tables=False``) must NOT touch the new
        extractor — preserves the existing measurement baseline."""
        loader = HwpNativeLoader()
        with mock.patch(
            "ingestion._extract_hwp_native",
            return_value="native body",
        ) as text_only, mock.patch(
            "ingestion._extract_hwp_native_with_tables"
        ) as table_aware:
            loader.load_text({"텍스트": "csv ignored"}, Path("/nonexistent.hwp"))
        text_only.assert_called_once()
        table_aware.assert_not_called()
        self.assertEqual([], loader.last_native_tables)

    def test_fallback_clears_last_native_tables(self) -> None:
        loader = HwpNativeLoader(with_tables=True)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with mock.patch(
                "ingestion._extract_hwp_native_with_tables",
                side_effect=ImportError("pyhwp not installed"),
            ):
                text = loader.load_text(
                    {"텍스트": "fallback body"}, Path("/nonexistent.hwp")
                )
        self.assertEqual("fallback body", text)
        self.assertEqual("data_list_csv_text", loader.last_text_source)
        self.assertEqual([], loader.last_native_tables)
        self.assertIsNotNone(loader.last_fallback_reason)
        self.assertIn("ImportError", loader.last_fallback_reason)
        runtime_warnings = [w for w in caught if issubclass(w.category, RuntimeWarning)]
        self.assertEqual(1, len(runtime_warnings))

    def test_native_tables_reset_between_calls(self) -> None:
        """A success → failure → success sequence must not leak stale cells."""
        loader = HwpNativeLoader(with_tables=True)
        # First call: success with one table
        with mock.patch(
            "ingestion._extract_hwp_native_with_tables",
            return_value=(
                "body 1",
                [
                    {
                        "table_index": 0,
                        "rows": 1,
                        "cols": 1,
                        "cells": [
                            {"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "A"}
                        ],
                    }
                ],
            ),
        ):
            loader.load_text({"텍스트": ""}, Path("/a.hwp"))
        self.assertEqual(1, len(loader.last_native_tables))

        # Second call: fallback — tables must reset to []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            with mock.patch(
                "ingestion._extract_hwp_native_with_tables",
                side_effect=RuntimeError("corrupted body"),
            ):
                loader.load_text({"텍스트": "csv body"}, Path("/b.hwp"))
        self.assertEqual([], loader.last_native_tables)

        # Third call: success with a different table — stale cells must not bleed
        with mock.patch(
            "ingestion._extract_hwp_native_with_tables",
            return_value=(
                "body 3",
                [
                    {
                        "table_index": 0,
                        "rows": 1,
                        "cols": 1,
                        "cells": [
                            {"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "C"}
                        ],
                    }
                ],
            ),
        ):
            loader.load_text({"텍스트": ""}, Path("/c.hwp"))
        self.assertEqual(1, len(loader.last_native_tables))
        self.assertEqual("C", loader.last_native_tables[0]["cells"][0]["text"])


class IngestionWiringTest(unittest.TestCase):
    """End-to-end through ``load_documents_from_metadata_csv``."""

    def test_default_loader_keeps_one_section_and_no_native_table_metadata(self) -> None:
        """ADR 0001 invariant: default path is byte-identical to pre-#506."""
        with _EnvScope():
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                csv_path, files_dir = _build_single_hwp_corpus(root)
                docs, _ = load_documents_from_metadata_csv(csv_path, files_dir)
        self.assertEqual(1, len(docs))
        self.assertEqual(1, len(docs[0]["sections"]))
        self.assertEqual("본문", docs[0]["sections"][0]["heading"])
        self.assertNotIn("native_table_count", docs[0]["metadata"])
        self.assertNotIn("native_tables", docs[0]["metadata"])

    def test_native_tables_loader_appends_table_section_and_metadata(self) -> None:
        with _EnvScope() as scope:
            scope.set("native_tables")
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                csv_path, files_dir = _build_single_hwp_corpus(root)
                with mock.patch(
                    "ingestion._extract_hwp_native_with_tables",
                    return_value=(
                        "사업 개요",
                        [
                            {
                                "table_index": 0,
                                "rows": 2,
                                "cols": 2,
                                "cells": [
                                    {
                                        "row": 0,
                                        "col": 0,
                                        "rowspan": 1,
                                        "colspan": 1,
                                        "text": "항목",
                                    },
                                    {
                                        "row": 0,
                                        "col": 1,
                                        "rowspan": 1,
                                        "colspan": 1,
                                        "text": "값",
                                    },
                                    {
                                        "row": 1,
                                        "col": 0,
                                        "rowspan": 1,
                                        "colspan": 1,
                                        "text": "예산",
                                    },
                                    {
                                        "row": 1,
                                        "col": 1,
                                        "rowspan": 1,
                                        "colspan": 1,
                                        "text": "1억",
                                    },
                                ],
                            }
                        ],
                    ),
                ):
                    docs, _ = load_documents_from_metadata_csv(csv_path, files_dir)
        self.assertEqual(1, len(docs))
        document = docs[0]
        # Sections: body + table 1
        self.assertEqual(2, len(document["sections"]))
        self.assertEqual("본문", document["sections"][0]["heading"])
        self.assertEqual("사업 개요", document["sections"][0]["text"])
        self.assertEqual(
            "표 1 (HWP native)", document["sections"][1]["heading"]
        )
        for token in ("항목", "값", "예산", "1억"):
            self.assertIn(token, document["sections"][1]["text"])
        # Metadata sidecar
        self.assertEqual(1, document["metadata"]["native_table_count"])
        self.assertEqual(
            document["metadata"]["native_tables"],
            [{"table_index": 0, "rows": 2, "cols": 2, "cell_count": 4}],
        )
        # text_source still records the native path so observability holds
        self.assertEqual("hwp_native", document["metadata"]["text_source"])

    def test_native_tables_with_parse_failure_falls_back_silently(self) -> None:
        with _EnvScope() as scope:
            scope.set("native_tables")
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                csv_path, files_dir = _build_single_hwp_corpus(root)
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    with mock.patch(
                        "ingestion._extract_hwp_native_with_tables",
                        side_effect=OSError("not a valid OLE file"),
                    ):
                        docs, _ = load_documents_from_metadata_csv(csv_path, files_dir)
        self.assertEqual(1, len(docs))
        document = docs[0]
        self.assertEqual(1, len(document["sections"]))
        self.assertEqual("CSV fallback body.", document["sections"][0]["text"])
        self.assertEqual("data_list_csv_text", document["metadata"]["text_source"])
        self.assertNotIn("native_table_count", document["metadata"])
        runtime_warnings = [w for w in caught if issubclass(w.category, RuntimeWarning)]
        self.assertGreaterEqual(len(runtime_warnings), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
