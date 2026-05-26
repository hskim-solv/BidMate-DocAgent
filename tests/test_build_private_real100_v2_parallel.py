from __future__ import annotations

import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingestion import IngestionRecord  # noqa: E402
from scripts.build_private_real100_v2_parallel import (  # noqa: E402
    _row_fingerprint,
    _write_checkpoint,
    parallel_load_documents_from_metadata_csv,
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


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            full = {field: "" for field in FIELDNAMES}
            full.update(row)
            writer.writerow(full)


def test_parallel_loader_preserves_ingestion_report_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIDMATE_HWP_LOADER", "csv_text")
    monkeypatch.setenv("BIDMATE_PDF_LOADER", "csv_text")
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    (files_dir / "a.pdf").write_text("placeholder", encoding="utf-8")
    (files_dir / "b.hwp").write_text("placeholder", encoding="utf-8")
    metadata_csv = tmp_path / "data_list.csv"
    _write_csv(
        metadata_csv,
        [
            {
                "공고 번호": "P-001",
                "사업명": "첫 번째 RFP",
                "발주 기관": "기관 A",
                "파일형식": "pdf",
                "파일명": "a.pdf",
                "텍스트": "첫 번째 문서 본문",
            },
            {
                "공고 번호": "P-002",
                "사업명": "두 번째 RFP",
                "발주 기관": "기관 B",
                "파일형식": "hwp",
                "파일명": "b.hwp",
                "텍스트": "두 번째 문서 본문",
            },
        ],
    )

    documents, report = parallel_load_documents_from_metadata_csv(metadata_csv, files_dir, workers=2)

    assert [doc["doc_id"] for doc in documents] == ["P-001", "P-002"]
    assert report["summary"]["total_rows"] == 2
    assert report["summary"]["indexed_documents"] == 2
    assert report["summary"]["failed_rows"] == 0
    assert report["summary"]["text_source_counts"] == {
        "pdf": {"data_list_csv_text": 1},
        "hwp": {"data_list_csv_text": 1},
    }


def test_parallel_loader_reuses_private_row_checkpoints(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIDMATE_PDF_LOADER", "csv_text")
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    (files_dir / "cached.pdf").write_text("placeholder", encoding="utf-8")
    metadata_csv = tmp_path / "data_list.csv"
    row = {
        "공고 번호": "P-001",
        "사업명": "Cached RFP",
        "발주 기관": "Agency",
        "파일형식": "pdf",
        "파일명": "cached.pdf",
        "텍스트": "",
    }
    _write_csv(metadata_csv, [row])
    checkpoint_dir = tmp_path / "checkpoints"
    document = {
        "doc_id": "P-001",
        "text": "cached parsed markdown",
        "metadata": {"file_format": "pdf"},
    }
    record = IngestionRecord(
        row_number=2,
        status="indexed",
        doc_id="P-001",
        file_name="cached.pdf",
        file_format="pdf",
        source_path=str(files_dir / "cached.pdf"),
        text_source="pdf_pymupdf4llm",
    )
    full_row = {field: "" for field in FIELDNAMES}
    full_row.update(row)
    _write_checkpoint(checkpoint_dir, 2, _row_fingerprint(full_row), document, record)

    documents, report = parallel_load_documents_from_metadata_csv(
        metadata_csv,
        files_dir,
        workers=2,
        checkpoint_dir=checkpoint_dir,
    )

    assert documents == [document]
    assert report["summary"]["indexed_documents"] == 1
    assert report["summary"]["failed_rows"] == 0
    assert report["summary"]["text_source_counts"] == {"pdf": {"pdf_pymupdf4llm": 1}}
