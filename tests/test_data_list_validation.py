"""Tests for issue #51 (data_list.csv validator) and #52 (canonical doc_id)."""

import csv
import tempfile
import unittest
from pathlib import Path

from ingestion import (
    FAILURE_TAXONOMY,
    canonical_doc_id,
    load_documents_from_metadata_csv,
    make_doc_id,
    make_doc_id_from_file_name,
    validate_data_list_csv,
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


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None) -> None:
    fieldnames = fieldnames or FIELDNAMES
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class CanonicalDocIdTest(unittest.TestCase):
    """Issue #52 — deterministic doc_id generation."""

    def test_notice_id_priority_over_file_name(self) -> None:
        self.assertEqual(
            "20240001-1",
            canonical_doc_id("20240001", "1", "anything.pdf"),
        )

    def test_file_name_fallback_when_notice_id_missing(self) -> None:
        self.assertEqual(
            "교육과정-안내서",
            canonical_doc_id("", "", "교육과정 안내서.pdf"),
        )

    def test_returns_none_when_no_signal(self) -> None:
        self.assertIsNone(canonical_doc_id("", "", ""))

    def test_canonical_normalization_is_idempotent(self) -> None:
        first = canonical_doc_id("  20240001 ", "1.0", "Sample.pdf")
        second = canonical_doc_id("20240001", "1.0", "Sample.pdf")
        self.assertEqual(first, second)

    def test_make_doc_id_collapses_internal_whitespace(self) -> None:
        self.assertEqual("a-b-c", make_doc_id("a b", "c"))

    def test_make_doc_id_from_file_name_handles_unicode(self) -> None:
        self.assertEqual(
            "사업-안내서",
            make_doc_id_from_file_name("사업 안내서.pdf"),
        )


