#!/usr/bin/env python3
"""Run parser-stage evaluation for visual parsing v2 artifacts.

This evaluator compares already generated ``*.visual.json`` artifacts against a
small gold file. It does not rerun OCR, PDF parsing, indexing, or QA eval.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any

import yaml


REPORT_SCHEMA_VERSION = 1

METRIC_KEYS = (
    "ocr_text_recall",
    "ocr_char_f1",
    "layout_block_precision",
    "layout_block_recall",
    "layout_block_f1",
    "section_boundary_recall",
    "table_cell_f1",
    "table_row_f1",
    "table_column_f1",
    "field_precision",
    "field_recall",
    "field_f1",
    "bbox_alignment_rate",
)

FAILURE_TAXONOMY = {
    "artifact_missing": {
        "stage": "artifact",
        "downstream_risk": "Parser run cannot be compared for this document.",
    },
    "ocr_missing_text": {
        "stage": "ocr",
        "downstream_risk": "Important text may be absent from retrieval candidates.",
    },
    "layout_block_missing": {
        "stage": "layout",
        "downstream_risk": "Chunking and section grouping may lose document structure.",
    },
    "layout_type_mismatch": {
        "stage": "layout",
        "downstream_risk": "Headings, tables, and body text may be grouped incorrectly.",
    },
    "section_boundary_missing": {
        "stage": "section",
        "downstream_risk": "Section-aware chunks may become noisy or incomplete.",
    },
    "table_cell_mismatch": {
        "stage": "table",
        "downstream_risk": "Tabular requirements may be flattened or misread.",
    },
    "field_missing": {
        "stage": "field",
        "downstream_risk": "Metadata-like facts may not be available for filtering or answers.",
    },
    "field_value_mismatch": {
        "stage": "field",
        "downstream_risk": "Extracted key-value facts may support wrong claims.",
    },
    "bbox_missing": {
        "stage": "bbox",
        "downstream_risk": "Citations cannot point back to page regions.",
    },
    "bbox_misaligned": {
        "stage": "bbox",
        "downstream_risk": "Page-region citations may point to the wrong visual evidence.",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run parser-stage metrics over visual parsing v2 artifacts."
    )
    parser.add_argument(
        "--artifact_dir",
        required=True,
        help="Directory containing generated *.visual.json artifacts.",
    )
    parser.add_argument("--gold", required=True, help="Parser-stage gold YAML file.")
    parser.add_argument(
        "--output_dir",
        default="reports",
        help="Directory to save parser_eval_summary.json.",
    )
    parser.add_argument("--run_name", default="visual_v2", help="Stable parser run name.")
    parser.add_argument(
        "--parser_version",
        default="2",
        help="Parser version label to record in the report.",
    )
    return parser.parse_args()


def load_gold(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Parser gold must be a mapping: {path}")
    documents = data.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("Parser gold must include a non-empty documents list")
    seen_doc_ids: set[str] = set()
    for document in documents:
        if not isinstance(document, dict):
            raise ValueError("Each parser gold document must be a mapping")
        doc_id = str(document.get("doc_id") or "").strip()
        if not doc_id:
            raise ValueError("Each parser gold document must include doc_id")
        if doc_id in seen_doc_ids:
            raise ValueError(f"Duplicate parser gold doc_id: {doc_id}")
        seen_doc_ids.add(doc_id)
    return data


def load_artifact(artifact_dir: Path, gold_doc: dict[str, Any]) -> tuple[Path, dict[str, Any] | None]:
    doc_id = str(gold_doc["doc_id"])
    artifact_name = str(gold_doc.get("artifact") or f"{doc_id}.visual.json")
    artifact_path = Path(artifact_name)
    if not artifact_path.is_absolute():
        artifact_path = artifact_dir / artifact_path
    if not artifact_path.exists():
        return artifact_path, None
    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Visual artifact must be a JSON object: {artifact_path}")
    return artifact_path, data


def normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def text_chars(value: Any) -> Counter[str]:
    return Counter(char for char in normalize_text(value) if not char.isspace())


def round_score(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def safe_rate(values: list[float | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    if not present:
        return None
    return round_score(sum(present) / len(present))


def prf(matched: int, predicted_total: int, expected_total: int) -> dict[str, float | None]:
    if expected_total == 0:
        return {"precision": None, "recall": None, "f1": None}
    precision = matched / predicted_total if predicted_total else 0.0
    recall = matched / expected_total
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {
        "precision": round_score(precision),
        "recall": round_score(recall),
        "f1": round_score(f1),
    }


def counter_prf(predicted: Counter[Any], expected: Counter[Any]) -> dict[str, float | None]:
    expected_total = sum(expected.values())
    predicted_total = sum(predicted.values())
    if expected_total == 0:
        return {"precision": None, "recall": None, "f1": None}
    matched = sum((predicted & expected).values())
    return prf(matched, predicted_total, expected_total)


def add_error(
    errors: list[dict[str, Any]],
    code: str,
    message: str,
    expected: Any = None,
    actual: Any = None,
) -> None:
    taxonomy = FAILURE_TAXONOMY[code]
    error = {
        "code": code,
        "stage": taxonomy["stage"],
        "message": message,
    }
    if expected is not None:
        error["expected"] = expected
    if actual is not None:
        error["actual"] = actual
    errors.append(error)


def all_blocks(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for page in artifact.get("pages") or []:
        if isinstance(page, dict):
            page_blocks = page.get("blocks") or []
            blocks.extend(block for block in page_blocks if isinstance(block, dict))
    return blocks


def artifact_text(artifact: dict[str, Any]) -> str:
    return "\n".join(str(block.get("text") or "") for block in all_blocks(artifact))


def find_block(
    blocks: list[dict[str, Any]],
    expected_text: str,
    page_number: int | None = None,
) -> dict[str, Any] | None:
    expected = normalize_text(expected_text)
    if not expected:
        return None
    for block in blocks:
        if page_number is not None and block.get("page_number") != page_number:
            continue
        if expected in normalize_text(block.get("text")):
            return block
    return None


def score_ocr(gold_doc: dict[str, Any], artifact: dict[str, Any], errors: list[dict[str, Any]]) -> dict[str, Any]:
    expected = gold_doc.get("ocr_text") or {}
    snippets = [str(item) for item in expected.get("snippets") or []]
    full_expected = " ".join(snippets)
    predicted_text = artifact_text(artifact)

    matched_snippets = 0
    for snippet in snippets:
        if normalize_text(snippet) in normalize_text(predicted_text):
            matched_snippets += 1
        else:
            add_error(
                errors,
                "ocr_missing_text",
                "Expected OCR/text snippet was not found in artifact blocks.",
                expected=snippet,
            )

    expected_chars = text_chars(full_expected)
    predicted_chars = text_chars(predicted_text)
    char_scores = counter_prf(predicted_chars, expected_chars)
    return {
        "ocr_text_recall": round_score(matched_snippets / len(snippets)) if snippets else None,
        "ocr_char_f1": char_scores["f1"],
    }


def score_layout(
    gold_doc: dict[str, Any], artifact: dict[str, Any], errors: list[dict[str, Any]]
) -> dict[str, Any]:
    expected_blocks = [item for item in gold_doc.get("layout_blocks") or [] if isinstance(item, dict)]
    blocks = all_blocks(artifact)
    matched = 0
    for expected in expected_blocks:
        expected_text = str(expected.get("text") or "")
        page_number = expected.get("page_number")
        if not isinstance(page_number, int):
            page_number = None
        block = find_block(blocks, expected_text, page_number)
        if block is None:
            add_error(
                errors,
                "layout_block_missing",
                "Expected layout block text was not found.",
                expected=expected,
            )
            continue
        expected_type = str(expected.get("type") or "")
        actual_type = str(block.get("type") or "")
        if expected_type and actual_type != expected_type:
            add_error(
                errors,
                "layout_type_mismatch",
                "Expected layout block was found with a different type.",
                expected=expected,
                actual={"type": actual_type, "block_id": block.get("block_id")},
            )
            continue
        matched += 1

    scores = prf(matched, len(blocks), len(expected_blocks))
    return {
        "layout_block_precision": scores["precision"],
        "layout_block_recall": scores["recall"],
        "layout_block_f1": scores["f1"],
    }


def score_sections(
    gold_doc: dict[str, Any], artifact: dict[str, Any], errors: list[dict[str, Any]]
) -> dict[str, Any]:
    expected_sections = [item for item in gold_doc.get("sections") or [] if isinstance(item, dict)]
    actual_sections = [item for item in artifact.get("sections") or [] if isinstance(item, dict)]
    matched = 0
    for expected in expected_sections:
        expected_heading = normalize_text(expected.get("heading"))
        expected_page_span = expected.get("page_span")
        found = None
        for section in actual_sections:
            if expected_heading != normalize_text(section.get("heading")):
                continue
            if expected_page_span and section.get("page_span") != expected_page_span:
                continue
            found = section
            break
        if found is None:
            add_error(
                errors,
                "section_boundary_missing",
                "Expected section heading/page span was not found.",
                expected=expected,
            )
        else:
            matched += 1
    return {
        "section_boundary_recall": (
            round_score(matched / len(expected_sections)) if expected_sections else None
        )
    }


def rows_from_tables(tables: list[Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        for row in table.get("rows") or []:
            if isinstance(row, list):
                normalized_row = [normalize_text(cell) for cell in row if normalize_text(cell)]
                if normalized_row:
                    rows.append(normalized_row)
    return rows


def row_counter(rows: list[list[str]]) -> Counter[str]:
    return Counter("\t".join(row) for row in rows)


def cell_counter(rows: list[list[str]]) -> Counter[str]:
    return Counter(cell for row in rows for cell in row)


def column_counter(rows: list[list[str]]) -> Counter[int]:
    return Counter(len(row) for row in rows if row)


def score_tables(
    gold_doc: dict[str, Any], artifact: dict[str, Any], errors: list[dict[str, Any]]
) -> dict[str, Any]:
    expected_rows = rows_from_tables(gold_doc.get("tables") or [])
    actual_rows = rows_from_tables(artifact.get("tables") or [])
    cell_scores = counter_prf(cell_counter(actual_rows), cell_counter(expected_rows))
    row_scores = counter_prf(row_counter(actual_rows), row_counter(expected_rows))
    column_scores = counter_prf(column_counter(actual_rows), column_counter(expected_rows))

    if expected_rows and cell_scores["f1"] != 1.0:
        add_error(
            errors,
            "table_cell_mismatch",
            "Expected table rows/cells were not fully reconstructed.",
            expected=expected_rows,
            actual=actual_rows,
        )

    return {
        "table_cell_f1": cell_scores["f1"],
        "table_row_f1": row_scores["f1"],
        "table_column_f1": column_scores["f1"],
    }


def normalize_field(field: dict[str, Any]) -> tuple[str, str]:
    return normalize_text(field.get("key")), normalize_text(field.get("value"))


def value_matches(expected: str, actual: str) -> bool:
    if not expected:
        return True
    return expected == actual or expected in actual or actual in expected


def score_fields(
    gold_doc: dict[str, Any], artifact: dict[str, Any], errors: list[dict[str, Any]]
) -> dict[str, Any]:
    expected_fields = [item for item in gold_doc.get("fields") or [] if isinstance(item, dict)]
    actual_fields = [item for item in artifact.get("field_candidates") or [] if isinstance(item, dict)]
    matched = 0
    used_actual: set[int] = set()
    for expected in expected_fields:
        expected_key, expected_value = normalize_field(expected)
        same_key = [
            (idx, field)
            for idx, field in enumerate(actual_fields)
            if idx not in used_actual and normalize_text(field.get("key")) == expected_key
        ]
        if not same_key:
            add_error(
                errors,
                "field_missing",
                "Expected key-value field was not extracted.",
                expected=expected,
            )
            continue
        matching_value = [
            (idx, field)
            for idx, field in same_key
            if value_matches(expected_value, normalize_text(field.get("value")))
        ]
        if not matching_value:
            add_error(
                errors,
                "field_value_mismatch",
                "Expected field key was found with a different value.",
                expected=expected,
                actual=[field for _, field in same_key],
            )
            continue
        used_actual.add(matching_value[0][0])
        matched += 1

    scores = prf(matched, len(actual_fields), len(expected_fields))
    return {
        "field_precision": scores["precision"],
        "field_recall": scores["recall"],
        "field_f1": scores["f1"],
    }


def is_bbox(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    try:
        [float(part) for part in value]
    except (TypeError, ValueError):
        return False
    return True


def bbox_iou(left: list[Any], right: list[Any]) -> float:
    l0, t0, l1, b1 = [float(part) for part in left]
    r0, u0, r1, d1 = [float(part) for part in right]
    inter_w = max(0.0, min(l1, r1) - max(l0, r0))
    inter_h = max(0.0, min(b1, d1) - max(t0, u0))
    intersection = inter_w * inter_h
    left_area = max(0.0, l1 - l0) * max(0.0, b1 - t0)
    right_area = max(0.0, r1 - r0) * max(0.0, d1 - u0)
    union = left_area + right_area - intersection
    return 0.0 if union <= 0 else intersection / union


def score_bboxes(
    gold_doc: dict[str, Any], artifact: dict[str, Any], errors: list[dict[str, Any]]
) -> dict[str, Any]:
    anchors = [item for item in gold_doc.get("bbox_anchors") or [] if isinstance(item, dict)]
    if not anchors:
        return {"bbox_alignment_rate": None}

    blocks = all_blocks(artifact)
    aligned = 0
    for anchor in anchors:
        page_number = anchor.get("page_number")
        if not isinstance(page_number, int):
            page_number = None
        block_id = str(anchor.get("block_id") or "")
        if block_id:
            block = next((item for item in blocks if item.get("block_id") == block_id), None)
        else:
            block = find_block(blocks, str(anchor.get("text") or ""), page_number)

        if block is None:
            add_error(
                errors,
                "bbox_missing",
                "Expected page-region anchor block was not found.",
                expected=anchor,
            )
            continue

        actual_bbox = block.get("bbox")
        if not is_bbox(actual_bbox):
            add_error(
                errors,
                "bbox_missing",
                "Expected page-region anchor has no bbox.",
                expected=anchor,
                actual={"block_id": block.get("block_id"), "bbox": actual_bbox},
            )
            continue

        expected_bbox = anchor.get("bbox")
        if is_bbox(expected_bbox):
            min_iou = float(anchor.get("min_iou", 0.5))
            iou = bbox_iou(actual_bbox, expected_bbox)
            if iou < min_iou:
                add_error(
                    errors,
                    "bbox_misaligned",
                    "Expected bbox anchor did not meet the IoU threshold.",
                    expected=anchor,
                    actual={
                        "block_id": block.get("block_id"),
                        "bbox": actual_bbox,
                        "iou": round_score(iou),
                    },
                )
                continue
        aligned += 1

    return {"bbox_alignment_rate": round_score(aligned / len(anchors))}


def score_document(
    gold_doc: dict[str, Any],
    artifact: dict[str, Any] | None,
    artifact_path: Path,
) -> dict[str, Any]:
    doc_id = str(gold_doc["doc_id"])
    errors: list[dict[str, Any]] = []
    metrics = {key: None for key in METRIC_KEYS}

    if artifact is None:
        add_error(errors, "artifact_missing", "Expected visual artifact file is missing.")
        return {
            "doc_id": doc_id,
            "artifact_path": str(artifact_path),
            "parser_status": "missing",
            "metrics": metrics,
            "errors": errors,
        }

    metrics.update(score_ocr(gold_doc, artifact, errors))
    metrics.update(score_layout(gold_doc, artifact, errors))
    metrics.update(score_sections(gold_doc, artifact, errors))
    metrics.update(score_tables(gold_doc, artifact, errors))
    metrics.update(score_fields(gold_doc, artifact, errors))
    metrics.update(score_bboxes(gold_doc, artifact, errors))

    diagnostics = artifact.get("diagnostics") or {}
    return {
        "doc_id": doc_id,
        "artifact_path": str(artifact_path),
        "parser_status": str(diagnostics.get("status") or "unknown"),
        "metrics": metrics,
        "errors": errors,
    }


def summarize_documents(documents: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = {
        key: safe_rate([doc.get("metrics", {}).get(key) for doc in documents])
        for key in METRIC_KEYS
    }
    failure_counts = Counter(
        error["code"]
        for document in documents
        for error in document.get("errors") or []
        if error.get("code")
    )
    return {
        "num_documents": len(documents),
        "num_documents_with_errors": sum(1 for doc in documents if doc.get("errors")),
        "metrics": metrics,
        "failure_counts": dict(sorted(failure_counts.items())),
    }


def build_report(
    artifact_dir: Path,
    gold_path: Path,
    gold: dict[str, Any],
    run_name: str,
    parser_version: str,
) -> dict[str, Any]:
    document_results = []
    for gold_doc in sorted(gold["documents"], key=lambda item: str(item["doc_id"])):
        artifact_path, artifact = load_artifact(artifact_dir, gold_doc)
        document_results.append(score_document(gold_doc, artifact, artifact_path))

    return {
        "mode": "parser",
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": {
            "name": run_name,
            "parser_version": str(parser_version),
            "artifact_dir": str(artifact_dir),
            "gold": str(gold_path),
        },
        "summary": summarize_documents(document_results),
        "documents": document_results,
        "failure_taxonomy": FAILURE_TAXONOMY,
    }


def main() -> int:
    try:
        args = parse_args()
        artifact_dir = Path(args.artifact_dir)
        gold_path = Path(args.gold)
        if not artifact_dir.exists() or not artifact_dir.is_dir():
            raise ValueError(f"--artifact_dir must be an existing directory: {artifact_dir}")
        if not gold_path.exists() or not gold_path.is_file():
            raise ValueError(f"--gold must be an existing file: {gold_path}")
        gold = load_gold(gold_path)
        report = build_report(
            artifact_dir=artifact_dir,
            gold_path=gold_path,
            gold=gold,
            run_name=args.run_name,
            parser_version=args.parser_version,
        )
    except Exception as exc:
        print(f"[ERROR] Parser eval failed: {exc}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "parser_eval_summary.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Parser eval summary written: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
