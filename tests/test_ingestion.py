import csv
import tempfile
import unittest
from pathlib import Path

from ingestion import load_documents_from_metadata_csv
from rag_core import build_index_payload_from_documents


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


class MetadataCsvIngestionTest(unittest.TestCase):
    def test_ingests_pdf_hwp_rows_and_reports_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            files_dir = root / "files"
            files_dir.mkdir()
            (files_dir / "sample.pdf").write_bytes(b"%PDF-1.4\n")
            (files_dir / "sample.hwp").write_bytes(b"HWP Document File")
            metadata_csv = root / "data_list.csv"
            long_text = " ".join(["요구사항"] * 220)
            rows = [
                {
                    "공고 번호": "202400001",
                    "공고 차수": "0.0",
                    "사업명": "PDF 기반 사업",
                    "사업 금액": "123000000.0",
                    "발주 기관": "기관 PDF",
                    "공개 일자": "2024-01-01 09:00:00",
                    "입찰 참여 시작일": "",
                    "입찰 참여 마감일": "2024-01-15 17:00:00",
                    "사업 요약": "PDF 사업 요약",
                    "파일형식": "pdf",
                    "파일명": "sample.pdf",
                    "텍스트": "PDF 본문입니다. 보안 요구사항을 포함합니다.",
                },
                {
                    "공고 번호": "202400002",
                    "공고 차수": "1.0",
                    "사업명": "HWP 기반 사업",
                    "사업 금액": "45000000",
                    "발주 기관": "기관 HWP",
                    "공개 일자": "2024-02-01 09:00:00",
                    "입찰 참여 시작일": "2024-02-02 09:00:00",
                    "입찰 참여 마감일": "2024-02-10 17:00:00",
                    "사업 요약": "HWP 사업 요약",
                    "파일형식": "hwp",
                    "파일명": "sample.hwp",
                    "텍스트": long_text,
                },
                {
                    "공고 번호": "202400003",
                    "공고 차수": "0.0",
                    "사업명": "누락 파일 사업",
                    "사업 금액": "",
                    "발주 기관": "기관 Missing",
                    "공개 일자": "",
                    "입찰 참여 시작일": "",
                    "입찰 참여 마감일": "",
                    "사업 요약": "",
                    "파일형식": "pdf",
                    "파일명": "missing.pdf",
                    "텍스트": "파일이 없으면 인덱싱하지 않습니다.",
                },
            ]
            with metadata_csv.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
                writer.writeheader()
                writer.writerows(rows)

            documents, report = load_documents_from_metadata_csv(metadata_csv, files_dir)

            self.assertEqual(2, len(documents))
            self.assertEqual(3, report["summary"]["total_rows"])
            self.assertEqual(2, report["summary"]["indexed_documents"])
            self.assertEqual(1, report["summary"]["failed_rows"])
            failed = [record for record in report["records"] if record["status"] == "failed"]
            self.assertEqual("missing_file", failed[0]["reason"])

            first = documents[0]
            self.assertEqual("202400001-0.0", first["doc_id"])
            self.assertEqual("기관 PDF", first["agency"])
            self.assertEqual(123000000, first["metadata"]["budget"])
            self.assertEqual("pdf", first["metadata"]["file_format"])
            self.assertEqual("data_list_csv_text", first["metadata"]["text_source"])

            payload = build_index_payload_from_documents(
                documents,
                source_dir=str(metadata_csv),
                embedding_backend="hashing",
            )

            self.assertEqual(2, payload["build"]["num_documents"])
            self.assertGreater(payload["build"]["num_chunks"], 2)
            self.assertEqual({"fixed": 2}, payload["build"]["chunking"]["actual_strategy_counts"])
            self.assertEqual(2, len(payload["parent_sections"]))
            self.assertTrue(all("metadata" in chunk for chunk in payload["chunks"]))
            self.assertTrue(all("section_path" in chunk for chunk in payload["chunks"]))
            self.assertTrue(all("chunking_strategy" in chunk for chunk in payload["chunks"]))
            self.assertTrue(all(len(chunk["text"]) <= 520 for chunk in payload["chunks"]))
            self.assertEqual("202400001", payload["chunks"][0]["metadata"]["notice_id"])


