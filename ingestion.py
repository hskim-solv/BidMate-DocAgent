#!/usr/bin/env python3
"""CSV-backed PDF/HWP ingestion for private RFP experiments.

The v1 loader uses the extracted text already present in data_list.csv. It
still validates the referenced PDF/HWP files so missing source data is visible
in the ingestion report.
"""

from __future__ import annotations

import csv
import os
import warnings
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any
import unicodedata

from rag_metadata_extraction import extract_rfp_metadata

SUPPORTED_FILE_FORMATS = {"pdf", "hwp"}

REQUIRED_COLUMNS = [
    "공고 번호",
    "사업명",
    "발주 기관",
    "파일형식",
    "파일명",
    "텍스트",
]

INGESTION_REPORT_SCHEMA_VERSION = 2

# Public, reviewer-facing failure taxonomy for ingestion. Keep keys stable;
# downstream tooling (eval/run_eval.py, docs, dashboards) reads them.
FAILURE_TAXONOMY: dict[str, dict[str, str]] = {
    "missing_file_name": {
        "stage": "row",
        "downstream_risk": "Row cannot be matched to any source file.",
    },
    "missing_doc_id": {
        "stage": "row",
        "downstream_risk": "Row produces no stable identifier; eval cannot reference it.",
    },
    "duplicate_doc_id": {
        "stage": "row",
        "downstream_risk": "Two rows would collide in the index; later row is dropped.",
    },
    "unsupported_file_format": {
        "stage": "row",
        "downstream_risk": "PDF/HWP path is the only supported v1 format.",
    },
    "missing_file": {
        "stage": "filesystem",
        "downstream_risk": "Source file is referenced but not present on disk.",
    },
    "empty_text": {
        "stage": "text",
        "downstream_risk": "CSV has no body text for this row; nothing to chunk or embed.",
    },
}


@dataclass(frozen=True)
class IngestionRecord:
    row_number: int
    status: str
    doc_id: str | None
    file_name: str
    file_format: str
    source_path: str
    reason: str | None = None
    duplicate_resolution: dict[str, Any] | None = None
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    field: str
    message: str
    row_number: int | None = None


@dataclass
class _DuplicateTracker:
    seen: dict[str, int] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)


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


class HwpNativeLoader(CsvTextDocumentLoader):
    """Opt-in HWP loader that parses the binary natively via pyhwp.

    Spike scaffolding (issue #167). On any import error, OSError, or runtime
    parse failure, falls back to the CSV ``텍스트`` column so the baseline
    ingestion contract (ADR 0001) keeps working without pyhwp installed.

    Diagnostics (issue #363): ``last_text_source`` records which source the
    final text came from; ``last_fallback_reason`` records ``"ExceptionName:
    truncated message"`` when fallback fires (``None`` otherwise). Because
    this loader is only constructed when the user opts in via
    ``BIDMATE_HWP_LOADER=native`` (see ``_resolve_loader``), every fallback
    here also emits a ``RuntimeWarning`` so the silent path is visible in
    real-data eval logs.
    """

    file_format = "hwp"

    def __init__(self) -> None:
        self.last_text_source = "data_list_csv_text"
        self.last_fallback_reason: str | None = None

    def load_text(self, row: dict[str, str], source_path: Path) -> str:
        self.last_text_source = "data_list_csv_text"
        self.last_fallback_reason = None
        try:
            native_text = _extract_hwp_native(source_path)
        except (ImportError, OSError, RuntimeError) as exc:
            native_text = None
            reason = f"{type(exc).__name__}: {str(exc)[:120]}"
            self.last_fallback_reason = reason
            warnings.warn(
                f"HwpNativeLoader fallback to CSV text: {reason}",
                RuntimeWarning,
                stacklevel=2,
            )
        if native_text:
            self.last_text_source = "hwp_native"
            return native_text
        text = normalize_body_text(row.get("텍스트", ""))
        if not text:
            raise ValueError("empty_text")
        return text


