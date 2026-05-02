import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

from rag_core import build_index_payload_from_documents, run_rag_query
from visual_ingestion import (
    extract_field_candidates,
    extract_table_candidates,
    load_visual_documents_from_metadata_csv,
    parse_visual_document,
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


class VisualIngestionTest(unittest.TestCase):
    @unittest.skipIf(importlib.util.find_spec("fitz") is None, "pymupdf is not installed")
    def test_parses_synthetic_pdf_to_v2_artifact(self) -> None:
        import fitz  # type: ignore

        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "visual_sample.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "사업명: 시각 파싱 사업\n1. 보안 요구사항\n접근 통제를 포함합니다.")
            doc.save(pdf_path)
            doc.close()

            document, artifact = parse_visual_document(
                pdf_path,
                doc_id="visual-pdf",
                title="시각 파싱 사업",
                agency="기관 V",
                metadata={"file_format": "pdf", "file_name": pdf_path.name},
            )

            self.assertIsNotNone(document)
            self.assertEqual(2, artifact["schema_version"])
            self.assertEqual("parsed", artifact["diagnostics"]["status"])
            self.assertTrue(artifact["pages"][0]["blocks"])
            self.assertTrue(artifact["sections"])
            self.assertEqual("visual_parsing_v2", document["metadata"]["text_source"])

    @unittest.skipIf(importlib.util.find_spec("PIL") is None, "Pillow is not installed")
    def test_image_ocr_path_uses_injected_provider(self) -> None:
        from PIL import Image

        def fake_ocr(_image):
            return [
                {
                    "text": "사업명: 이미지 OCR 사업\n항목 | 값\n보안 | 접근통제",
                    "bbox": [10, 10, 180, 90],
                    "confidence": 0.91,
                }
            ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "sample.png"
            Image.new("RGB", (200, 100), "white").save(image_path)

            document, artifact = parse_visual_document(
                image_path,
                doc_id="visual-image",
                title="이미지 OCR 사업",
                ocr_provider=fake_ocr,
            )

            self.assertIsNotNone(document)
            self.assertEqual("parsed", artifact["diagnostics"]["status"])
            self.assertEqual([1, 1], artifact["sections"][0]["page_span"])
            self.assertTrue(artifact["field_candidates"])
            self.assertTrue(artifact["tables"])
            self.assertEqual("visual_parsing_v2", document["metadata"]["document_type"])

    def test_extracts_table_and_field_candidates_from_layout_text(self) -> None:
        blocks = [
            {
                "text": "사업명: 후보 추출 사업\n항목 | 요구사항\n보안 | 접근 통제\n로그 | 감사 추적",
                "page_number": 3,
                "bbox": [1, 2, 100, 120],
                "source": "unit",
                "confidence": 1.0,
            }
        ]

        tables = extract_table_candidates(blocks, doc_id="candidate-doc")
        fields = extract_field_candidates(blocks)

        self.assertEqual(1, len(tables))
        self.assertEqual(["항목", "요구사항"], tables[0]["rows"][0])
        self.assertEqual("사업명", fields[0]["key"])
        self.assertEqual("후보 추출 사업", fields[0]["value"])

    def test_metadata_csv_visual_mode_falls_back_for_hwp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            files_dir = root / "files"
            files_dir.mkdir()
            (files_dir / "sample.hwp").write_bytes(b"HWP Document File")
            metadata_csv = root / "data_list.csv"
            with metadata_csv.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
                writer.writeheader()
                writer.writerow(
                    {
                        "공고 번호": "202400010",
                        "공고 차수": "0.0",
                        "사업명": "HWP fallback 사업",
                        "사업 금액": "",
                        "발주 기관": "기관 H",
                        "공개 일자": "",
                        "입찰 참여 시작일": "",
                        "입찰 참여 마감일": "",
                        "사업 요약": "",
                        "파일형식": "hwp",
                        "파일명": "sample.hwp",
                        "텍스트": "HWP CSV 텍스트 본문입니다. 보안 요구사항을 포함합니다.",
                    }
                )

            documents, report = load_visual_documents_from_metadata_csv(
                metadata_csv,
                files_dir,
                root / "artifacts",
            )

            self.assertEqual(1, len(documents))
            self.assertEqual("fallback", report["records"][0]["status"])
            self.assertEqual(1, report["summary"]["fallback_documents"])
            self.assertEqual("data_list_csv_text", documents[0]["metadata"]["text_source"])
            self.assertEqual("visual_fallback_hwp", documents[0]["metadata"]["visual_fallback_reason"])

    def test_region_metadata_reaches_chunks_evidence_and_citations(self) -> None:
        region = {
            "page_number": 2,
            "bbox": [10, 20, 120, 160],
            "source": "unit",
            "type": "text",
            "block_id": "block-1",
        }
        document = {
            "doc_id": "visual-region-doc",
            "title": "Region 보존 사업",
            "agency": "기관 V",
            "project": "Region 보존 사업",
            "metadata": {"document_type": "visual_parsing_v2"},
            "sections": [
                {
                    "heading": "보안 요구사항",
                    "text": "보안 요구사항은 접근 통제와 감사 추적입니다.",
                    "regions": [region],
                    "page_span": [2, 2],
                }
            ],
            "source_path": "visual-region.pdf",
        }

        index = build_index_payload_from_documents(
            [document],
            source_dir="unit",
            embedding_backend="hashing",
        )
        result = run_rag_query(index, "기관 V의 보안 요구사항은?")

        self.assertEqual([region], index["chunks"][0]["regions"])
        self.assertEqual([2, 2], index["chunks"][0]["page_span"])
        self.assertEqual([region], result["evidence"][0]["regions"])
        citation = result["answer"]["claims"][0]["citations"][0]
        self.assertEqual([region], citation["regions"])
        self.assertEqual([2, 2], citation["page_span"])


if __name__ == "__main__":
    unittest.main()