class ValidateDataListCsvTest(unittest.TestCase):
    """Issue #51 — schema audit + #53 grouped diagnostics."""

    def test_missing_required_column_is_a_schema_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "files").mkdir()
            csv_path = root / "data_list.csv"
            partial_fieldnames = [c for c in FIELDNAMES if c != "발주 기관"]
            _write_csv(csv_path, rows=[], fieldnames=partial_fieldnames)
            report = validate_data_list_csv(csv_path, root / "files")
            self.assertFalse(report["summary"]["schema_ok"])
            codes = {issue["code"] for issue in report["schema_issues"]}
            self.assertIn("missing_required_column", codes)
            fields = {issue["field"] for issue in report["schema_issues"]}
            self.assertIn("발주 기관", fields)

    def test_grouped_failure_reasons_with_examples(self) -> None:
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
                            "사업명": "정상 사업",
                            "발주 기관": "기관 A",
                            "파일형식": "pdf",
                            "파일명": "ok.pdf",
                            "텍스트": "본문",
                        }
                    ),
                    _row(
                        **{
                            "공고 번호": "2",
                            "공고 차수": "0",
                            "사업명": "누락 사업",
                            "발주 기관": "기관 B",
                            "파일형식": "pdf",
                            "파일명": "missing.pdf",
                            "텍스트": "본문",
                        }
                    ),
                    _row(
                        **{
                            "공고 번호": "3",
                            "공고 차수": "0",
                            "사업명": "지원되지 않는 형식",
                            "발주 기관": "기관 C",
                            "파일형식": "doc",
                            "파일명": "weird.doc",
                            "텍스트": "본문",
                        }
                    ),
                ],
            )
            report = validate_data_list_csv(csv_path, files_dir)
            self.assertTrue(report["summary"]["schema_ok"])
            self.assertEqual(3, report["summary"]["total_rows"])
            self.assertEqual(1, report["summary"]["ok_rows"])
            self.assertEqual(2, report["summary"]["failed_rows"])
            self.assertEqual(
                {"missing_file": 1, "unsupported_file_format": 1},
                report["summary"]["failure_reasons"],
            )
            self.assertEqual(
                ["missing_file", "unsupported_file_format"],
                sorted(report["summary"]["failure_examples"].keys()),
            )
            for examples in report["summary"]["failure_examples"].values():
                self.assertGreaterEqual(len(examples), 1)
            self.assertEqual(report["failure_taxonomy"], FAILURE_TAXONOMY)

    def test_duplicate_resolution_explains_collision_under_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files_dir = root / "files"
            files_dir.mkdir()
            (files_dir / "a.pdf").write_bytes(b"%PDF-1.4\n")
            (files_dir / "b.pdf").write_bytes(b"%PDF-1.4\n")
            csv_path = root / "data_list.csv"
            _write_csv(
                csv_path,
                rows=[
                    _row(
                        **{
                            "공고 번호": "20240001",
                            "공고 차수": "0",
                            "사업명": "원본",
                            "발주 기관": "기관",
                            "파일형식": "pdf",
                            "파일명": "a.pdf",
                            "텍스트": "본문",
                        }
                    ),
                    _row(
                        **{
                            "공고 번호": "20240001",
                            "공고 차수": "0",
                            "사업명": "충돌",
                            "발주 기관": "기관",
                            "파일형식": "pdf",
                            "파일명": "b.pdf",
                            "텍스트": "본문",
                        }
                    ),
                ],
            )
            report = validate_data_list_csv(csv_path, files_dir)
            self.assertEqual(
                {"duplicate_doc_id": 1},
                report["summary"]["failure_reasons"],
            )
            duplicates = report["summary"]["duplicate_doc_ids"]
            self.assertIn("20240001-0", duplicates)
            self.assertEqual([2, 3], duplicates["20240001-0"])
            second_record = next(
                record for record in report["records"] if record["row_number"] == 3
            )
            self.assertEqual("duplicate_doc_id", second_record["reason"])
            resolution = second_record["duplicate_resolution"]
            self.assertEqual("fail", resolution["policy"])
            self.assertEqual(2, resolution["first_seen_row"])
            self.assertEqual("20240001-0-2", resolution["suggested_doc_id"])

    def test_blank_text_is_a_failure_not_a_warning(self) -> None:
        # Mirrors the ingestion path which raises ``empty_text`` for blank
        # body text. Validating a CSV where every row has empty text must
        # not exit clean — otherwise the pre-flight check claims success
        # for inputs that will fail the actual index build.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files_dir = root / "files"
            files_dir.mkdir()
            (files_dir / "a.pdf").write_bytes(b"%PDF-1.4\n")
            csv_path = root / "data_list.csv"
            _write_csv(
                csv_path,
                rows=[
                    _row(
                        **{
                            "공고 번호": "1",
                            "공고 차수": "0",
                            "사업명": "",
                            "발주 기관": "",
                            "파일형식": "pdf",
                            "파일명": "a.pdf",
                            "텍스트": "",
                        }
                    ),
                ],
            )
            report = validate_data_list_csv(csv_path, files_dir)
            self.assertEqual(0, report["summary"]["ok_rows"])
            self.assertEqual(1, report["summary"]["failed_rows"])
            self.assertEqual(
                {"empty_text": 1},
                report["summary"]["failure_reasons"],
            )
            warnings = report["summary"]["blank_field_warnings"]
            self.assertEqual({"blank_agency": 1, "blank_project": 1}, warnings)
            self.assertNotIn("blank_text", warnings)
            self.assertIn("empty_text", report["failure_taxonomy"])

    def test_fail_policy_does_not_reserve_suggested_doc_id(self) -> None:
        # Regression for codex P1: under ``on_duplicate_doc_id="fail"`` the
        # second collision row only *suggests* ``<base>-2`` for diagnostics.
        # A later row whose canonical doc_id is legitimately ``<base>-2``
        # must remain free to claim it instead of being flagged as a
        # spurious duplicate.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files_dir = root / "files"
            files_dir.mkdir()
            for name in ("a.pdf", "b.pdf", "c.pdf"):
                (files_dir / name).write_bytes(b"%PDF-1.4\n")
            csv_path = root / "data_list.csv"
            _write_csv(
                csv_path,
                rows=[
                    _row(
                        **{
                            "공고 번호": "20240001",
                            "공고 차수": "0",
                            "사업명": "원본",
                            "발주 기관": "기관 A",
                            "파일형식": "pdf",
                            "파일명": "a.pdf",
                            "텍스트": "본문 가",
                        }
                    ),
                    _row(
                        **{
                            "공고 번호": "20240001",
                            "공고 차수": "0",
                            "사업명": "충돌",
                            "발주 기관": "기관 A",
                            "파일형식": "pdf",
                            "파일명": "b.pdf",
                            "텍스트": "본문 나",
                        }
                    ),
                    _row(
                        **{
                            "공고 번호": "20240001-0-2",
                            "공고 차수": "",
                            "사업명": "별개 공고",
                            "발주 기관": "기관 B",
                            "파일형식": "pdf",
                            "파일명": "c.pdf",
                            "텍스트": "본문 다",
                        }
                    ),
                ],
            )

            report = validate_data_list_csv(csv_path, files_dir)
            self.assertEqual(2, report["summary"]["ok_rows"])
            self.assertEqual(1, report["summary"]["failed_rows"])
            self.assertEqual(
                {"duplicate_doc_id": 1},
                report["summary"]["failure_reasons"],
            )
            ok_doc_ids = sorted(
                record["doc_id"]
                for record in report["records"]
                if record["status"] == "ok"
            )
            self.assertEqual(["20240001-0", "20240001-0-2"], ok_doc_ids)

            documents, ingestion_report = load_documents_from_metadata_csv(
                csv_path,
                files_dir,
            )
            indexed_doc_ids = sorted(doc["doc_id"] for doc in documents)
            self.assertEqual(["20240001-0", "20240001-0-2"], indexed_doc_ids)
            self.assertEqual(
                {"duplicate_doc_id": 1},
                ingestion_report["summary"]["failure_reasons"],
            )


