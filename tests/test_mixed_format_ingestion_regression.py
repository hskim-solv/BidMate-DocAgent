"""Mixed PDF/HWP ingestion regression suite (issue #54).

Protects the v1 CSV-text path against regressions in:
  * mixed PDF + HWP success rows producing stable doc_ids
  * per-failure-reason grouped diagnostics in ingestion_report.json
  * duplicate handling under both 'fail' and 'suffix' policies
  * downstream RAG payload contract for the mixed corpus

Tests deliberately use small text fixtures so the suite stays fast and
CI-friendly. Extending the suite is documented in
``docs/real-data/real-data-ingestion.md``.
"""

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ingestion import (
    INGESTION_REPORT_SCHEMA_VERSION,
    load_documents_from_metadata_csv,
)
from rag_core import build_index_payload_from_documents


REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _build_mixed_corpus(root: Path) -> tuple[Path, Path, list[dict[str, str]]]:
    files_dir = root / "files"
    files_dir.mkdir()
    (files_dir / "pdf-success.pdf").write_bytes(b"%PDF-1.4\n")
    (files_dir / "hwp-success.hwp").write_bytes(b"HWP DOC")
    (files_dir / "pdf-dup-a.pdf").write_bytes(b"%PDF-1.4\n")
    (files_dir / "pdf-dup-b.pdf").write_bytes(b"%PDF-1.4\n")
    (files_dir / "weird.doc").write_bytes(b"WORD")

    csv_path = root / "data_list.csv"
    rows = [
        _row(
            **{
                "공고 번호": "20240001",
                "공고 차수": "0",
                "사업명": "PDF 사업",
                "발주 기관": "기관 A",
                "파일형식": "pdf",
                "파일명": "pdf-success.pdf",
                "텍스트": "PDF 본문 내용 보안 요구사항.",
            }
        ),
        _row(
            **{
                "공고 번호": "20240002",
                "공고 차수": "1",
                "사업명": "HWP 사업",
                "발주 기관": "기관 B",
                "파일형식": "hwp",
                "파일명": "hwp-success.hwp",
                "텍스트": "HWP 본문 내용 일정 정보.",
            }
        ),
        _row(
            **{
                "공고 번호": "20240003",
                "공고 차수": "0",
                "사업명": "누락 파일",
                "발주 기관": "기관 C",
                "파일형식": "pdf",
                "파일명": "missing.pdf",
                "텍스트": "본문이 있어도 파일이 없으면 인덱싱 실패.",
            }
        ),
        _row(
            **{
                "공고 번호": "20240004",
                "공고 차수": "0",
                "사업명": "지원되지 않는 형식",
                "발주 기관": "기관 D",
                "파일형식": "doc",
                "파일명": "weird.doc",
                "텍스트": "본문",
            }
        ),
        _row(
            **{
                "공고 번호": "20240005",
                "공고 차수": "0",
                "사업명": "원본",
                "발주 기관": "기관 E",
                "파일형식": "pdf",
                "파일명": "pdf-dup-a.pdf",
                "텍스트": "본문 가",
            }
        ),
        _row(
            **{
                "공고 번호": "20240005",
                "공고 차수": "0",
                "사업명": "충돌",
                "발주 기관": "기관 E",
                "파일형식": "pdf",
                "파일명": "pdf-dup-b.pdf",
                "텍스트": "본문 나",
            }
        ),
    ]
    _write_csv(csv_path, rows)
    return csv_path, files_dir, rows