def _extract_hwp_native(source_path: Path) -> str | None:
    """Extract body text from an HWP file using pyhwp's Hwp5File API.

    Returns ``None`` if parsing succeeds but yields no normalized text.
    Raises ``ImportError`` if pyhwp is unavailable; other exceptions
    (``OSError``, ``RuntimeError``) propagate to the caller for fallback.
    """
    from hwp5.xmlmodel import Hwp5File  # type: ignore[import-not-found]

    hwp = Hwp5File(str(source_path))
    parts: list[str] = []
    for section in hwp.bodytext.section_list():
        for paragraph in section.paragraphs:
            for chunk in paragraph.text_chunks:
                parts.append(chunk.text)
    text = normalize_body_text("\n".join(parts))
    return text or None


LOADERS: dict[str, CsvTextDocumentLoader] = {
    "pdf": PdfCsvTextLoader(),
    "hwp": HwpCsvTextLoader(),
}


def _resolve_loader(file_format: str) -> CsvTextDocumentLoader:
    """Pick the loader for ``file_format``.

    For HWP, respect the ``BIDMATE_HWP_LOADER=native`` opt-in (spike, #167);
    everything else falls through to the registered default.
    """
    if (
        file_format == "hwp"
        and os.environ.get("BIDMATE_HWP_LOADER", "").strip().lower() == "native"
    ):
        return HwpNativeLoader()
    return LOADERS[file_format]


