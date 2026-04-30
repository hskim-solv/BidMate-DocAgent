#!/usr/bin/env python3
"""CSV-backed PDF/HWP ingestion for private RFP experiments.

The v1 loader uses the extracted text already present in data_list.csv. It
still validates the referenced PDF/HWP files so missing source data is visible
in the ingestion report.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any
import unicodedata

SUPPORTED_FILE_FORMATS = {"pdf", "hwp"}

REQUIRED_COLUMNS = [
    "공고 번호",
    "사업명",
    "발주 기관",
    "파일형식",
    "파일명",
    "텍스트",
]


@dataclass(frozen=True)
class IngestionRecord:
    row_number: int
    status: str
    doc_id: str | None
    file_name: str
    file_format: str
    source_path: str
    reason: str | None = None


class CsvTextDocumentLoader:
    file_format = ""

    def load_text(self, row: dict[str, str], source_path: Path) -> str:
        text = normalize_body_text(row.get("텍스트", ""))
        if not text:
            raise ValueError("empty_text")
        return text


class PdfCsvTextLoader(CsvTextDocumentLoader):
    file_format = "pdf"


class HwpCsvTextLoader(CsvTextDocumentLoader):
    file_format = "hwp"


LOADERS: dict[str, CsvTextDocumentLoader] = {
    "pdf": PdfCsvTextLoader(),
    "hwp": HwpCsvTextLoader(),
}


def load_documents_from_metadata_csv(
    metadata_csv: Path,
    files_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not metadata_csv.exists():
        raise ValueError(f"--metadata_csv does not exist: {metadata_csv}")
    if not metadata_csv.is_file():
        raise ValueError(f"--metadata_csv must be a file: {metadata_csv}")
    if not files_dir.exists():
        raise ValueError(f"--files_dir does not exist: {files_dir}")
    if not files_dir.is_dir():
        raise ValueError(f"--files_dir must be a directory: {files_dir}")

    documents: list[dict[str, Any]] = []
    records: list[IngestionRecord] = []
    seen_doc_ids: set[str] = set()

    with metadata_csv.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        validate_fieldnames(reader.fieldnames or [], metadata_csv)
        for row_number, row in enumerate(reader, start=2):
            document, record = normalize_ingestion_row(row, row_number, files_dir, seen_doc_ids)
            records.append(record)
            if document is not None:
                documents.append(document)
                seen_doc_ids.add(document["doc_id"])

    if not documents:
        failure_reasons = sorted({record.reason or record.status for record in records})
        raise ValueError(
            "No PDF/HWP documents could be ingested from "
            f"{metadata_csv}. Failure reasons: {', '.join(failure_reasons) or 'none'}"
        )

    report = {
        "metadata_csv": str(metadata_csv),
        "files_dir": str(files_dir),
        "summary": {
            "total_rows": len(records),
            "indexed_documents": len(documents),
            "failed_rows": sum(1 for record in records if record.status == "failed"),
        },
        "records": [asdict(record) for record in records],
    }
    return documents, report


def validate_fieldnames(fieldnames: list[str], metadata_csv: Path) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(
            f"{metadata_csv} is missing required columns: {', '.join(missing)}"
        )


def normalize_ingestion_row(
    row: dict[str, str],
    row_number: int,
    files_dir: Path,
    seen_doc_ids: set[str],
) -> tuple[dict[str, Any] | None, IngestionRecord]:
    notice_id = clean_cell(row.get("공고 번호"))
    notice_round = clean_cell(row.get("공고 차수"))
    file_name = clean_cell(row.get("파일명"))
    file_format = normalize_file_format(row.get("파일형식"), file_name)
    source_path = find_source_file(files_dir, file_name) if file_name else files_dir
    doc_id = make_doc_id(notice_id, notice_round) if notice_id else make_doc_id_from_file_name(file_name)

    failure_reason = validate_row_basics(
        doc_id=doc_id,
        file_name=file_name,
        file_format=file_format,
        source_path=source_path,
        seen_doc_ids=seen_doc_ids,
    )
    if failure_reason:
        return None, make_record(
            row_number,
            "failed",
            doc_id,
            file_name,
            file_format,
            source_path,
            failure_reason,
        )

    loader = LOADERS[file_format]
    try:
        text = loader.load_text(row, source_path)
    except ValueError as exc:
        return None, make_record(
            row_number,
            "failed",
            doc_id,
            file_name,
            file_format,
            source_path,
            str(exc),
        )

    metadata = normalize_metadata(row, file_format, file_name)
    document = {
        "doc_id": doc_id,
        "title": clean_cell(row.get("사업명")) or Path(file_name).stem,
        "agency": clean_cell(row.get("발주 기관")),
        "project": clean_cell(row.get("사업명")),
        "metadata": metadata,
        "sections": [{"heading": "본문", "text": text}],
        "source_path": str(source_path),
    }
    return document, make_record(
        row_number,
        "indexed",
        doc_id,
        file_name,
        file_format,
        source_path,
    )


def validate_row_basics(
    doc_id: str | None,
    file_name: str,
    file_format: str,
    source_path: Path,
    seen_doc_ids: set[str],
) -> str | None:
    if not file_name:
        return "missing_file_name"
    if not doc_id:
        return "missing_doc_id"
    if doc_id in seen_doc_ids:
        return "duplicate_doc_id"
    if file_format not in SUPPORTED_FILE_FORMATS:
        return "unsupported_file_format"
    if not source_path.exists() or not source_path.is_file():
        return "missing_file"
    return None


def make_record(
    row_number: int,
    status: str,
    doc_id: str | None,
    file_name: str,
    file_format: str,
    source_path: Path,
    reason: str | None = None,
) -> IngestionRecord:
    return IngestionRecord(
        row_number=row_number,
        status=status,
        doc_id=doc_id,
        file_name=file_name,
        file_format=file_format,
        source_path=str(source_path),
        reason=reason,
    )


def normalize_metadata(row: dict[str, str], file_format: str, file_name: str) -> dict[str, Any]:
    return {
        "notice_id": clean_cell(row.get("공고 번호")),
        "notice_round": clean_cell(row.get("공고 차수")),
        "project": clean_cell(row.get("사업명")),
        "budget": parse_budget(row.get("사업 금액")),
        "agency": clean_cell(row.get("발주 기관")),
        "published_at": clean_cell(row.get("공개 일자")),
        "bid_start_at": clean_cell(row.get("입찰 참여 시작일")),
        "bid_deadline_at": clean_cell(row.get("입찰 참여 마감일")),
        "summary": clean_cell(row.get("사업 요약")),
        "file_format": file_format,
        "file_name": file_name,
        "doc_id_source": "notice_id" if clean_cell(row.get("공고 번호")) else "file_name",
        "document_type": "private_pdf_hwp_csv_text",
        "text_source": "data_list_csv_text",
    }


def normalize_file_format(value: str | None, file_name: str) -> str:
    raw_format = clean_cell(value).lower().lstrip(".")
    if raw_format:
        return raw_format
    return Path(file_name).suffix.lower().lstrip(".")


def find_source_file(files_dir: Path, file_name: str) -> Path:
    candidate = files_dir / file_name
    if candidate.exists():
        return candidate

    normalized_name = unicodedata.normalize("NFC", file_name)
    for path in files_dir.iterdir():
        if unicodedata.normalize("NFC", path.name) == normalized_name:
            return path
    return candidate


def make_doc_id(notice_id: str, notice_round: str) -> str:
    parts = [notice_id]
    if notice_round:
        parts.append(notice_round)
    return "-".join(slug_part(part) for part in parts if part)


def make_doc_id_from_file_name(file_name: str) -> str | None:
    if not file_name:
        return None
    return slug_part(Path(file_name).stem)


def slug_part(value: str) -> str:
    return re.sub(r"\s+", "-", value.strip())


def parse_budget(value: str | None) -> int | float | str | None:
    cleaned = clean_cell(value).replace(",", "")
    if not cleaned:
        return None
    try:
        parsed = float(cleaned)
    except ValueError:
        return clean_cell(value)
    if parsed.is_integer():
        return int(parsed)
    return parsed


def clean_cell(value: str | None) -> str:
    return str(value or "").strip()


def normalize_body_text(value: str | None) -> str:
    return clean_cell(value).replace("\r\n", "\n").replace("\r", "\n")
