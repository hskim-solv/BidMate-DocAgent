"""HwpNativeLoader spike regression suite (issue #167).

Covers:
  * default dispatch keeps the CSV-text path (ADR 0001 baseline invariant)
  * opt-in via ``BIDMATE_HWP_LOADER=native`` swaps to ``HwpNativeLoader``
  * ``HwpNativeLoader`` falls back to CSV text when pyhwp is missing or
    the binary cannot be parsed (so the loader degrades gracefully without
    pyhwp installed in CI)
  * ``text_source`` metadata propagates from the loader (no longer hardcoded)
  * cross-format isolation: PDF dispatch ignores the HWP-specific env var
"""

from __future__ import annotations

import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ingestion import (
    HwpCsvTextLoader,
    HwpNativeLoader,
    PdfCsvTextLoader,
    _resolve_loader,
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
    # Mock HWP bytes: not a real OLE compound document, so pyhwp parsing will
    # fail and the CSV fallback path must take over.
    (files_dir / "hwp-success.hwp").write_bytes(b"HWP DOC")

    csv_path = root / "data_list.csv"
    rows = [
        _row(
            **{
                "공고 번호": "20240001",
                "공고 차수": "0",
                "사업명": "HWP 사업",
                "발주 기관": "기관 A",
                "파일형식": "hwp",
                "파일명": "hwp-success.hwp",
                "텍스트": "CSV fallback body text.",
            }
        ),
    ]
    _write_csv(csv_path, rows)
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


class HwpNativeLoaderRegressionTest(unittest.TestCase):
    def test_default_dispatch_returns_csv_loader(self) -> None:
        with _EnvScope():
            loader = _resolve_loader("hwp")
            self.assertIsInstance(loader, HwpCsvTextLoader)
            self.assertNotIsInstance(loader, HwpNativeLoader)

    def test_opt_in_dispatch_returns_native_loader(self) -> None:
        with _EnvScope() as scope:
            scope.set("native")
            loader = _resolve_loader("hwp")
            self.assertIsInstance(loader, HwpNativeLoader)

    def test_opt_in_env_var_is_case_insensitive_and_trimmed(self) -> None:
        with _EnvScope() as scope:
            scope.set("  NATIVE  ")
            self.assertIsInstance(_resolve_loader("hwp"), HwpNativeLoader)
            scope.set("native")
            self.assertIsInstance(_resolve_loader("hwp"), HwpNativeLoader)
            scope.set("Native")
            self.assertIsInstance(_resolve_loader("hwp"), HwpNativeLoader)

    def test_pdf_dispatch_unaffected_by_hwp_env_var(self) -> None:
        with _EnvScope() as scope:
            scope.set("native")
            self.assertIsInstance(_resolve_loader("pdf"), PdfCsvTextLoader)

    def test_native_loader_falls_back_to_csv_when_pyhwp_missing(self) -> None:
        loader = HwpNativeLoader()
        # Force the import inside _extract_hwp_native to fail by injecting a
        # patched importer. This mirrors the no-pyhwp CI environment.
        with mock.patch(
            "ingestion._extract_hwp_native",
            side_effect=ImportError("pyhwp not installed"),
        ):
            text = loader.load_text(
                {"텍스트": "fallback body"}, Path("/nonexistent.hwp")
            )
        self.assertEqual("fallback body", text)
        self.assertEqual("data_list_csv_text", loader.last_text_source)

    def test_native_loader_falls_back_when_parser_raises_oserror(self) -> None:
        loader = HwpNativeLoader()
        with mock.patch(
            "ingestion._extract_hwp_native",
            side_effect=OSError("not a valid OLE file"),
        ):
            text = loader.load_text(
                {"텍스트": "csv text after parse failure"},
                Path("/nonexistent.hwp"),
            )
        self.assertEqual("csv text after parse failure", text)
        self.assertEqual("data_list_csv_text", loader.last_text_source)

    def test_native_loader_records_hwp_native_source_on_success(self) -> None:
        loader = HwpNativeLoader()
        with mock.patch(
            "ingestion._extract_hwp_native",
            return_value="native extracted body",
        ):
            text = loader.load_text(
                {"텍스트": "csv text (should be ignored)"},
                Path("/nonexistent.hwp"),
            )
        self.assertEqual("native extracted body", text)
        self.assertEqual("hwp_native", loader.last_text_source)

    def test_native_loader_empty_native_and_empty_csv_raises(self) -> None:
        loader = HwpNativeLoader()
        with mock.patch("ingestion._extract_hwp_native", return_value=None):
            with self.assertRaises(ValueError) as ctx:
                loader.load_text({"텍스트": ""}, Path("/nonexistent.hwp"))
            self.assertIn("empty_text", str(ctx.exception))

    def test_metadata_text_source_default_preserves_baseline_string(self) -> None:
        """ADR 0001 invariant: default ingestion stamps text_source=data_list_csv_text."""
        with _EnvScope():
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                csv_path, files_dir = _build_single_hwp_corpus(root)
                documents, _ = load_documents_from_metadata_csv(csv_path, files_dir)
                self.assertEqual(1, len(documents))
                self.assertEqual(
                    "data_list_csv_text",
                    documents[0]["metadata"]["text_source"],
                )

    def test_metadata_text_source_when_opt_in_with_invalid_hwp_falls_back(self) -> None:
        """Opt-in is set but the binary is mock bytes — fallback marks CSV source."""
        with _EnvScope() as scope:
            scope.set("native")
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                csv_path, files_dir = _build_single_hwp_corpus(root)
                documents, _ = load_documents_from_metadata_csv(csv_path, files_dir)
                self.assertEqual(1, len(documents))
                # pyhwp may be installed locally and raise on the mock bytes,
                # or absent and raise ImportError — either way the loader
                # records the CSV fallback as the source.
                self.assertEqual(
                    "data_list_csv_text",
                    documents[0]["metadata"]["text_source"],
                )

    def test_metadata_text_source_when_native_extraction_succeeds(self) -> None:
        """When pyhwp is mocked to succeed, the document metadata reflects it."""
        with _EnvScope() as scope:
            scope.set("native")
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                csv_path, files_dir = _build_single_hwp_corpus(root)
                with mock.patch(
                    "ingestion._extract_hwp_native",
                    return_value="native body",
                ):
                    documents, _ = load_documents_from_metadata_csv(
                        csv_path, files_dir
                    )
                self.assertEqual(1, len(documents))
                self.assertEqual(
                    "hwp_native",
                    documents[0]["metadata"]["text_source"],
                )
                self.assertEqual(
                    "native body",
                    documents[0]["sections"][0]["text"],
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