class RowValidationParityRegression(unittest.TestCase):
    """Both ingestion and audit paths must surface the same failure_reason
    on shared validation-chain failures (issue #257). Guards against drift
    after the shared `_resolve_row_validation` helper was introduced."""

    def _row(self, **overrides: str) -> dict[str, str]:
        row = {col: "" for col in FIELDNAMES}
        row.update(
            {
                "공고 번호": "202400001",
                "공고 차수": "0",
                "사업명": "샘플 사업",
                "발주 기관": "기관 X",
                "파일형식": "pdf",
                "텍스트": "본문 텍스트입니다.",
            }
        )
        row.update(overrides)
        return row

    def _reasons(
        self, files_dir: Path, row: dict[str, str]
    ) -> tuple[str | None, str | None]:
        from ingestion import (
            _DuplicateTracker,
            audit_metadata_row,
            normalize_ingestion_row,
        )

        _, record_n = normalize_ingestion_row(
            row, row_number=2, files_dir=files_dir, tracker=_DuplicateTracker()
        )
        record_a = audit_metadata_row(
            row, row_number=2, files_dir=files_dir, tracker=_DuplicateTracker()
        )
        return record_n.reason, record_a.reason

    def test_missing_file_name_reason_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            normalize_reason, audit_reason = self._reasons(
                Path(tmp), self._row(파일명="")
            )
            self.assertEqual("missing_file_name", normalize_reason)
            self.assertEqual("missing_file_name", audit_reason)

    def test_unsupported_file_format_reason_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            files_dir = Path(tmp) / "files"
            files_dir.mkdir()
            (files_dir / "report.docx").write_bytes(b"")
            normalize_reason, audit_reason = self._reasons(
                files_dir, self._row(파일명="report.docx", 파일형식="docx")
            )
            self.assertEqual("unsupported_file_format", normalize_reason)
            self.assertEqual("unsupported_file_format", audit_reason)

    def test_missing_file_reason_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            files_dir = Path(tmp) / "files"
            files_dir.mkdir()
            normalize_reason, audit_reason = self._reasons(
                files_dir, self._row(파일명="absent.pdf")
            )
            self.assertEqual("missing_file", normalize_reason)
            self.assertEqual("missing_file", audit_reason)

    def test_duplicate_doc_id_reason_matches(self) -> None:
        # First row reserves the doc_id; second row collides on the same
        # canonical key. Both paths must report duplicate_doc_id on the
        # collider row when on_duplicate_doc_id defaults to "fail".
        from ingestion import (
            _DuplicateTracker,
            audit_metadata_row,
            normalize_ingestion_row,
        )

        with tempfile.TemporaryDirectory() as tmp:
            files_dir = Path(tmp) / "files"
            files_dir.mkdir()
            (files_dir / "sample.pdf").write_bytes(b"%PDF-1.4\n")
            row1 = self._row(파일명="sample.pdf")
            row2 = self._row(파일명="sample.pdf")

            tracker_n = _DuplicateTracker()
            normalize_ingestion_row(row1, 2, files_dir, tracker_n)
            _, record_n = normalize_ingestion_row(row2, 3, files_dir, tracker_n)

            tracker_a = _DuplicateTracker()
            audit_metadata_row(row1, 2, files_dir, tracker_a)
            record_a = audit_metadata_row(row2, 3, files_dir, tracker_a)

            self.assertEqual("duplicate_doc_id", record_n.reason)
            self.assertEqual("duplicate_doc_id", record_a.reason)


if __name__ == "__main__":
    unittest.main()