class IngestionDuplicateResolutionTest(unittest.TestCase):
    """Issue #52 — auto-suffix policy keeps the second row indexable."""

    def test_suffix_policy_assigns_next_available_doc_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files_dir = root / "files"
            files_dir.mkdir()
            (files_dir / "a.pdf").write_bytes(b"%PDF-1.4\n")
            (files_dir / "b.pdf").write_bytes(b"%PDF-1.4\n")
            csv_path = root / "data_list.csv"
            _write_csv(
                csv_path,
                rows=[
                    _row(
                        **{
                            "공고 번호": "20240001",
                            "공고 차수": "0",
                            "사업명": "원본",
                            "발주 기관": "기관",
                            "파일형식": "pdf",
                            "파일명": "a.pdf",
                            "텍스트": "본문 가",
                        }
                    ),
                    _row(
                        **{
                            "공고 번호": "20240001",
                            "공고 차수": "0",
                            "사업명": "복원",
                            "발주 기관": "기관",
                            "파일형식": "pdf",
                            "파일명": "b.pdf",
                            "텍스트": "본문 나",
                        }
                    ),
                ],
            )

            documents, report = load_documents_from_metadata_csv(
                csv_path,
                files_dir,
                on_duplicate_doc_id="suffix",
            )

            self.assertEqual(2, len(documents))
            self.assertEqual("20240001-0", documents[0]["doc_id"])
            self.assertEqual("20240001-0-2", documents[1]["doc_id"])
            self.assertEqual("suffix", documents[1]["metadata"]["doc_id_resolution"])
            self.assertEqual("20240001-0", documents[1]["metadata"]["doc_id_base"])
            self.assertEqual(
                {"20240001-0": [2, 3]},
                report["summary"]["duplicate_doc_ids"],
            )
            self.assertEqual("suffix", report["summary"]["on_duplicate_doc_id"])
            self.assertEqual({}, report["summary"]["failure_reasons"])


if __name__ == "__main__":
    unittest.main()
