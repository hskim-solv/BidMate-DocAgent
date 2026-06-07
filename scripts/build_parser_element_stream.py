#!/usr/bin/env python3
"""Build a private parser element-stream artifact from candidate outputs.

Harness-only: this does not change canonical ingestion or chunking. It merges
metadata, PyMuPDF4LLM text-control elements, pdfplumber table sidecar elements,
and OCR review winners into the schema documented in
`docs/plans/T-2026-0081-parser-output-merge-schema.md`.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_parser_candidate_eval import (  # noqa: E402
    CandidateEvalError,
    load_manifest_rows,
    load_subset_rows,
    make_doc_id,
    normalize_metadata,
    selected_rows,
    utc_now,
    write_json,
)

SCHEMA_VERSION = 1
DEFAULT_MANIFEST = "data/private/real100_v2/converted_pdfs_by_path/manifest.json"
DEFAULT_SUBSET = ".omx/context/pdf-parser-12doc-subset.json"
DEFAULT_PAGE_AUDIT = (
    "data/private/real100_v2/parser_page_audit/page-audit-96path-routing-v2-20260605T092124Z/page_audit.json"
)
DEFAULT_PARSER_RUN_DIR = "data/private/real100_v2/parser_candidate_eval/parser-12doc-ocr-off-smoke-20260605T050845Z"
DEFAULT_OCR_REVIEW_PACKET = (
    "data/private/real100_v2/ocr_review/ocr-mini-review-row16-row17-20260605T074054Z/review_packet.json"
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_path(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


def text_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def safe_slug(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value).strip("-")[:60] or "element"


def element_id(doc_id: str, candidate: str, element_type: str, page_span: list[int] | None, ordinal: int, text: str) -> str:
    page = f"p{int(page_span[0]):04d}" if page_span else "pmeta"
    return f"{doc_id}:{safe_slug(candidate)}:{page}:{element_type}:{ordinal:04d}:{text_hash(text)}"


def candidate_artifact_path(parser_run_dir: Path, candidate: str, csv_row: int) -> Path:
    return parser_run_dir / "candidates" / candidate / f"row-{csv_row:04d}.json"


def provenance_from_artifact(artifact: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    provenance = dict(artifact.get("provenance") or {})
    return {
        "candidate": artifact.get("candidate"),
        "provider": artifact.get("provider") or "local",
        "candidate_version": artifact.get("candidate_version"),
        "model": provenance.get("model"),
        "generated_at_utc": utc_now(),
        "run_id": run_id,
        "runtime_s": provenance.get("runtime_s"),
        "cost_usd": provenance.get("cost_usd"),
    }


def page_span_or_none(raw: Any) -> list[int] | None:
    if not isinstance(raw, list) or len(raw) != 2:
        return None
    try:
        return [int(raw[0]), int(raw[1])]
    except Exception:  # noqa: BLE001
        return None


def make_element(
    *,
    doc_id: str,
    candidate: str,
    element_type: str,
    source_role: str,
    page_span: list[int] | None,
    bbox: Any,
    text: str,
    structured_payload: Any,
    confidence: float | None,
    citation_ready: bool,
    merge_priority: int,
    route_labels: list[str],
    provenance: dict[str, Any],
    ordinal: int,
) -> dict[str, Any]:
    return {
        "element_id": element_id(doc_id, candidate, element_type, page_span, ordinal, text),
        "element_type": element_type,
        "source_role": source_role,
        "page_span": page_span,
        "bbox": bbox,
        "text": text,
        "structured_payload": structured_payload,
        "confidence": confidence,
        "citation_ready": bool(citation_ready),
        "merge_priority": merge_priority,
        "route_labels": route_labels,
        "provenance": provenance,
    }


def metadata_elements(row: dict[str, Any], *, doc_id: str) -> list[dict[str, Any]]:
    metadata = normalize_metadata(row)
    base_values = {
        "csv_row": str(int(row["csv_row"])),
        "source_file": str(row.get("source_file") or ""),
        "path_pdf": str(row.get("path_pdf") or ""),
        "source_sha256": str(row.get("source_sha256") or ""),
    }
    values = {**base_values, **{str(key): str(value) for key, value in metadata.items() if value not in (None, "")}}
    elements = []
    provenance = {
        "candidate": "metadata",
        "provider": "metadata",
        "candidate_version": None,
        "model": None,
        "generated_at_utc": utc_now(),
        "run_id": None,
        "runtime_s": 0.0,
        "cost_usd": 0.0,
    }
    for ordinal, (key, value) in enumerate(sorted(values.items()), start=1):
        text = f"{key}: {value}"
        elements.append(
            make_element(
                doc_id=doc_id,
                candidate="metadata",
                element_type="metadata_fact",
                source_role="metadata",
                page_span=None,
                bbox=None,
                text=text,
                structured_payload={"key": key, "value": value},
                confidence=None,
                citation_ready=True,
                merge_priority=1,
                route_labels=[],
                provenance=provenance,
                ordinal=ordinal,
            )
        )
    return elements


def route_labels_for_page(route_doc: dict[str, Any] | None, page_span: list[int] | None) -> list[str]:
    if not route_doc or not page_span:
        return []
    page_number = int(page_span[0])
    for page in route_doc.get("pages") or []:
        if isinstance(page, dict) and int(page.get("page") or 0) == page_number:
            return [str(label) for label in page.get("labels") or []]
    return []


def text_control_elements(
    artifact: dict[str, Any],
    *,
    route_doc: dict[str, Any] | None,
    parser_run_id: str,
) -> list[dict[str, Any]]:
    if artifact.get("status") != "ok":
        return []
    doc_id = str(artifact.get("doc_id") or "")
    provenance = provenance_from_artifact(artifact, run_id=parser_run_id)
    elements = []
    ordinal = 1
    for raw in artifact.get("elements") or []:
        if not isinstance(raw, dict) or raw.get("type") == "table":
            continue
        text = str(raw.get("text") or "").strip()
        page_span = page_span_or_none(raw.get("page_span"))
        if not text or not page_span:
            continue
        elements.append(
            make_element(
                doc_id=doc_id,
                candidate=str(artifact.get("candidate") or "pymupdf4llm_current"),
                element_type="text_layer",
                source_role="control",
                page_span=page_span,
                bbox=raw.get("bbox"),
                text=text,
                structured_payload=None,
                confidence=None,
                citation_ready=True,
                merge_priority=10,
                route_labels=route_labels_for_page(route_doc, page_span),
                provenance=provenance,
                ordinal=ordinal,
            )
        )
        ordinal += 1
    return elements


def table_sidecar_elements(
    artifact: dict[str, Any],
    *,
    route_doc: dict[str, Any] | None,
    parser_run_id: str,
) -> list[dict[str, Any]]:
    if artifact.get("status") != "ok":
        return []
    doc_id = str(artifact.get("doc_id") or "")
    provenance = provenance_from_artifact(artifact, run_id=parser_run_id)
    elements = []
    ordinal = 1
    for raw in artifact.get("elements") or []:
        if not isinstance(raw, dict) or raw.get("type") != "table":
            continue
        text = str(raw.get("text") or "").strip()
        page_span = page_span_or_none(raw.get("page_span"))
        if not text or not page_span:
            continue
        elements.append(
            make_element(
                doc_id=doc_id,
                candidate=str(artifact.get("candidate") or "pdfplumber_table_sidecar"),
                element_type="table",
                source_role="sidecar",
                page_span=page_span,
                bbox=raw.get("bbox"),
                text=text,
                structured_payload={"table_id": raw.get("table_id")},
                confidence=None,
                citation_ready=True,
                merge_priority=20,
                route_labels=route_labels_for_page(route_doc, page_span),
                provenance=provenance,
                ordinal=ordinal,
            )
        )
        ordinal += 1
    return elements


def reviewed_ocr_elements(ocr_review_packet: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    by_row: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for page in ocr_review_packet.get("pages") or []:
        if not isinstance(page, dict):
            continue
        review = page.get("review") if isinstance(page.get("review"), dict) else {}
        winner = str(review.get("winner") or "")
        if not winner:
            continue
        csv_row = int(page.get("csv_row") or 0)
        page_number = int(page.get("page") or 0)
        doc_id = str(page.get("doc_id") or "")
        route_labels = [str(label) for label in (page.get("audit") or {}).get("labels") or []]
        for candidate in page.get("candidates") or []:
            if not isinstance(candidate, dict) or candidate.get("candidate") != winner:
                continue
            text = str(candidate.get("text") or "").strip()
            if not text:
                continue
            provenance = dict(candidate.get("provenance") or {})
            provenance = {
                "candidate": winner,
                "provider": "local",
                "candidate_version": provenance.get("versions", {}).get("paddleocr")
                if isinstance(provenance.get("versions"), dict)
                else None,
                "model": provenance.get("model"),
                "generated_at_utc": utc_now(),
                "run_id": (ocr_review_packet.get("run") or {}).get("run_id"),
                "runtime_s": candidate.get("runtime_s"),
                "cost_usd": provenance.get("cost_usd", 0.0),
            }
            by_row[csv_row].append(
                make_element(
                    doc_id=doc_id,
                    candidate=winner,
                    element_type="ocr_text",
                    source_role="routed_ocr",
                    page_span=[page_number, page_number],
                    bbox=None,
                    text=text,
                    structured_payload={
                        "review_status": review.get("status"),
                        "review_winner": winner,
                        "required_facts": review.get("required_facts") or [],
                    },
                    confidence=candidate.get("avg_confidence"),
                    citation_ready=True,
                    merge_priority=30,
                    route_labels=route_labels,
                    provenance=provenance,
                    ordinal=len(by_row[csv_row]) + 1,
                )
            )
    return by_row


def load_page_audit_by_row(path: Path) -> dict[int, dict[str, Any]]:
    data = read_json(path)
    run_id = (data.get("run") or {}).get("run_id")
    by_row: dict[int, dict[str, Any]] = {}
    for doc in data.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        csv_row = int(doc.get("csv_row") or 0)
        copy = dict(doc)
        copy["_page_audit_run_id"] = run_id
        by_row[csv_row] = copy
    return by_row


def build_document(
    row: dict[str, Any],
    *,
    route_doc: dict[str, Any] | None,
    parser_run_dir: Path,
    parser_run_id: str,
    reviewed_ocr_by_row: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    csv_row = int(row["csv_row"])
    doc_id = make_doc_id(row)
    elements = metadata_elements(row, doc_id=doc_id)

    text_artifact_path = candidate_artifact_path(parser_run_dir, "pymupdf4llm_current", csv_row)
    if text_artifact_path.exists():
        elements.extend(text_control_elements(read_json(text_artifact_path), route_doc=route_doc, parser_run_id=parser_run_id))

    table_artifact_path = candidate_artifact_path(parser_run_dir, "pdfplumber_table_sidecar", csv_row)
    if table_artifact_path.exists():
        elements.extend(table_sidecar_elements(read_json(table_artifact_path), route_doc=route_doc, parser_run_id=parser_run_id))

    elements.extend(reviewed_ocr_by_row.get(csv_row, []))
    elements.sort(key=lambda item: (int(item.get("merge_priority") or 999), item.get("page_span") or [0, 0], item["element_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "parser_element_stream",
        "doc_id": doc_id,
        "csv_row": csv_row,
        "source_file": row.get("source_file"),
        "path_pdf": row.get("path_pdf"),
        "source_sha256": row.get("source_sha256"),
        "metadata": {"csv": normalize_metadata(row), "normalized": {}},
        "route_summary": {
            "page_audit_run_id": (route_doc or {}).get("_page_audit_run_id"),
            "route_counts": (route_doc or {}).get("route_counts") or {},
            "label_counts": (route_doc or {}).get("label_counts") or {},
        },
        "elements": elements,
    }


def aggregate_documents(run_manifest: dict[str, Any], documents: list[dict[str, Any]]) -> dict[str, Any]:
    element_type_counts = Counter()
    source_role_counts = Counter()
    citation_ready_counts = Counter()
    by_doc = []
    for doc in documents:
        elements = doc.get("elements") or []
        element_type_counts.update(str(element.get("element_type") or "unknown") for element in elements)
        source_role_counts.update(str(element.get("source_role") or "unknown") for element in elements)
        citation_ready_counts.update("true" if element.get("citation_ready") else "false" for element in elements)
        by_doc.append(
            {
                "csv_row": doc.get("csv_row"),
                "doc_id": doc.get("doc_id"),
                "source_sha256": doc.get("source_sha256"),
                "elements": len(elements),
                "element_type_counts": dict(Counter(str(element.get("element_type") or "unknown") for element in elements)),
                "source_role_counts": dict(Counter(str(element.get("source_role") or "unknown") for element in elements)),
                "route_counts": (doc.get("route_summary") or {}).get("route_counts"),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "parser_element_stream_aggregate",
        "generated_at_utc": utc_now(),
        "run": run_manifest,
        "summary": {
            "documents": len(documents),
            "elements": sum(len(doc.get("elements") or []) for doc in documents),
            "element_type_counts": dict(sorted(element_type_counts.items())),
            "source_role_counts": dict(sorted(source_role_counts.items())),
            "citation_ready_counts": dict(sorted(citation_ready_counts.items())),
        },
        "documents": sorted(by_doc, key=lambda item: int(item.get("csv_row") or 0)),
    }


def write_markdown_summary(path: Path, aggregate: dict[str, Any]) -> None:
    summary = aggregate.get("summary") or {}
    run = aggregate.get("run") or {}
    lines = ["# Parser Element Stream Aggregate", ""]
    lines.append(f"- Run ID: `{run.get('run_id')}`")
    lines.append(f"- Generated: `{aggregate.get('generated_at_utc')}`")
    lines.append(f"- Documents: `{summary.get('documents')}`")
    lines.append(f"- Elements: `{summary.get('elements')}`")
    lines.append(f"- Element types: `{summary.get('element_type_counts')}`")
    lines.append(f"- Source roles: `{summary.get('source_role_counts')}`")
    lines.append(f"- Citation ready: `{summary.get('citation_ready_counts')}`")
    lines.append("")
    lines.append("This aggregate intentionally omits raw element text. See private element_stream.json for text payloads.")
    lines.append("")
    lines.append("| csv_row | elements | element types | source roles | routes |")
    lines.append("|---:|---:|---|---|---|")
    for doc in aggregate.get("documents") or []:
        lines.append(
            f"| {doc.get('csv_row')} | {doc.get('elements')} | `{doc.get('element_type_counts')}` | "
            f"`{doc.get('source_role_counts')}` | `{doc.get('route_counts')}` |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def out_dir_default(run_id: str) -> Path:
    return REPO_ROOT / "data/private/real100_v2/parser_element_stream" / run_id


def report_dir_default(run_id: str) -> Path:
    return REPO_ROOT / "reports/parser_candidate_eval" / run_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build harness-only parser element stream.")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--subset", default=DEFAULT_SUBSET)
    parser.add_argument("--page-audit", default=DEFAULT_PAGE_AUDIT)
    parser.add_argument("--parser-run-dir", default=DEFAULT_PARSER_RUN_DIR)
    parser.add_argument("--ocr-review-packet", default=DEFAULT_OCR_REVIEW_PACKET)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--report-dir", default=None)
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        run_id = args.run_id or f"parser-element-stream-{utc_now()}"
        out_dir = Path(args.out_dir) if args.out_dir else out_dir_default(run_id)
        report_dir = Path(args.report_dir) if args.report_dir else report_dir_default(run_id)
        manifest_path = normalize_path(args.manifest)
        subset_path = normalize_path(args.subset)
        page_audit_path = normalize_path(args.page_audit)
        parser_run_dir = normalize_path(args.parser_run_dir)
        ocr_review_path = normalize_path(args.ocr_review_packet)
        manifest = load_manifest_rows(manifest_path)
        rows = selected_rows(manifest, load_subset_rows(subset_path))
        page_audit_by_row = load_page_audit_by_row(page_audit_path)
        ocr_review_packet = read_json(ocr_review_path) if ocr_review_path.exists() else {"pages": []}
        reviewed_ocr_by_row = reviewed_ocr_elements(ocr_review_packet)
        parser_run_id = parser_run_dir.name
        run_manifest = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "generated_at_utc": utc_now(),
            "manifest": str(manifest_path),
            "subset": str(subset_path),
            "page_audit": str(page_audit_path),
            "parser_run_dir": str(parser_run_dir),
            "ocr_review_packet": str(ocr_review_path),
            "out_dir": str(out_dir),
            "report_dir": str(report_dir),
            "documents": len(rows),
        }
        documents = [
            build_document(
                row,
                route_doc=page_audit_by_row.get(int(row["csv_row"])),
                parser_run_dir=parser_run_dir,
                parser_run_id=parser_run_id,
                reviewed_ocr_by_row=reviewed_ocr_by_row,
            )
            for row in rows
        ]
        stream = {
            "schema_version": SCHEMA_VERSION,
            "mode": "parser_element_stream_run",
            "generated_at_utc": utc_now(),
            "run": run_manifest,
            "documents": documents,
        }
        write_json(out_dir / "element_stream.json", stream)
        for doc in documents:
            write_json(out_dir / "documents" / f"row-{int(doc['csv_row']):04d}.json", doc)
        aggregate = aggregate_documents(run_manifest, documents)
        write_json(report_dir / "element_stream.aggregate.json", aggregate)
        write_markdown_summary(report_dir / "element_stream.md", aggregate)
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "out_dir": str(out_dir),
                    "report_dir": str(report_dir),
                    "documents": aggregate["summary"]["documents"],
                    "elements": aggregate["summary"]["elements"],
                    "element_type_counts": aggregate["summary"]["element_type_counts"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except CandidateEvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
