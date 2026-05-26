from __future__ import annotations

import csv
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from ingestion import (
    HwpPdfPyMuPdf4LlmLoader,
    PdfPyMuPdf4LlmLoader,
    _HwpPdfPyMuPdf4LlmFallback,
    _reset_kordoc_loaders,
    _resolve_loader,
    load_documents_from_metadata_csv,
)
from rag_answer import make_citation


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


def _write_metadata_csv(path: Path, file_name: str, text: str = "csv fallback") -> None:
    row = {column: "" for column in FIELDNAMES}
    row.update(
        {
            "공고 번호": "20260001",
            "공고 차수": "0",
            "사업명": "HWP PDF PyMuPDF4LLM 사업",
            "발주 기관": "기관",
            "파일형식": "hwp",
            "파일명": file_name,
            "텍스트": text,
        }
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerow(row)


class HwpPdfPyMuPdf4LlmLoaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self._env_backup = {
            key: os.environ.get(key)
            for key in (
                "BIDMATE_HWP_LOADER",
                "BIDMATE_PDF_LOADER",
                "BIDMATE_INGEST_REDACT_PII",
                "BIDMATE_HWP_PDF_ARTIFACT_DIR",
            )
        }
        for key in self._env_backup:
            os.environ.pop(key, None)
        _reset_kordoc_loaders()

    def tearDown(self) -> None:
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _reset_kordoc_loaders()

    def test_default_hwp_resolver_uses_pdf_pymupdf4llm_loader(self) -> None:
        loader = _resolve_loader("hwp")

        self.assertIsInstance(loader, HwpPdfPyMuPdf4LlmLoader)

    def test_default_pdf_resolver_uses_pymupdf4llm_loader(self) -> None:
        loader = _resolve_loader("pdf")

        self.assertIsInstance(loader, PdfPyMuPdf4LlmLoader)

    def test_success_preserves_page_sections_in_metadata_ingestion(self) -> None:
        os.environ["BIDMATE_HWP_LOADER"] = "pdf_pymupdf4llm"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            files_dir = root / "files"
            files_dir.mkdir()
            hwp_path = files_dir / "sample.hwp"
            hwp_path.write_bytes(b"HWP")
            csv_path = root / "data_list.csv"
            _write_metadata_csv(csv_path, hwp_path.name)
            sections = [
                {"heading": "page-1", "text": "first page", "page_span": [1, 1]},
                {"heading": "page-2", "text": "second page", "page_span": [2, 2]},
            ]

            with mock.patch(
                "ingestion._extract_hwp_pdf_pymupdf4llm",
                return_value=(
                    "first page\n\nsecond page",
                    sections,
                    {
                        "source_sha256": "source",
                        "converted_pdf_sha256": "converted",
                        "converted_pdf_page_count": 2,
                        "citation_basis": "libreoffice_converted_pdf",
                    },
                    {"pymupdf4llm_numeric_only_chunks_skipped": 0},
                ),
            ):
                documents, report = load_documents_from_metadata_csv(csv_path, files_dir)

        self.assertEqual(documents[0]["sections"], sections)
        self.assertEqual(documents[0]["metadata"]["text_source"], "pdf_pymupdf4llm")
        self.assertEqual(documents[0]["metadata"]["citation_basis"], "libreoffice_converted_pdf")
        self.assertEqual(documents[0]["metadata"]["converted_pdf_page_count"], 2)
        self.assertEqual(report["summary"]["text_source_counts"]["hwp"]["pdf_pymupdf4llm"], 1)

    def test_pii_redaction_applies_to_page_sections(self) -> None:
        os.environ["BIDMATE_HWP_LOADER"] = "pdf_pymupdf4llm"
        os.environ["BIDMATE_INGEST_REDACT_PII"] = "true"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            files_dir = root / "files"
            files_dir.mkdir()
            hwp_path = files_dir / "sample.hwp"
            hwp_path.write_bytes(b"HWP")
            csv_path = root / "data_list.csv"
            _write_metadata_csv(csv_path, hwp_path.name)
            sections = [
                {
                    "heading": "page-1",
                    "text": "담당자 email person@example.com",
                    "page_span": [1, 1],
                }
            ]

            with mock.patch(
                "ingestion._extract_hwp_pdf_pymupdf4llm",
                return_value=(
                    "담당자 email person@example.com",
                    sections,
                    {"citation_basis": "libreoffice_converted_pdf"},
                    {},
                ),
            ):
                documents, _ = load_documents_from_metadata_csv(csv_path, files_dir)

        self.assertIn("<email>", documents[0]["sections"][0]["text"])
        self.assertNotIn("person@example.com", documents[0]["sections"][0]["text"])

    def test_hwp_success_preserves_pdf_artifact_metadata_and_skips_numeric_chunks(self) -> None:
        fake_module = types.ModuleType("pymupdf4llm")
        fake_module.to_markdown = mock.Mock(
            return_value=[
                {"text": "1", "metadata": {"page": 1}},
                {"text": "body page", "metadata": {"page": 2}},
            ]
        )  # type: ignore[attr-defined]

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "artifacts"
            os.environ["BIDMATE_HWP_PDF_ARTIFACT_DIR"] = str(artifact_dir)
            hwp_path = root / "doc.hwp"
            pdf_path = root / "converted.pdf"
            hwp_path.write_bytes(b"HWP source")
            pdf_path.write_bytes(b"%PDF converted")
            loader = HwpPdfPyMuPdf4LlmLoader()

            with mock.patch(
                "ingestion._convert_hwp_to_pdf",
                return_value=(pdf_path, "/usr/bin/soffice", "LibreOffice 25.8"),
            ):
                with mock.patch("ingestion._validate_converted_pdf", return_value=2):
                    with mock.patch.dict(sys.modules, {"pymupdf4llm": fake_module}):
                        text = loader.load_text({"텍스트": "csv body"}, hwp_path)

            self.assertEqual(text, "body page")
            self.assertEqual(loader.last_sections[0]["page_span"], [2, 2])
            self.assertEqual(loader.last_metadata["citation_basis"], "libreoffice_converted_pdf")
            self.assertEqual(loader.last_metadata["converted_pdf_page_count"], 2)
            self.assertTrue(Path(loader.last_metadata["converted_pdf_path"]).exists())
            self.assertEqual(loader.last_parser_health["pymupdf4llm_numeric_only_chunks_skipped"], 1)

    def test_pdf_success_uses_source_pdf_citation_metadata(self) -> None:
        fake_module = types.ModuleType("pymupdf4llm")
        fake_module.to_markdown = mock.Mock(
            return_value=[{"text": "pdf body", "metadata": {"page_number": 3}}]
        )  # type: ignore[attr-defined]

        with TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "doc.pdf"
            pdf_path.write_bytes(b"%PDF source")
            loader = PdfPyMuPdf4LlmLoader()

            with mock.patch("ingestion._validate_source_pdf", return_value=5):
                with mock.patch.dict(sys.modules, {"pymupdf4llm": fake_module}):
                    text = loader.load_text({"텍스트": "csv body"}, pdf_path)

        self.assertEqual(text, "pdf body")
        self.assertEqual(loader.last_sections[0]["page_span"], [3, 3])
        self.assertEqual(loader.last_metadata["citation_basis"], "source_pdf")
        self.assertEqual(loader.last_metadata["citation_pdf_page_count"], 5)

    def test_converter_unavailable_raises_fail_closed(self) -> None:
        loader = HwpPdfPyMuPdf4LlmLoader()

        with mock.patch("ingestion._resolve_hwp_to_pdf_converter", return_value=None):
            with self.assertRaises(RuntimeError):
                loader.load_text({"텍스트": "csv body"}, Path("/files/doc.hwp"))

        self.assertEqual(loader.last_text_source, "data_list_csv_text")
        self.assertIn("hwp_to_pdf_converter_unavailable", loader.last_fallback_reason or "")

    def test_nonzero_exit_fallback_redacts_stderr_path_and_filename(self) -> None:
        loader = HwpPdfPyMuPdf4LlmLoader()
        source_path = Path("/private/source/secret.hwp")
        proc = subprocess.CompletedProcess(
            ["soffice"],
            1,
            "",
            'Error: source file could not be loaded: /private/source/secret.hwp "secret.hwp"',
        )

        with mock.patch("ingestion._resolve_hwp_to_pdf_converter", return_value="/usr/bin/soffice"):
            with mock.patch.object(subprocess, "run", return_value=proc):
                with self.assertRaises(RuntimeError):
                    loader.load_text({"텍스트": "csv body"}, source_path)

        reason = loader.last_fallback_reason or ""
        self.assertIn("hwp_to_pdf_nonzero_exit", reason)
        self.assertNotIn("/private/source", reason)
        self.assertNotIn("secret.hwp", reason)

    def test_missing_pdf_output_raises_fail_closed(self) -> None:
        loader = HwpPdfPyMuPdf4LlmLoader()
        proc = subprocess.CompletedProcess(["soffice"], 0, "", "source file could not be loaded")

        with mock.patch("ingestion._resolve_hwp_to_pdf_converter", return_value="/usr/bin/soffice"):
            with mock.patch.object(subprocess, "run", return_value=proc):
                with self.assertRaises(RuntimeError):
                    loader.load_text({"텍스트": "csv body"}, Path("/files/doc.hwp"))

        self.assertIn("hwp_to_pdf_not_produced", loader.last_fallback_reason or "")

    def test_invalid_pdf_raises_fail_closed(self) -> None:
        loader = HwpPdfPyMuPdf4LlmLoader()

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            if "--version" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "LibreOffice 25.8", "")
            out_dir = Path(cmd[cmd.index("--outdir") + 1])
            (out_dir / "doc.pdf").write_bytes(b"")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch("ingestion._resolve_hwp_to_pdf_converter", return_value="/usr/bin/soffice"):
            with mock.patch.object(subprocess, "run", side_effect=fake_run):
                with mock.patch("ingestion.sha256_file", return_value="sha"):
                    with self.assertRaises(RuntimeError):
                        loader.load_text({"텍스트": "csv body"}, Path("/files/doc.hwp"))

        self.assertIn("hwp_to_pdf_invalid_pdf", loader.last_fallback_reason or "")

    def test_pymupdf4llm_unavailable_raises_fail_closed(self) -> None:
        loader = HwpPdfPyMuPdf4LlmLoader()
        with mock.patch(
            "ingestion._convert_hwp_to_pdf",
            return_value=(Path("/tmp/doc.pdf"), "/usr/bin/soffice", "LibreOffice 25.8"),
        ):
            with mock.patch("ingestion._validate_converted_pdf", return_value=1):
                with mock.patch("ingestion.sha256_file", return_value="sha"):
                    with mock.patch.dict(sys.modules, {"pymupdf4llm": None}):
                        with self.assertRaises(RuntimeError):
                            loader.load_text({"텍스트": "csv body"}, Path("/files/doc.hwp"))

        self.assertIn("pymupdf4llm_unavailable", loader.last_fallback_reason or "")

    def test_pymupdf4llm_empty_output_raises_fail_closed(self) -> None:
        loader = HwpPdfPyMuPdf4LlmLoader()
        fake_module = types.ModuleType("pymupdf4llm")
        fake_module.to_markdown = mock.Mock(return_value=[{"text": ""}])  # type: ignore[attr-defined]

        with mock.patch(
            "ingestion._convert_hwp_to_pdf",
            return_value=(Path("/tmp/doc.pdf"), "/usr/bin/soffice", "LibreOffice 25.8"),
        ):
            with mock.patch("ingestion._validate_converted_pdf", return_value=1):
                with mock.patch("ingestion.sha256_file", return_value="sha"):
                    with mock.patch.dict(sys.modules, {"pymupdf4llm": fake_module}):
                        with self.assertRaises(RuntimeError):
                            loader.load_text({"텍스트": "csv body"}, Path("/files/doc.hwp"))

        self.assertIn("pymupdf4llm_empty_output", loader.last_fallback_reason or "")

    def test_pymupdf4llm_parse_failed_raises_fail_closed(self) -> None:
        loader = HwpPdfPyMuPdf4LlmLoader()
        fake_module = types.ModuleType("pymupdf4llm")
        fake_module.to_markdown = mock.Mock(side_effect=ValueError("bad pdf"))  # type: ignore[attr-defined]

        with mock.patch(
            "ingestion._convert_hwp_to_pdf",
            return_value=(Path("/tmp/doc.pdf"), "/usr/bin/soffice", "LibreOffice 25.8"),
        ):
            with mock.patch("ingestion._validate_converted_pdf", return_value=1):
                with mock.patch("ingestion.sha256_file", return_value="sha"):
                    with mock.patch.dict(sys.modules, {"pymupdf4llm": fake_module}):
                        with self.assertRaises(RuntimeError):
                            loader.load_text({"텍스트": "csv body"}, Path("/files/doc.hwp"))

        self.assertIn("pymupdf4llm_parse_failed", loader.last_fallback_reason or "")

    def test_hwp_parser_fail_closed_by_default(self) -> None:
        loader = HwpPdfPyMuPdf4LlmLoader()

        with mock.patch(
            "ingestion._extract_hwp_pdf_pymupdf4llm",
            side_effect=_HwpPdfPyMuPdf4LlmFallback("pymupdf4llm_empty_output"),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                loader.load_text({"텍스트": "csv body"}, Path("/files/doc.hwp"))

        self.assertIn("pymupdf4llm_empty_output", str(ctx.exception))

    def test_fail_closed_parser_error_is_reported_per_row(self) -> None:
        os.environ["BIDMATE_HWP_LOADER"] = "pdf_pymupdf4llm"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            files_dir = root / "files"
            files_dir.mkdir()
            (files_dir / "bad.hwp").write_bytes(b"HWP bad")
            (files_dir / "good.hwp").write_bytes(b"HWP good")
            csv_path = root / "data_list.csv"
            rows = []
            for notice_id, file_name, text in (
                ("20260001", "bad.hwp", "bad csv fallback must not be used"),
                ("20260002", "good.hwp", "good csv fallback must not be used"),
            ):
                row = {column: "" for column in FIELDNAMES}
                row.update(
                    {
                        "공고 번호": notice_id,
                        "공고 차수": "0",
                        "사업명": "fail-closed telemetry 사업",
                        "발주 기관": "기관",
                        "파일형식": "hwp",
                        "파일명": file_name,
                        "텍스트": text,
                    }
                )
                rows.append(row)
            with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
                writer.writeheader()
                writer.writerows(rows)

            def fake_extract(source_path: Path):  # type: ignore[no-untyped-def]
                if source_path.name == "bad.hwp":
                    raise _HwpPdfPyMuPdf4LlmFallback(
                        "hwp_to_pdf_not_produced",
                        "source file could not be loaded",
                    )
                return (
                    "good page body",
                    [{"heading": "page-1", "text": "good page body", "page_span": [1, 1]}],
                    {"citation_basis": "libreoffice_converted_pdf"},
                    {},
                )

            with mock.patch("ingestion._extract_hwp_pdf_pymupdf4llm", side_effect=fake_extract):
                documents, report = load_documents_from_metadata_csv(csv_path, files_dir)

        self.assertEqual(1, len(documents))
        self.assertEqual("20260002-0", documents[0]["doc_id"])
        self.assertEqual("good page body", documents[0]["sections"][0]["text"])
        self.assertEqual(1, report["summary"]["failed_rows"])
        self.assertEqual(
            {"hwp_to_pdf_not_produced": 1},
            report["summary"]["failure_reasons"],
        )
        failed = [record for record in report["records"] if record["status"] == "failed"]
        self.assertEqual("data_list_csv_text", failed[0]["text_source"])
        self.assertIn("hwp_to_pdf_not_produced", failed[0]["fallback_reason"])

    def test_answer_citation_includes_canonical_pdf_metadata_without_path(self) -> None:
        citation = make_citation(
            {
                "doc_id": "doc",
                "chunk_id": "doc::chunk-001",
                "title": "title",
                "section": "page-2",
                "agency": "agency",
                "section_path": ["page-2"],
                "page_span": [2, 2],
                "text_span_hash": "hash",
                "metadata": {
                    "text_source": "pdf_pymupdf4llm",
                    "citation_basis": "libreoffice_converted_pdf",
                    "converted_pdf_sha256": "abc",
                    "converted_pdf_page_count": 143,
                    "converted_pdf_path": "/private/path/doc.pdf",
                },
            }
        )

        self.assertEqual("LibreOffice 변환 PDF p.2", citation["citation_label"])
        self.assertEqual("pdf_pymupdf4llm", citation["text_source"])
        self.assertEqual("libreoffice_converted_pdf", citation["citation_basis"])
        self.assertEqual("hash", citation["text_span_hash"])
        self.assertNotIn("converted_pdf_path", citation)


if __name__ == "__main__":
    unittest.main()
