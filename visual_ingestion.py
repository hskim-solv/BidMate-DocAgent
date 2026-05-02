#!/usr/bin/env python3
"""Visual parsing v2 ingestion for PDF/image RFP sources.

The parser emits structured artifacts with page/block/region metadata and
normalizes those artifacts into the existing RAG document shape. Heavy parser
dependencies are imported lazily so the public CSV/text baseline keeps running
in minimal environments.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable

from ingestion import (
    clean_cell,
    find_source_file,
    make_doc_id,
    make_doc_id_from_file_name,
    normalize_body_text,
    normalize_file_format,
    normalize_metadata,
    validate_fieldnames,
)

VISUAL_SCHEMA_VERSION = 2
PDF_MIN_TEXT_CHARS_FOR_OCR = 24
SUPPORTED_IMAGE_FORMATS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}
SUPPORTED_VISUAL_FORMATS = {"pdf", *SUPPORTED_IMAGE_FORMATS}
VISUAL_METADATA_FORMATS = { *SUPPORTED_VISUAL_FORMATS, "hwp" }

OcrProvider = Callable[[Any], str | list[dict[str, Any]]]


class OcrUnavailable(RuntimeError):
    """Raised when an OCR provider cannot be loaded or executed."""


@dataclass(frozen=True)
class VisualIngestionRecord:
    row_number: int | None
    status: str
    doc_id: str | None
    file_name: str
    file_format: str
    source_path: str
    artifact_path: str | None = None
    reason: str | None = None


def load_visual_documents_from_dir(
    input_dir: Path,
    artifact_dir: Path,
    ocr_provider: OcrProvider | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not input_dir.exists():
        raise ValueError(f"--visual_input_dir does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise ValueError(f"--visual_input_dir must be a directory: {input_dir}")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    documents: list[dict[str, Any]] = []
    records: list[VisualIngestionRecord] = []

    files = sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and normalize_file_format("", path.name) in SUPPORTED_VISUAL_FORMATS
    )
    for source_path in files:
        doc_id = make_doc_id_from_file_name(source_path.name) or source_path.stem
        metadata = {
            "file_format": normalize_file_format("", source_path.name),
            "file_name": source_path.name,
            "doc_id_source": "file_name",
        }
        document, artifact = parse_visual_document(
            source_path,
            doc_id=doc_id,
            title=source_path.stem,
            metadata=metadata,
            ocr_provider=ocr_provider,
        )
        artifact_path = write_visual_artifact(artifact, artifact_dir)
        if document is not None:
            attach_artifact_path(document, artifact_path)
            documents.append(document)
        records.append(record_from_artifact(artifact, artifact_path, row_number=None))

    if not documents:
        failure_reasons = sorted({record.reason or record.status for record in records})
        raise ValueError(
            "No visual PDF/image documents could be ingested from "
            f"{input_dir}. Failure reasons: {', '.join(failure_reasons) or 'none'}"
        )

    return documents, make_visual_report(
        source={"visual_input_dir": str(input_dir), "visual_artifact_dir": str(artifact_dir)},
        records=records,
    )


def load_visual_documents_from_metadata_csv(
    metadata_csv: Path,
    files_dir: Path,
    artifact_dir: Path,
    ocr_provider: OcrProvider | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not metadata_csv.exists():
        raise ValueError(f"--metadata_csv does not exist: {metadata_csv}")
    if not metadata_csv.is_file():
        raise ValueError(f"--metadata_csv must be a file: {metadata_csv}")
    if not files_dir.exists():
        raise ValueError(f"--files_dir does not exist: {files_dir}")
    if not files_dir.is_dir():
        raise ValueError(f"--files_dir must be a directory: {files_dir}")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    documents: list[dict[str, Any]] = []
    records: list[VisualIngestionRecord] = []
    seen_doc_ids: set[str] = set()

    with metadata_csv.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        validate_fieldnames(reader.fieldnames or [], metadata_csv)
        for row_number, row in enumerate(reader, start=2):
            document, artifact, record = parse_visual_metadata_row(
                row,
                row_number,
                files_dir,
                seen_doc_ids,
                ocr_provider=ocr_provider,
            )
            artifact_path = write_visual_artifact(artifact, artifact_dir)
            record = replace_record_artifact_path(record, artifact_path)
            if document is not None:
                attach_artifact_path(document, artifact_path)
                documents.append(document)
                seen_doc_ids.add(document["doc_id"])
            records.append(record)

    if not documents:
        failure_reasons = sorted({record.reason or record.status for record in records})
        raise ValueError(
            "No visual PDF/image/HWP-fallback documents could be ingested from "
            f"{metadata_csv}. Failure reasons: {', '.join(failure_reasons) or 'none'}"
        )

    return documents, make_visual_report(
        source={
            "metadata_csv": str(metadata_csv),
            "files_dir": str(files_dir),
            "visual_artifact_dir": str(artifact_dir),
        },
        records=records,
    )


def parse_visual_metadata_row(
    row: dict[str, str],
    row_number: int,
    files_dir: Path,
    seen_doc_ids: set[str],
    ocr_provider: OcrProvider | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any], VisualIngestionRecord]:
    notice_id = clean_cell(row.get("공고 번호"))
    notice_round = clean_cell(row.get("공고 차수"))
    file_name = clean_cell(row.get("파일명"))
    file_format = normalize_file_format(row.get("파일형식"), file_name)
    source_path = find_source_file(files_dir, file_name) if file_name else files_dir
    doc_id = make_doc_id(notice_id, notice_round) if notice_id else make_doc_id_from_file_name(file_name)

    failure_reason = validate_visual_row_basics(
        doc_id=doc_id,
        file_name=file_name,
        file_format=file_format,
        source_path=source_path,
        seen_doc_ids=seen_doc_ids,
    )
    if failure_reason:
        artifact = failure_artifact(
            doc_id=doc_id or make_doc_id_from_file_name(file_name) or f"row-{row_number}",
            source_path=source_path,
            file_format=file_format,
            title=clean_cell(row.get("사업명")) or Path(file_name).stem,
            metadata=normalize_metadata(row, file_format, file_name),
            reason=failure_reason,
        )
        return None, artifact, record_from_artifact(artifact, None, row_number=row_number)

    metadata = normalize_metadata(row, file_format, file_name)
    title = clean_cell(row.get("사업명")) or Path(file_name).stem
    agency = clean_cell(row.get("발주 기관"))
    project = clean_cell(row.get("사업명"))

    if file_format == "hwp":
        document, artifact = make_hwp_fallback_document(
            row=row,
            doc_id=doc_id or Path(file_name).stem,
            source_path=source_path,
            file_format=file_format,
            file_name=file_name,
        )
    else:
        document, artifact = parse_visual_document(
            source_path,
            doc_id=doc_id,
            title=title,
            agency=agency,
            project=project,
            metadata=metadata,
            ocr_provider=ocr_provider,
        )
    return document, artifact, record_from_artifact(artifact, None, row_number=row_number)


def validate_visual_row_basics(
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
    if file_format not in VISUAL_METADATA_FORMATS:
        return "unsupported_file_format"
    if not source_path.exists() or not source_path.is_file():
        return "missing_file"
    return None


def parse_visual_document(
    source_path: Path,
    doc_id: str | None = None,
    title: str | None = None,
    agency: str = "",
    project: str = "",
    metadata: dict[str, Any] | None = None,
    ocr_provider: OcrProvider | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    file_format = normalize_file_format("", source_path.name)
    resolved_doc_id = doc_id or make_doc_id_from_file_name(source_path.name) or source_path.stem
    resolved_title = title or source_path.stem
    base_metadata = dict(metadata or {})
    base_metadata.setdefault("file_format", file_format)
    base_metadata.setdefault("file_name", source_path.name)

    if file_format not in SUPPORTED_VISUAL_FORMATS:
        artifact = failure_artifact(
            resolved_doc_id,
            source_path,
            file_format,
            resolved_title,
            base_metadata,
            "unsupported_file_format",
            agency=agency,
            project=project,
        )
        return None, artifact
    if not source_path.exists() or not source_path.is_file():
        artifact = failure_artifact(
            resolved_doc_id,
            source_path,
            file_format,
            resolved_title,
            base_metadata,
            "missing_file",
            agency=agency,
            project=project,
        )
        return None, artifact

    if file_format == "pdf":
        artifact = parse_pdf_artifact(
            source_path,
            resolved_doc_id,
            resolved_title,
            agency,
            project,
            base_metadata,
            ocr_provider,
        )
    else:
        artifact = parse_image_artifact(
            source_path,
            resolved_doc_id,
            resolved_title,
            agency,
            project,
            base_metadata,
            ocr_provider,
        )

    finalize_visual_artifact(artifact)
    if artifact["diagnostics"]["status"] == "failed":
        return None, artifact
    return artifact_to_document(artifact), artifact


def parse_pdf_artifact(
    source_path: Path,
    doc_id: str,
    title: str,
    agency: str,
    project: str,
    metadata: dict[str, Any],
    ocr_provider: OcrProvider | None,
) -> dict[str, Any]:
    artifact = base_visual_artifact(source_path, doc_id, "pdf", title, agency, project, metadata)
    try:
        import fitz  # type: ignore
    except Exception as exc:
        mark_failed(artifact, "pdf_parser_unavailable", {"dependency": "pymupdf", "error": str(exc)})
        return artifact

    try:
        pdf_doc = fitz.open(str(source_path))
    except Exception as exc:
        mark_failed(artifact, "pdf_open_failed", {"error": str(exc)})
        return artifact

    text_block_count = 0
    ocr_block_count = 0
    with pdf_doc:
        for page_index, page in enumerate(pdf_doc, start=1):
            width = float(page.rect.width)
            height = float(page.rect.height)
            blocks = pdf_text_blocks(page, page_index, width, height, doc_id)
            text_block_count += len(blocks)
            page_text = "\n".join(block["text"] for block in blocks)
            if len(page_text.strip()) < PDF_MIN_TEXT_CHARS_FOR_OCR:
                ocr_blocks, ocr_reason = ocr_pdf_page(page, page_index, width, height, doc_id, ocr_provider)
                if ocr_blocks:
                    blocks.extend(ocr_blocks)
                    ocr_block_count += len(ocr_blocks)
                elif not page_text.strip():
                    add_reason(artifact, ocr_reason or "ocr_unavailable")
            artifact["pages"].append(
                {
                    "page_number": page_index,
                    "width": width,
                    "height": height,
                    "blocks": blocks,
                }
            )

    add_stage(artifact, "pdf_text_layer", "ok", {"blocks": text_block_count})
    if ocr_block_count:
        add_stage(artifact, "ocr", "ok", {"blocks": ocr_block_count})
    elif artifact["diagnostics"]["reasons"]:
        add_stage(artifact, "ocr", "failed", {"reason": "ocr_unavailable"})
    else:
        add_stage(artifact, "ocr", "skipped", {"reason": "text_layer_sufficient"})

    artifact["tables"].extend(pdfplumber_tables(source_path, artifact))
    return artifact


def pdf_text_blocks(
    page: Any,
    page_number: int,
    page_width: float,
    page_height: float,
    doc_id: str,
) -> list[dict[str, Any]]:
    try:
        raw = page.get_text("dict")
    except Exception:
        return []

    blocks = []
    for block_index, block in enumerate(raw.get("blocks", []), start=1):
        if block.get("type") != 0:
            continue
        text = text_from_pdf_block(block)
        if not text:
            continue
        bbox = normalize_bbox(block.get("bbox"), page_width, page_height)
        blocks.append(
            {
                "block_id": f"{doc_id}::p{page_number:03d}::b{block_index:03d}",
                "text": text,
                "type": classify_layout_block(text),
                "page_number": page_number,
                "bbox": bbox,
                "confidence": 1.0,
                "source": "pdf_text_layer",
            }
        )
    return blocks


def text_from_pdf_block(block: dict[str, Any]) -> str:
    lines = []
    for line in block.get("lines", []):
        parts = [str(span.get("text") or "").strip() for span in line.get("spans", [])]
        line_text = " ".join(part for part in parts if part).strip()
        if line_text:
            lines.append(line_text)
    return normalize_body_text("\n".join(lines))


def ocr_pdf_page(
    page: Any,
    page_number: int,
    page_width: float,
    page_height: float,
    doc_id: str,
    ocr_provider: OcrProvider | None,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        import fitz  # type: ignore
        from PIL import Image
    except Exception:
        return [], "ocr_unavailable"

    try:
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        blocks = ocr_blocks_from_image(
            image,
            page_number=page_number,
            width=float(pixmap.width),
            height=float(pixmap.height),
            doc_id=doc_id,
            source="ocr_pdf_page",
            ocr_provider=ocr_provider,
        )
        scale_x = page_width / max(1.0, float(pixmap.width))
        scale_y = page_height / max(1.0, float(pixmap.height))
        return [scale_block_bbox(block, scale_x, scale_y) for block in blocks], None
    except OcrUnavailable:
        return [], "ocr_unavailable"
    except Exception:
        return [], "ocr_failed"


def parse_image_artifact(
    source_path: Path,
    doc_id: str,
    title: str,
    agency: str,
    project: str,
    metadata: dict[str, Any],
    ocr_provider: OcrProvider | None,
) -> dict[str, Any]:
    file_format = normalize_file_format("", source_path.name)
    artifact = base_visual_artifact(source_path, doc_id, file_format, title, agency, project, metadata)
    try:
        from PIL import Image
    except Exception as exc:
        mark_failed(artifact, "image_parser_unavailable", {"dependency": "pillow", "error": str(exc)})
        return artifact

    try:
        with Image.open(source_path) as image:
            width, height = image.size
            blocks = ocr_blocks_from_image(
                image.convert("RGB"),
                page_number=1,
                width=float(width),
                height=float(height),
                doc_id=doc_id,
                source="ocr_image",
                ocr_provider=ocr_provider,
            )
    except OcrUnavailable as exc:
        mark_failed(artifact, "ocr_unavailable", {"error": str(exc)})
        return artifact
    except Exception as exc:
        mark_failed(artifact, "image_open_failed", {"error": str(exc)})
        return artifact

    artifact["pages"].append(
        {
            "page_number": 1,
            "width": float(width),
            "height": float(height),
            "blocks": blocks,
        }
    )
    add_stage(artifact, "ocr", "ok", {"blocks": len(blocks)})
    return artifact


def ocr_blocks_from_image(
    image: Any,
    page_number: int,
    width: float,
    height: float,
    doc_id: str,
    source: str,
    ocr_provider: OcrProvider | None,
) -> list[dict[str, Any]]:
    provider = ocr_provider or tesseract_ocr_provider
    result = provider(image)
    return normalize_ocr_result(result, page_number, width, height, doc_id, source)


def tesseract_ocr_provider(image: Any) -> list[dict[str, Any]]:
    try:
        import pytesseract  # type: ignore
    except Exception as exc:
        raise OcrUnavailable(f"pytesseract_unavailable: {exc}") from exc

    try:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    except Exception as exc:
        raise OcrUnavailable(f"tesseract_unavailable: {exc}") from exc

    grouped: dict[tuple[int, int, int], dict[str, Any]] = {}
    for idx, raw_text in enumerate(data.get("text", [])):
        text = str(raw_text or "").strip()
        if not text:
            continue
        try:
            confidence = float(data.get("conf", [0])[idx])
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0:
            confidence = 0.0
        key = (
            int(data.get("block_num", [0])[idx]),
            int(data.get("par_num", [0])[idx]),
            int(data.get("line_num", [0])[idx]),
        )
        left = float(data.get("left", [0])[idx])
        top = float(data.get("top", [0])[idx])
        width = float(data.get("width", [0])[idx])
        height = float(data.get("height", [0])[idx])
        entry = grouped.setdefault(key, {"parts": [], "confidences": [], "boxes": []})
        entry["parts"].append(text)
        entry["confidences"].append(confidence / 100.0)
        entry["boxes"].append([left, top, left + width, top + height])

    blocks = []
    for entry in grouped.values():
        text = " ".join(entry["parts"]).strip()
        if not text:
            continue
        confidences = entry["confidences"] or [0.0]
        blocks.append(
            {
                "text": text,
                "bbox": union_bboxes(entry["boxes"]),
                "confidence": round(sum(confidences) / len(confidences), 3),
            }
        )
    return blocks


def normalize_ocr_result(
    result: str | list[dict[str, Any]],
    page_number: int,
    width: float,
    height: float,
    doc_id: str,
    source: str,
) -> list[dict[str, Any]]:
    if isinstance(result, str):
        text = normalize_body_text(result)
        if not text:
            return []
        result = [{"text": text, "bbox": [0.0, 0.0, width, height], "confidence": 1.0}]

    blocks = []
    for idx, block in enumerate(result, start=1):
        text = normalize_body_text(str(block.get("text") or ""))
        if not text:
            continue
        bbox = normalize_bbox(block.get("bbox"), width, height)
        confidence = float(block.get("confidence", 1.0) or 0.0)
        blocks.append(
            {
                "block_id": block.get("block_id") or f"{doc_id}::p{page_number:03d}::ocr{idx:03d}",
                "text": text,
                "type": str(block.get("type") or classify_layout_block(text)),
                "page_number": int(block.get("page_number") or page_number),
                "bbox": bbox,
                "confidence": round(max(0.0, min(1.0, confidence)), 3),
                "source": str(block.get("source") or source),
            }
        )
    return blocks


def pdfplumber_tables(source_path: Path, artifact: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        import pdfplumber  # type: ignore
    except Exception:
        add_stage(artifact, "table_extraction", "skipped", {"reason": "pdfplumber_unavailable"})
        return []

    tables = []
    try:
        with pdfplumber.open(str(source_path)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                for table_index, table in enumerate(page.find_tables(), start=1):
                    rows = table.extract() or []
                    if not rows:
                        continue
                    tables.append(
                        {
                            "table_id": f"{artifact['doc_id']}::p{page_number:03d}::table{table_index:03d}",
                            "page_number": page_number,
                            "bbox": normalize_bbox(table.bbox, float(page.width), float(page.height)),
                            "rows": rows,
                            "source": "pdfplumber",
                            "confidence": 0.8,
                        }
                    )
    except Exception as exc:
        add_stage(artifact, "table_extraction", "failed", {"error": str(exc)})
        return []

    add_stage(artifact, "table_extraction", "ok", {"tables": len(tables)})
    return tables


def finalize_visual_artifact(artifact: dict[str, Any]) -> None:
    if artifact["diagnostics"]["status"] == "failed":
        return

    blocks = all_blocks(artifact)
    if not blocks:
        mark_failed(artifact, "empty_visual_text")
        return

    heuristic_tables = extract_table_candidates(blocks, doc_id=artifact["doc_id"])
    if heuristic_tables:
        artifact["tables"].extend(heuristic_tables)
    artifact["field_candidates"] = extract_field_candidates(blocks)
    artifact["sections"] = build_sections_from_blocks(blocks)

    if not artifact["sections"]:
        mark_failed(artifact, "empty_visual_text")
        return

    reasons = artifact["diagnostics"]["reasons"]
    artifact["diagnostics"]["status"] = "partial" if reasons else "parsed"
    artifact["diagnostics"]["summary"] = {
        "pages": len(artifact["pages"]),
        "blocks": len(blocks),
        "tables": len(artifact["tables"]),
        "field_candidates": len(artifact["field_candidates"]),
        "sections": len(artifact["sections"]),
    }


def make_hwp_fallback_document(
    row: dict[str, str],
    doc_id: str,
    source_path: Path,
    file_format: str,
    file_name: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    metadata = normalize_metadata(row, file_format, file_name)
    metadata["visual_fallback_reason"] = "visual_fallback_hwp"
    title = clean_cell(row.get("사업명")) or Path(file_name).stem
    artifact = base_visual_artifact(
        source_path=source_path,
        doc_id=doc_id,
        file_format=file_format,
        title=title,
        agency=clean_cell(row.get("발주 기관")),
        project=clean_cell(row.get("사업명")),
        metadata=metadata,
    )
    text = normalize_body_text(row.get("텍스트", ""))
    if not text:
        mark_failed(artifact, "empty_text")
        return None, artifact

    region = {
        "page_number": None,
        "bbox": None,
        "source": "data_list_csv_text",
        "type": "fallback_text",
        "block_id": f"{doc_id}::fallback::text",
    }
    artifact["sections"] = [
        {
            "heading": "본문",
            "section_path": ["본문"],
            "text": text,
            "page_span": None,
            "regions": [region],
        }
    ]
    artifact["diagnostics"]["status"] = "fallback"
    artifact["diagnostics"]["reasons"] = ["visual_fallback_hwp"]
    artifact["diagnostics"]["stages"].append(
        {
            "name": "hwp_visual_parsing",
            "status": "fallback",
            "reason": "HWP native visual parsing is out of scope for v2.",
        }
    )
    artifact["diagnostics"]["summary"] = {
        "pages": 0,
        "blocks": 0,
        "tables": 0,
        "field_candidates": 0,
        "sections": 1,
    }
    return artifact_to_document(artifact), artifact


def artifact_to_document(artifact: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(artifact.get("metadata") or {})
    metadata.setdefault("file_format", artifact["file_format"])
    metadata["visual_schema_version"] = artifact["schema_version"]
    if metadata.get("visual_fallback_reason") == "visual_fallback_hwp":
        metadata["document_type"] = "private_hwp_csv_text_visual_fallback"
        metadata["text_source"] = "data_list_csv_text"
    else:
        metadata["document_type"] = "visual_parsing_v2"
        metadata["text_source"] = "visual_parsing_v2"
    metadata["visual_parse_status"] = artifact["diagnostics"]["status"]

    return {
        "doc_id": artifact["doc_id"],
        "title": artifact["title"],
        "agency": artifact.get("agency", ""),
        "project": artifact.get("project", ""),
        "metadata": metadata,
        "sections": artifact.get("sections", []),
        "source_path": artifact["source_path"],
    }


def base_visual_artifact(
    source_path: Path,
    doc_id: str,
    file_format: str,
    title: str,
    agency: str,
    project: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "doc_id": doc_id,
        "title": title,
        "agency": agency,
        "project": project,
        "source_path": str(source_path),
        "file_format": file_format,
        "metadata": dict(metadata),
        "pages": [],
        "tables": [],
        "field_candidates": [],
        "sections": [],
        "diagnostics": {
            "status": "parsed",
            "reasons": [],
            "stages": [],
            "summary": {},
        },
    }


def failure_artifact(
    doc_id: str,
    source_path: Path,
    file_format: str,
    title: str,
    metadata: dict[str, Any],
    reason: str,
    agency: str = "",
    project: str = "",
) -> dict[str, Any]:
    artifact = base_visual_artifact(source_path, doc_id, file_format, title, agency, project, metadata)
    mark_failed(artifact, reason)
    return artifact


def mark_failed(artifact: dict[str, Any], reason: str, detail: dict[str, Any] | None = None) -> None:
    artifact["diagnostics"]["status"] = "failed"
    add_reason(artifact, reason)
    stage = {"name": "visual_parsing", "status": "failed", "reason": reason}
    if detail:
        stage.update(detail)
    artifact["diagnostics"]["stages"].append(stage)


def add_reason(artifact: dict[str, Any], reason: str) -> None:
    reasons = artifact["diagnostics"].setdefault("reasons", [])
    if reason and reason not in reasons:
        reasons.append(reason)


def add_stage(
    artifact: dict[str, Any],
    name: str,
    status: str,
    detail: dict[str, Any] | None = None,
) -> None:
    stage = {"name": name, "status": status}
    if detail:
        stage.update(detail)
    artifact["diagnostics"].setdefault("stages", []).append(stage)


def all_blocks(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = []
    for page in artifact.get("pages", []):
        blocks.extend(page.get("blocks") or [])
    return blocks


def classify_layout_block(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    compact = re.sub(r"\s+", "", first_line)
    if re.match(r"^(제\s*\d+\s*[장절]|[IVXLC]+\.|\d+[\).]|[가-힣]\.)", first_line):
        return "heading"
    heading_keywords = (
        "제안요청",
        "사업개요",
        "사업 개요",
        "요구사항",
        "과업내용",
        "과업 내용",
        "입찰",
        "평가",
        "목차",
        "security requirements",
        "requirements",
    )
    lowered = first_line.lower()
    if (
        0 < len(compact) <= 48
        and ":" not in first_line
        and not re.search(r"[.?!。]$", first_line)
        and any(keyword in lowered for keyword in heading_keywords)
    ):
        return "heading"
    if looks_like_table_line(first_line):
        return "table"
    return "text"


def build_sections_from_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for block in blocks:
        text = normalize_body_text(block.get("text", ""))
        if not text:
            continue
        block_type = block.get("type") or classify_layout_block(text)
        is_heading = block_type == "heading"
        if current is None or is_heading:
            heading = first_non_empty_line(text) if is_heading else "문서 전체"
            remainder = text_after_first_line(text) if is_heading else text
            current = {
                "heading": heading,
                "section_path": [heading],
                "text_parts": [remainder] if remainder else [],
                "regions": [] if is_heading else [region_from_block(block)],
            }
            sections.append(current)
            if is_heading:
                current["regions"].append(region_from_block(block))
            continue
        current["text_parts"].append(text)
        current["regions"].append(region_from_block(block))

    normalized = []
    for section in sections:
        text = "\n".join(part for part in section.pop("text_parts", []) if part).strip()
        if not text:
            text = section["heading"]
        regions = [region for region in section.get("regions", []) if region]
        normalized.append(
            {
                "heading": section["heading"],
                "section_path": section["section_path"],
                "text": text,
                "page_span": page_span_from_regions(regions),
                "regions": regions,
            }
        )
    return normalized


def extract_table_candidates(
    blocks: list[dict[str, Any]],
    doc_id: str = "visual-doc",
) -> list[dict[str, Any]]:
    tables = []
    table_seq = 1
    for block in blocks:
        lines = [line.strip() for line in str(block.get("text") or "").splitlines() if line.strip()]
        table_lines = [line for line in lines if looks_like_table_line(line)]
        if len(table_lines) < 2:
            continue
        rows = [split_table_line(line) for line in table_lines]
        if max(len(row) for row in rows) < 2:
            continue
        tables.append(
            {
                "table_id": f"{doc_id}::p{int(block.get('page_number') or 1):03d}::heuristic{table_seq:03d}",
                "page_number": block.get("page_number"),
                "bbox": block.get("bbox"),
                "rows": rows,
                "source": "layout_heuristic",
                "confidence": 0.45,
            }
        )
        table_seq += 1
    return tables


def extract_field_candidates(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    field_seq = 1
    for block in blocks:
        for line in str(block.get("text") or "").splitlines():
            match = re.match(r"^\s*([^:=：]{2,40})\s*[:=：]\s*(.{1,200})\s*$", line)
            if not match:
                continue
            candidates.append(
                {
                    "field_id": f"field-{field_seq:03d}",
                    "key": match.group(1).strip(),
                    "value": match.group(2).strip(),
                    "page_number": block.get("page_number"),
                    "bbox": block.get("bbox"),
                    "source": block.get("source", ""),
                    "confidence": block.get("confidence", 1.0),
                }
            )
            field_seq += 1
    return candidates


def looks_like_table_line(line: str) -> bool:
    if "|" in line or "\t" in line:
        return True
    return bool(re.search(r"\S+\s{2,}\S+\s{2,}\S+", line))


def split_table_line(line: str) -> list[str]:
    if "|" in line:
        parts = line.split("|")
    elif "\t" in line:
        parts = line.split("\t")
    else:
        parts = re.split(r"\s{2,}", line)
    return [part.strip() for part in parts if part.strip()]


def first_non_empty_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "문서 전체")


def text_after_first_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) <= 1:
        return ""
    return "\n".join(lines[1:]).strip()


def region_from_block(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "page_number": block.get("page_number"),
        "bbox": block.get("bbox"),
        "source": block.get("source", ""),
        "type": block.get("type", ""),
        "block_id": block.get("block_id", ""),
    }


def page_span_from_regions(regions: list[dict[str, Any]]) -> list[int] | None:
    page_numbers = [
        int(region["page_number"])
        for region in regions
        if isinstance(region.get("page_number"), int)
    ]
    if not page_numbers:
        return None
    return [min(page_numbers), max(page_numbers)]


def normalize_bbox(value: Any, width: float, height: float) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x0, y0, x1, y1 = [float(part) for part in value]
    except (TypeError, ValueError):
        return None
    x0 = max(0.0, min(width, x0))
    x1 = max(0.0, min(width, x1))
    y0 = max(0.0, min(height, y0))
    y1 = max(0.0, min(height, y1))
    return [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]


def union_bboxes(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return [
        round(min(box[0] for box in boxes), 2),
        round(min(box[1] for box in boxes), 2),
        round(max(box[2] for box in boxes), 2),
        round(max(box[3] for box in boxes), 2),
    ]


def scale_block_bbox(block: dict[str, Any], scale_x: float, scale_y: float) -> dict[str, Any]:
    bbox = block.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        block = dict(block)
        block["bbox"] = [
            round(float(bbox[0]) * scale_x, 2),
            round(float(bbox[1]) * scale_y, 2),
            round(float(bbox[2]) * scale_x, 2),
            round(float(bbox[3]) * scale_y, 2),
        ]
    return block


def write_visual_artifact(artifact: dict[str, Any], artifact_dir: Path) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    out_path = artifact_dir / f"{safe_file_stem(artifact['doc_id'])}.visual.json"
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def attach_artifact_path(document: dict[str, Any], artifact_path: Path) -> None:
    document.setdefault("metadata", {})["visual_artifact_path"] = str(artifact_path)


def safe_file_stem(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_.-]+", "-", value).strip("-") or "visual-artifact"


def record_from_artifact(
    artifact: dict[str, Any],
    artifact_path: Path | None,
    row_number: int | None,
) -> VisualIngestionRecord:
    reasons = artifact.get("diagnostics", {}).get("reasons") or []
    return VisualIngestionRecord(
        row_number=row_number,
        status=str(artifact.get("diagnostics", {}).get("status") or "failed"),
        doc_id=artifact.get("doc_id"),
        file_name=str(artifact.get("metadata", {}).get("file_name") or Path(artifact["source_path"]).name),
        file_format=str(artifact.get("file_format") or ""),
        source_path=str(artifact.get("source_path") or ""),
        artifact_path=str(artifact_path) if artifact_path else None,
        reason=str(reasons[0]) if reasons else None,
    )


def replace_record_artifact_path(record: VisualIngestionRecord, artifact_path: Path) -> VisualIngestionRecord:
    return VisualIngestionRecord(
        row_number=record.row_number,
        status=record.status,
        doc_id=record.doc_id,
        file_name=record.file_name,
        file_format=record.file_format,
        source_path=record.source_path,
        artifact_path=str(artifact_path),
        reason=record.reason,
    )


def make_visual_report(
    source: dict[str, str],
    records: list[VisualIngestionRecord],
) -> dict[str, Any]:
    status_counts = {
        status: sum(1 for record in records if record.status == status)
        for status in ("parsed", "partial", "fallback", "failed")
    }
    summary = {
        "total_rows": len(records),
        "indexed_documents": len(records) - status_counts["failed"],
        "failed_rows": status_counts["failed"],
        **{f"{status}_documents": count for status, count in status_counts.items()},
    }
    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "ingestion_mode": "visual",
        **source,
        "summary": summary,
        "records": [asdict(record) for record in records],
    }