class MixedFormatIngestionTest(unittest.TestCase):
    def setUp(self) -> None:
        # ADR 0049: kordoc is now the default HWP + PDF backend, but this
        # suite uses dummy 0-byte fixtures that kordoc can't parse. Force
        # the CSV-text loader for both formats so the suite stays an
        # offline-friendly fixture of the v1 path (the kordoc subprocess +
        # fallback path is covered by tests/test_ingestion_kordoc_regression.py).
        import os
        self._env_backup = {
            "BIDMATE_HWP_LOADER": os.environ.get("BIDMATE_HWP_LOADER"),
            "BIDMATE_PDF_LOADER": os.environ.get("BIDMATE_PDF_LOADER"),
        }
        os.environ["BIDMATE_HWP_LOADER"] = "csv_text"
        os.environ["BIDMATE_PDF_LOADER"] = "csv_text"

    def tearDown(self) -> None:
        import os
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_default_fail_policy_indexes_three_and_reports_three_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path, files_dir, _ = _build_mixed_corpus(root)
            documents, report = load_documents_from_metadata_csv(csv_path, files_dir)

            self.assertEqual(3, len(documents))
            doc_ids = {doc["doc_id"] for doc in documents}
            self.assertEqual(
                {"20240001-0", "20240002-1", "20240005-0"},
                doc_ids,
            )

            summary = report["summary"]
            self.assertEqual(INGESTION_REPORT_SCHEMA_VERSION, summary["schema_version"])
            self.assertEqual(6, summary["total_rows"])
            self.assertEqual(3, summary["indexed_documents"])
            self.assertEqual(3, summary["failed_rows"])
            self.assertEqual(
                {
                    "missing_file": 1,
                    "unsupported_file_format": 1,
                    "duplicate_doc_id": 1,
                },
                summary["failure_reasons"],
            )
            self.assertEqual({"pdf": 4, "hwp": 1, "doc": 1}, summary["file_formats"])
            self.assertEqual({"notice_id": 3}, summary["doc_id_sources"])
            self.assertEqual(
                {"20240005-0": [6, 7]},
                summary["duplicate_doc_ids"],
            )
            for reason in ("missing_file", "unsupported_file_format", "duplicate_doc_id"):
                examples = summary["failure_examples"].get(reason)
                self.assertTrue(examples, f"missing examples for reason: {reason}")
            taxonomy = report["failure_taxonomy"]
            for reason in summary["failure_reasons"]:
                self.assertIn(reason, taxonomy)

    def test_suffix_policy_keeps_duplicate_row_indexable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path, files_dir, _ = _build_mixed_corpus(root)
            documents, report = load_documents_from_metadata_csv(
                csv_path,
                files_dir,
                on_duplicate_doc_id="suffix",
            )

            self.assertEqual(4, len(documents))
            doc_ids = [doc["doc_id"] for doc in documents]
            self.assertIn("20240005-0", doc_ids)
            self.assertIn("20240005-0-2", doc_ids)
            second = next(d for d in documents if d["doc_id"] == "20240005-0-2")
            self.assertEqual("suffix", second["metadata"]["doc_id_resolution"])
            self.assertEqual("20240005-0", second["metadata"]["doc_id_base"])

            summary = report["summary"]
            self.assertEqual(2, summary["failed_rows"])
            self.assertNotIn("duplicate_doc_id", summary["failure_reasons"])
            self.assertEqual("suffix", summary["on_duplicate_doc_id"])

    def test_rag_payload_chunks_carry_mixed_format_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path, files_dir, _ = _build_mixed_corpus(root)
            documents, _ = load_documents_from_metadata_csv(csv_path, files_dir)

            payload = build_index_payload_from_documents(
                documents,
                source_dir=str(csv_path),
                embedding_backend="hashing",
            )

            self.assertEqual(3, payload["build"]["num_documents"])
            self.assertGreaterEqual(payload["build"]["num_chunks"], 3)
            chunk_formats = {
                chunk["metadata"]["file_format"] for chunk in payload["chunks"]
            }
            self.assertEqual({"pdf", "hwp"}, chunk_formats)
            self.assertTrue(
                all(chunk["metadata"]["text_source"] == "data_list_csv_text" for chunk in payload["chunks"])
            )

    def test_text_source_counts_aggregated_by_format(self) -> None:
        """Issue #715: summary.text_source_counts buckets per (format, source).

        The mixed-corpus fixture only exercises the CSV-text path
        (PdfCsvTextLoader / HwpCsvTextLoader, forced via
        ``BIDMATE_HWP_LOADER=csv_text``), so every indexed row reports the
        default fallback provenance. A separate fixture that exercises the
        kordoc backend (ADR 0049) would produce ``{"kordoc": N}`` here —
        covered by ``tests/test_ingestion_kordoc_regression.py``.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path, files_dir, _ = _build_mixed_corpus(root)
            _, report = load_documents_from_metadata_csv(csv_path, files_dir)

            summary = report["summary"]
            # Bumped 3 → 4 in issue #902 (additive nested_table_loss_* fields
            # on summary.chunk_health). Existing summary fields below are
            # unchanged.
            self.assertEqual(4, summary["schema_version"])
            self.assertEqual(
                {
                    "pdf": {"data_list_csv_text": 2},
                    "hwp": {"data_list_csv_text": 1},
                },
                summary["text_source_counts"],
            )
            # No HWP native loader was exercised → no fallback messages.
            self.assertEqual({}, summary["fallback_reasons"])

    def test_chunk_health_is_not_attached_by_ingestion_loader(self) -> None:
        """``summary.chunk_health`` is wired in by ``scripts/build_index.py``
        (after the chunk-building stage), not by the ingestion loader itself.

        This boundary keeps ``load_documents_from_metadata_csv`` cheap and
        side-effect-free for callers that only need the document list (e.g.
        the validator CLI). The build-index CLI is the single integration
        point that pays for chunk-health computation.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path, files_dir, _ = _build_mixed_corpus(root)
            _, report = load_documents_from_metadata_csv(csv_path, files_dir)
            self.assertNotIn("chunk_health", report["summary"])

    def test_validate_data_list_cli_returns_exit_code_one_for_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path, files_dir, _ = _build_mixed_corpus(root)
            output_path = root / "validation.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "validate_data_list.py"),
                    "--metadata_csv",
                    str(csv_path),
                    "--files_dir",
                    str(files_dir),
                    "--output_path",
                    str(output_path),
                    "--quiet",
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(1, result.returncode, result.stderr)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("validation", report["mode"])
            self.assertTrue(report["summary"]["schema_ok"])
            self.assertEqual(3, report["summary"]["failed_rows"])
            self.assertIn("duplicate_doc_id", report["summary"]["failure_reasons"])

    def test_validate_data_list_cli_returns_exit_code_zero_when_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files_dir = root / "files"
            files_dir.mkdir()
            (files_dir / "ok.pdf").write_bytes(b"%PDF-1.4\n")
            csv_path = root / "data_list.csv"
            _write_csv(
                csv_path,
                rows=[
                    _row(
                        **{
                            "공고 번호": "1",
                            "공고 차수": "0",
                            "사업명": "정상",
                            "발주 기관": "기관",
                            "파일형식": "pdf",
                            "파일명": "ok.pdf",
                            "텍스트": "본문",
                        }
                    ),
                ],
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "validate_data_list.py"),
                    "--metadata_csv",
                    str(csv_path),
                    "--files_dir",
                    str(files_dir),
                    "--quiet",
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