def load_documents_from_metadata_csv(
    metadata_csv: Path,
    files_dir: Path,
    *,
    on_duplicate_doc_id: str = "fail",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if on_duplicate_doc_id not in {"fail", "suffix"}:
        raise ValueError(
            "on_duplicate_doc_id must be 'fail' or 'suffix'; got: "
            f"{on_duplicate_doc_id}"
        )
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
    tracker = _DuplicateTracker()

    with metadata_csv.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        validate_fieldnames(reader.fieldnames or [], metadata_csv)
        for row_number, row in enumerate(reader, start=2):
            document, record = normalize_ingestion_row(
                row,
                row_number,
                files_dir,
                tracker,
                on_duplicate_doc_id=on_duplicate_doc_id,
            )
            records.append(record)
            if document is not None:
                documents.append(document)

    if not documents:
        failure_reasons = sorted({record.reason or record.status for record in records})
        raise ValueError(
            "No PDF/HWP documents could be ingested from "
            f"{metadata_csv}. Failure reasons: {', '.join(failure_reasons) or 'none'}"
        )

    report = build_ingestion_report(
        metadata_csv=metadata_csv,
        files_dir=files_dir,
        records=records,
        indexed_count=len(documents),
        on_duplicate_doc_id=on_duplicate_doc_id,
    )
    return documents, report


def validate_fieldnames(fieldnames: list[str], metadata_csv: Path) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(
            f"{metadata_csv} is missing required columns: {', '.join(missing)}"
        )


@dataclass
class _RowValidation:
    """Row-level resolution result shared by ingestion + audit paths."""

    file_name: str
    file_format: str
    source_path: Path
    doc_id: str
    base_doc_id: str
    failure_reason: str | None
    duplicate_resolution: dict[str, Any] | None
    # True when this row reserved a fresh slot in the tracker (no
    # duplicate collision and validation passed up to that point).
    # Callers use this to gate post-resolution checks like ``empty_text``.
    tracker_registered: bool


def _resolve_row_validation(
    row: dict[str, str],
    row_number: int,
    files_dir: Path,
    tracker: _DuplicateTracker,
    *,
    on_duplicate_doc_id: str = "fail",
) -> _RowValidation:
    """Run the shared row-identity + duplicate-resolution validation chain.

    Used by ``normalize_ingestion_row`` (which then loads the body text)
    and ``audit_metadata_row`` (which then checks for blank body text).
    Mutates ``tracker`` in place: a fresh row is recorded; a suffix
    collision reserves the next unique id.
    """
    notice_id = clean_cell(row.get("공고 번호"))
    notice_round = clean_cell(row.get("공고 차수"))
    file_name = clean_cell(row.get("파일명"))
    file_format = normalize_file_format(row.get("파일형식"), file_name)
    source_path = find_source_file(files_dir, file_name) if file_name else files_dir
    base_doc_id = canonical_doc_id(notice_id, notice_round, file_name)

    duplicate_resolution: dict[str, Any] | None = None
    failure_reason: str | None = None
    doc_id = base_doc_id
    tracker_registered = False

    if not file_name:
        failure_reason = "missing_file_name"
    elif not doc_id:
        failure_reason = "missing_doc_id"
    elif file_format not in SUPPORTED_FILE_FORMATS:
        failure_reason = "unsupported_file_format"
    elif not source_path.exists() or not source_path.is_file():
        failure_reason = "missing_file"
    else:
        existing_row = tracker.seen.get(base_doc_id)
        if existing_row is not None:
            if on_duplicate_doc_id == "suffix":
                suggested = reserve_next_unique_doc_id(base_doc_id, tracker)
                doc_id = suggested
                duplicate_resolution = {
                    "policy": "suffix",
                    "base_doc_id": base_doc_id,
                    "first_seen_row": existing_row,
                    "assigned_doc_id": suggested,
                }
            else:
                # Read-only peek: do not reserve the suggested id, otherwise
                # a later row whose canonical doc_id is legitimately
                # <base>-N would be falsely flagged as a duplicate.
                suggested = peek_next_unique_doc_id(base_doc_id, tracker)
                failure_reason = "duplicate_doc_id"
                duplicate_resolution = {
                    "policy": "fail",
                    "base_doc_id": base_doc_id,
                    "first_seen_row": existing_row,
                    "suggested_doc_id": suggested,
                }
        else:
            tracker.seen[base_doc_id] = row_number
            tracker.counts[base_doc_id] = 1
            tracker_registered = True

    return _RowValidation(
        file_name=file_name,
        file_format=file_format,
        source_path=source_path,
        doc_id=doc_id,
        base_doc_id=base_doc_id,
        failure_reason=failure_reason,
        duplicate_resolution=duplicate_resolution,
        tracker_registered=tracker_registered,
    )


def normalize_ingestion_row(
    row: dict[str, str],
    row_number: int,
    files_dir: Path,
    tracker: _DuplicateTracker,
    *,
    on_duplicate_doc_id: str = "fail",
) -> tuple[dict[str, Any] | None, IngestionRecord]:
    validation = _resolve_row_validation(
        row, row_number, files_dir, tracker, on_duplicate_doc_id=on_duplicate_doc_id
    )

    if validation.failure_reason:
        return None, make_record(
            row_number,
            "failed",
            validation.doc_id,
            validation.file_name,
            validation.file_format,
            validation.source_path,
            validation.failure_reason,
            duplicate_resolution=validation.duplicate_resolution,
        )

    loader = _resolve_loader(validation.file_format)
    try:
        text = loader.load_text(row, validation.source_path)
    except ValueError as exc:
        return None, make_record(
            row_number,
            "failed",
            validation.doc_id,
            validation.file_name,
            validation.file_format,
            validation.source_path,
            str(exc),
            duplicate_resolution=validation.duplicate_resolution,
        )

    text_source = getattr(loader, "last_text_source", "data_list_csv_text")
    metadata = normalize_metadata(
        row, validation.file_format, validation.file_name, text_source=text_source
    )
    metadata["doc_id"] = validation.doc_id
    if validation.duplicate_resolution and on_duplicate_doc_id == "suffix":
        metadata["doc_id_resolution"] = validation.duplicate_resolution["policy"]
        metadata["doc_id_base"] = validation.duplicate_resolution["base_doc_id"]
    document = {
        "doc_id": validation.doc_id,
        "title": clean_cell(row.get("사업명")) or Path(validation.file_name).stem,
        "agency": clean_cell(row.get("발주 기관")),
        "project": clean_cell(row.get("사업명")),
        "metadata": metadata,
        "sections": [{"heading": "본문", "text": text}],
        "source_path": str(validation.source_path),
    }
    # Issue #180 wire-up: write the eight-field structured extraction
    # into ``metadata["extracted"]`` as an *additive* sidecar. The
    # regex backend is the default (ADR 0001 invariant), so this stays
    # deterministic and offline unless ``BIDMATE_METADATA_BACKEND`` is
    # flipped to ``anthropic_tool_use`` / ``openai_function_call``.
    # Top-level ``agency`` / ``project`` are intentionally untouched —
    # downstream chunk metadata propagation in rag_core.py and the
    # answer/citation contract (ADR 0003) read those fields.
    document["metadata"]["extracted"] = extract_rfp_metadata(document).as_dict()
    return document, make_record(
        row_number,
        "indexed",
        validation.doc_id,
        validation.file_name,
        validation.file_format,
        validation.source_path,
        duplicate_resolution=validation.duplicate_resolution,
    )


def make_record(
    row_number: int,
    status: str,
    doc_id: str | None,
    file_name: str,
    file_format: str,
    source_path: Path,
    reason: str | None = None,
    *,
    duplicate_resolution: dict[str, Any] | None = None,
    messages: tuple[str, ...] = (),
) -> IngestionRecord:
    return IngestionRecord(
        row_number=row_number,
        status=status,
        doc_id=doc_id,
        file_name=file_name,
        file_format=file_format,
        source_path=str(source_path),
        reason=reason,
        duplicate_resolution=duplicate_resolution,
        messages=messages,
    )


def normalize_metadata(
    row: dict[str, str],
    file_format: str,
    file_name: str,
    *,
    text_source: str = "data_list_csv_text",
) -> dict[str, Any]:
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
        "text_source": text_source,
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


def canonical_doc_id(
    notice_id: str | None,
    notice_round: str | None,
    file_name: str | None,
) -> str | None:
    """Single canonical doc_id rule used across ingestion paths.

    Priority:
      1. ``notice_id`` (+ optional ``notice_round``) if non-empty.
      2. File-name stem fallback.
    Both branches NFC-normalize, casefold, and collapse whitespace so the
    same source row produces the same id across runs and platforms.
    """
    notice = clean_cell(notice_id)
    if notice:
        return make_doc_id(notice, clean_cell(notice_round))
    return make_doc_id_from_file_name(clean_cell(file_name or ""))


def make_doc_id(notice_id: str, notice_round: str) -> str:
    parts = [notice_id]
    if notice_round:
        parts.append(notice_round)
    slugged = [slug_part(part) for part in parts if slug_part(part)]
    return "-".join(slugged)


def make_doc_id_from_file_name(file_name: str) -> str | None:
    if not file_name:
        return None
    stem = Path(file_name).stem
    slug = slug_part(stem)
    return slug or None


def slug_part(value: str) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFC", value).strip()
    normalized = re.sub(r"\s+", "-", normalized)
    return normalized


def _compute_next_unique_doc_id(
    base_doc_id: str,
    tracker: _DuplicateTracker,
) -> tuple[str, int]:
    count = tracker.counts.get(base_doc_id, 1) + 1
    candidate = f"{base_doc_id}-{count}"
    while candidate in tracker.seen:
        count += 1
        candidate = f"{base_doc_id}-{count}"
    return candidate, count


def peek_next_unique_doc_id(base_doc_id: str, tracker: _DuplicateTracker) -> str:
    """Compute the next available ``<base>-N`` id without mutating ``tracker``.

    Used when ``on_duplicate_doc_id="fail"`` so the failure record can carry a
    ``suggested_doc_id`` for diagnostics without reserving an id that no row
    will ever take. A later row whose canonical doc_id is legitimately
    ``<base>-N`` must remain free to claim it.
    """
    candidate, _ = _compute_next_unique_doc_id(base_doc_id, tracker)
    return candidate


def reserve_next_unique_doc_id(base_doc_id: str, tracker: _DuplicateTracker) -> str:
    """Compute and reserve the next ``<base>-N`` id; mutates ``tracker``.

    Used when ``on_duplicate_doc_id="suffix"`` to actually take the id for the
    duplicate row.
    """
    candidate, count = _compute_next_unique_doc_id(base_doc_id, tracker)
    tracker.seen[candidate] = tracker.seen.get(base_doc_id, 0)
    tracker.counts[base_doc_id] = count
    return candidate


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


def build_ingestion_report(
    *,
    metadata_csv: Path,
    files_dir: Path,
    records: list[IngestionRecord],
    indexed_count: int,
    on_duplicate_doc_id: str,
) -> dict[str, Any]:
    """Build the canonical ingestion_report.json payload."""
    failure_reasons: dict[str, int] = OrderedDict()
    failure_examples: dict[str, list[dict[str, Any]]] = OrderedDict()
    doc_id_sources: dict[str, int] = OrderedDict()
    file_formats: dict[str, int] = OrderedDict()
    duplicate_groups: dict[str, list[int]] = OrderedDict()

    for record in records:
        if record.reason:
            failure_reasons[record.reason] = failure_reasons.get(record.reason, 0) + 1
            examples = failure_examples.setdefault(record.reason, [])
            if len(examples) < 3:
                examples.append(
                    {
                        "row_number": record.row_number,
                        "doc_id": record.doc_id,
                        "file_name": record.file_name,
                        "file_format": record.file_format,
                    }
                )
        fmt = record.file_format or "unknown"
        file_formats[fmt] = file_formats.get(fmt, 0) + 1
        if record.status == "indexed":
            source = "notice_id" if _looks_like_notice_id_doc(record) else "file_name"
            doc_id_sources[source] = doc_id_sources.get(source, 0) + 1
        _accumulate_duplicate_group(duplicate_groups, record)

    summary = {
        "schema_version": INGESTION_REPORT_SCHEMA_VERSION,
        "total_rows": len(records),
        "indexed_documents": indexed_count,
        "failed_rows": sum(1 for record in records if record.status == "failed"),
        "failure_reasons": dict(failure_reasons),
        "failure_examples": {k: v for k, v in failure_examples.items()},
        "doc_id_sources": dict(doc_id_sources),
        "file_formats": dict(file_formats),
        "duplicate_doc_ids": {k: sorted(set(v)) for k, v in duplicate_groups.items()},
        "on_duplicate_doc_id": on_duplicate_doc_id,
    }
    return {
        "metadata_csv": str(metadata_csv),
        "files_dir": str(files_dir),
        "summary": summary,
        "failure_taxonomy": FAILURE_TAXONOMY,
        "records": [_record_to_dict(record) for record in records],
    }


def _accumulate_duplicate_group(
    duplicate_groups: dict[str, list[int]],
    record: IngestionRecord,
) -> None:
    """Add a record to ``duplicate_groups`` keyed by base_doc_id when applicable."""
    if not record.duplicate_resolution:
        return
    base = str(record.duplicate_resolution.get("base_doc_id") or record.doc_id or "")
    if not base:
        return
    duplicate_groups.setdefault(base, [])
    duplicate_groups[base].append(record.row_number)
    first_seen = record.duplicate_resolution.get("first_seen_row")
    if isinstance(first_seen, int) and first_seen not in duplicate_groups[base]:
        duplicate_groups[base].append(first_seen)


def _looks_like_notice_id_doc(record: IngestionRecord) -> bool:
    if not record.doc_id or not record.file_name:
        return True
    stem_slug = slug_part(Path(record.file_name).stem)
    return record.doc_id != stem_slug


def _record_to_dict(record: IngestionRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["messages"] = list(record.messages)
    if record.duplicate_resolution is None:
        payload.pop("duplicate_resolution", None)
    return payload


def validate_data_list_csv(
    metadata_csv: Path,
    files_dir: Path,
    *,
    on_duplicate_doc_id: str = "fail",
) -> dict[str, Any]:
    """Lightweight schema/audit pass over data_list.csv.

    Mirrors the per-row checks of :func:`load_documents_from_metadata_csv`
    but does not load body text or build documents. Returns a report
    structurally compatible with ``ingestion_report.json``.
    """
    if on_duplicate_doc_id not in {"fail", "suffix"}:
        raise ValueError(
            "on_duplicate_doc_id must be 'fail' or 'suffix'; got: "
            f"{on_duplicate_doc_id}"
        )
    if not metadata_csv.exists():
        raise ValueError(f"metadata_csv does not exist: {metadata_csv}")
    if not metadata_csv.is_file():
        raise ValueError(f"metadata_csv must be a file: {metadata_csv}")
    if not files_dir.exists():
        raise ValueError(f"files_dir does not exist: {files_dir}")
    if not files_dir.is_dir():
        raise ValueError(f"files_dir must be a directory: {files_dir}")

    schema_issues: list[ValidationIssue] = []
    records: list[IngestionRecord] = []
    tracker = _DuplicateTracker()

    with metadata_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        for column in missing:
            schema_issues.append(
                ValidationIssue(
                    code="missing_required_column",
                    field=column,
                    message=f"required column missing: {column}",
                )
            )
        if missing:
            return _build_validation_report(
                metadata_csv=metadata_csv,
                files_dir=files_dir,
                records=records,
                schema_issues=schema_issues,
                on_duplicate_doc_id=on_duplicate_doc_id,
            )
        for row_number, row in enumerate(reader, start=2):
            record = audit_metadata_row(
                row,
                row_number,
                files_dir,
                tracker,
                on_duplicate_doc_id=on_duplicate_doc_id,
            )
            records.append(record)

    return _build_validation_report(
        metadata_csv=metadata_csv,
        files_dir=files_dir,
        records=records,
        schema_issues=schema_issues,
        on_duplicate_doc_id=on_duplicate_doc_id,
    )


def audit_metadata_row(
    row: dict[str, str],
    row_number: int,
    files_dir: Path,
    tracker: _DuplicateTracker,
    *,
    on_duplicate_doc_id: str = "fail",
) -> IngestionRecord:
    # Track non-fatal warnings on fields ingestion accepts but downstream
    # eval often relies on. Blank body text is NOT a warning: the ingestion
    # path raises ``empty_text`` for that row, and the validator must
    # report the same failure so a clean validator exit code can be trusted.
    messages: list[str] = []
    if not clean_cell(row.get("발주 기관")):
        messages.append("blank_agency")
    if not clean_cell(row.get("사업명")):
        messages.append("blank_project")

    validation = _resolve_row_validation(
        row, row_number, files_dir, tracker, on_duplicate_doc_id=on_duplicate_doc_id
    )

    # audit-only: after a clean tracker registration, a blank body text
    # surfaces as ``empty_text`` so a clean validator exit code mirrors
    # the ingestion path's runtime failure for the same row.
    if (
        validation.tracker_registered
        and validation.failure_reason is None
        and not clean_cell(row.get("텍스트"))
    ):
        validation.failure_reason = "empty_text"

    return make_record(
        row_number,
        "failed" if validation.failure_reason else "ok",
        validation.doc_id,
        validation.file_name,
        validation.file_format,
        validation.source_path,
        validation.failure_reason,
        duplicate_resolution=validation.duplicate_resolution,
        messages=tuple(messages),
    )


def _build_validation_report(
    *,
    metadata_csv: Path,
    files_dir: Path,
    records: list[IngestionRecord],
    schema_issues: list[ValidationIssue],
    on_duplicate_doc_id: str,
) -> dict[str, Any]:
    failure_reasons: dict[str, int] = OrderedDict()
    failure_examples: dict[str, list[dict[str, Any]]] = OrderedDict()
    file_formats: dict[str, int] = OrderedDict()
    duplicate_groups: dict[str, list[int]] = OrderedDict()
    blank_field_counts: dict[str, int] = OrderedDict()

    for record in records:
        if record.reason:
            failure_reasons[record.reason] = failure_reasons.get(record.reason, 0) + 1
            examples = failure_examples.setdefault(record.reason, [])
            if len(examples) < 3:
                examples.append(
                    {
                        "row_number": record.row_number,
                        "doc_id": record.doc_id,
                        "file_name": record.file_name,
                        "file_format": record.file_format,
                    }
                )
        fmt = record.file_format or "unknown"
        file_formats[fmt] = file_formats.get(fmt, 0) + 1
        for message in record.messages:
            blank_field_counts[message] = blank_field_counts.get(message, 0) + 1
        _accumulate_duplicate_group(duplicate_groups, record)

    ok_count = sum(1 for record in records if record.status == "ok")
    failed_count = sum(1 for record in records if record.status == "failed")
    schema_ok = not schema_issues
    summary = {
        "schema_version": INGESTION_REPORT_SCHEMA_VERSION,
        "schema_ok": schema_ok,
        "total_rows": len(records),
        "ok_rows": ok_count,
        "failed_rows": failed_count,
        "failure_reasons": dict(failure_reasons),
        "failure_examples": {k: v for k, v in failure_examples.items()},
        "blank_field_warnings": dict(blank_field_counts),
        "file_formats": dict(file_formats),
        "duplicate_doc_ids": {k: sorted(set(v)) for k, v in duplicate_groups.items()},
        "on_duplicate_doc_id": on_duplicate_doc_id,
    }
    return {
        "mode": "validation",
        "metadata_csv": str(metadata_csv),
        "files_dir": str(files_dir),
        "summary": summary,
        "schema_issues": [asdict(issue) for issue in schema_issues],
        "failure_taxonomy": FAILURE_TAXONOMY,
        "records": [_record_to_dict(record) for record in records],
    }
