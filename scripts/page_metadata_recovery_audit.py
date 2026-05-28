#!/usr/bin/env python3
"""Aggregate-only page metadata recovery audit.

This script answers one narrow question: can page citation metadata be recovered
from existing local artifacts, or is a page-aware parser rebuild required?

It intentionally does not import or call retrieval, verifier, prompt, answer, or
index-writing code. Outputs are aggregate-only: no raw chunk text, doc_ids,
filenames, source paths, or private snippets.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from parser_page_metadata_contract import classify_parser_source_group


SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
PAGE_LIKE_KEY_RE = re.compile(r"page|bbox|region", re.IGNORECASE)
ABSOLUTE_PATH_VALUE_RE = re.compile(
    r"(^|[\s\"'`])(/Users/|/private/|/tmp/|/var/|/home/|/Volumes/|[A-Za-z]:\\)"
)
FILENAME_VALUE_RE = re.compile(
    r"(^|[\s\"'`])[^/\s\"'`]+\.(pdf|hwp|hwpx|docx|xlsx|csv|jsonl|md|txt)\b",
    re.IGNORECASE,
)
DEFAULT_OUT_JSON = _REPO_ROOT / "reports" / "real100_v2" / "page_metadata_readiness.aggregate.json"
DEFAULT_OUT_MD = _REPO_ROOT / "docs" / "evaluation" / "real100_v2-page-metadata-readiness.md"
PREFERRED_MINILM_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _safe_label(value: Any) -> str:
    label = str(value or "").strip()
    if not label:
        return "<missing>"
    return label if SAFE_LABEL_RE.fullmatch(label) else "<redacted_label>"


def _embedding_block(index_payload: Mapping[str, Any]) -> dict[str, Any]:
    embedding = index_payload.get("embedding") if isinstance(index_payload.get("embedding"), Mapping) else {}
    backend = _safe_label(embedding.get("backend"))
    model = str(embedding.get("model") or "").strip()
    if model:
        model = model.replace("/", "__")
    if not SAFE_LABEL_RE.fullmatch(model):
        model = "<redacted_label>" if model else "<missing>"
    try:
        dimension = int(embedding.get("dimension"))
    except (TypeError, ValueError):
        dimension = None
    return {"backend": backend, "model": model, "dimension": dimension}


def _private_eval_index_guard(
    embedding: Mapping[str, Any],
    chunk_coverage: Mapping[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    if embedding.get("backend") == "hashing":
        reasons.append("hashing_embeddings_forbidden")
    if embedding.get("backend") != "sentence-transformers" or embedding.get("model") != PREFERRED_MINILM_MODEL:
        reasons.append("minilm_semantic_baseline_required")
    if float(chunk_coverage.get("any_page_metadata_coverage") or 0.0) <= 0.0:
        reasons.append("chunk_page_metadata_coverage_zero")
    return {
        "status": "GO" if not reasons else "NO-GO",
        "reasons": reasons,
    }


def _load_json(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "missing"
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"unreadable:{type(exc).__name__}"
    if not isinstance(payload, dict):
        return {}, "not_object"
    return payload, None


def _is_page_span(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    return all(isinstance(page, int) for page in value)


def _is_bbox(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    try:
        [float(part) for part in value]
    except (TypeError, ValueError):
        return False
    return True


def _regions(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _has_region_page(item: Mapping[str, Any]) -> bool:
    return any(isinstance(region.get("page_number"), int) for region in _regions(item.get("regions")))


def _has_region_bbox(item: Mapping[str, Any]) -> bool:
    return any(_is_bbox(region.get("bbox")) for region in _regions(item.get("regions")))


def _has_page_metadata(item: Mapping[str, Any]) -> bool:
    return _is_page_span(item.get("page_span")) or _has_region_page(item)


def coverage_block(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(items)
    page_span = sum(1 for item in items if _is_page_span(item.get("page_span")))
    region_page = sum(1 for item in items if _has_region_page(item))
    region_bbox = sum(1 for item in items if _has_region_bbox(item))
    any_page = sum(1 for item in items if _has_page_metadata(item))
    return {
        "count": total,
        "with_any_page_metadata_count": any_page,
        "with_page_span_count": page_span,
        "with_regions_page_number_count": region_page,
        "with_regions_bbox_count": region_bbox,
        "any_page_metadata_coverage": _rate(any_page, total),
        "page_span_coverage": _rate(page_span, total),
        "regions_page_number_coverage": _rate(region_page, total),
        "regions_bbox_coverage": _rate(region_bbox, total),
    }


def _metadata_for(item: Mapping[str, Any], docs_by_id: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    doc = docs_by_id.get(str(item.get("doc_id") or ""))
    doc_metadata = doc.get("metadata") if isinstance(doc, Mapping) else None
    fallback = dict(doc_metadata) if isinstance(doc_metadata, Mapping) else {}
    metadata = item.get("metadata")
    if isinstance(metadata, Mapping):
        fallback.update(
            {
                key: value
                for key, value in metadata.items()
                if value not in (None, "", [])
            }
        )
    return fallback


def _source_group_key(
    item: Mapping[str, Any],
    docs_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str, str, str]:
    metadata = _metadata_for(item, docs_by_id)
    return (
        _safe_label(metadata.get("file_format")),
        _safe_label(metadata.get("text_source")),
        _safe_label(metadata.get("document_type")),
        _safe_label(item.get("chunking_strategy")),
    )


def _group_decision(group: Mapping[str, Any]) -> str:
    if group["any_page_metadata_coverage"] > 0:
        return "page_metadata_available"
    file_format = group["file_format"]
    text_source = group["text_source"]
    if text_source == "data_list_csv_text":
        return "requires_raw_source_reparse"
    if file_format == "hwp" and text_source == "kordoc":
        return "requires_page_aware_hwp_parser_change"
    if file_format == "pdf" and text_source == "kordoc":
        return "requires_pdf_visual_ingestion_or_page_aware_parser"
    return "requires_page_aware_reindex"


def _source_type(group: Mapping[str, Any]) -> str:
    file_format = str(group.get("file_format") or "")
    text_source = str(group.get("text_source") or "")
    document_type = str(group.get("document_type") or "")
    if float(group.get("any_page_metadata_coverage") or 0.0) > 0:
        return "existing_index_with_page_fields"
    if float(group.get("parent_any_page_metadata_coverage") or 0.0) > 0:
        return "existing_index_parent_only_page_fields"
    if document_type == "public_fixture_smoke":
        return "public_json_md_fixtures"
    if "visual" in text_source or "visual" in document_type:
        return "visual_pdf_image_artifacts"
    if text_source == "data_list_csv_text":
        return "csv_text_fallback"
    if file_format == "pdf" and text_source == "kordoc":
        return "pdf_via_kordoc_or_csv_text"
    if file_format == "hwp" and text_source == "kordoc":
        return "hwp_via_kordoc"
    return "existing_index_with_no_page_fields"


def _matrix_row_for_group(group: Mapping[str, Any]) -> dict[str, Any]:
    source_type = _source_type(group)
    coverage = float(group.get("any_page_metadata_coverage") or 0.0)
    parent_coverage = float(group.get("parent_any_page_metadata_coverage") or 0.0)

    matrix_by_type: dict[str, dict[str, Any]] = {
        "existing_index_with_page_fields": {
            "recoverable": True,
            "requires_parser_change": False,
            "requires_reindex": False,
            "requires_ocr_visual_ingestion": False,
            "estimated_engineering_cost": "S",
            "expected_eval_impact": "Citation page claims can be GO for covered source groups.",
        },
        "existing_index_parent_only_page_fields": {
            "recoverable": True,
            "requires_parser_change": False,
            "requires_reindex": True,
            "requires_ocr_visual_ingestion": False,
            "estimated_engineering_cost": "S-M",
            "expected_eval_impact": "Citation page coverage can become GO after rechunk/reindex.",
        },
        "visual_pdf_image_artifacts": {
            "recoverable": True,
            "requires_parser_change": False,
            "requires_reindex": True,
            "requires_ocr_visual_ingestion": False,
            "estimated_engineering_cost": "M",
            "expected_eval_impact": "Strongest near-term page citation lift for PDFs/images.",
        },
        "pdf_via_kordoc_or_csv_text": {
            "recoverable": False,
            "requires_parser_change": True,
            "requires_reindex": True,
            "requires_ocr_visual_ingestion": True,
            "estimated_engineering_cost": "M-L",
            "expected_eval_impact": "Page citation GO only after parser output carries page spans.",
        },
        "hwp_via_kordoc": {
            "recoverable": False,
            "requires_parser_change": True,
            "requires_reindex": True,
            "requires_ocr_visual_ingestion": False,
            "estimated_engineering_cost": "M-L",
            "expected_eval_impact": "Page citation GO requires page-aware HWP extraction or render+visual path.",
        },
        "csv_text_fallback": {
            "recoverable": False,
            "requires_parser_change": False,
            "requires_reindex": True,
            "requires_ocr_visual_ingestion": False,
            "estimated_engineering_cost": "S-M",
            "expected_eval_impact": "Low confidence unless raw source can be reparsed.",
        },
        "public_json_md_fixtures": {
            "recoverable": bool(coverage or parent_coverage),
            "requires_parser_change": False,
            "requires_reindex": True,
            "requires_ocr_visual_ingestion": False,
            "estimated_engineering_cost": "S",
            "expected_eval_impact": "Useful regression fixture, not a real performance claim.",
        },
        "existing_index_with_no_page_fields": {
            "recoverable": False,
            "requires_parser_change": False,
            "requires_reindex": True,
            "requires_ocr_visual_ingestion": False,
            "estimated_engineering_cost": "S",
            "expected_eval_impact": "Enables coverage measurement only after rebuild.",
        },
    }
    row = dict(matrix_by_type[source_type])
    row.update(
        {
            "source_type": source_type,
            "current_coverage": coverage,
            "parent_current_coverage": parent_coverage,
            "source_group": _format_source_group(group),
            "decision": group["decision"],
        }
    )
    return row


def _format_source_group(group: Mapping[str, Any]) -> str:
    return (
        f"file_format={group['file_format']}, text_source={group['text_source']}, "
        f"document_type={group['document_type']}, chunking_strategy={group['chunking_strategy']}"
    )


def implementation_matrix(source_groups: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [_matrix_row_for_group(group) for group in source_groups]


def _page_span_integrity(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    checked = 0
    invalid = 0
    region_outside_span = 0
    for item in items:
        page_span = item.get("page_span")
        if page_span is None:
            continue
        checked += 1
        if not _is_page_span(page_span) or int(page_span[0]) > int(page_span[1]):
            invalid += 1
            continue
        start, end = int(page_span[0]), int(page_span[1])
        for region in _regions(item.get("regions")):
            page_number = region.get("page_number")
            if isinstance(page_number, int) and not (start <= page_number <= end):
                region_outside_span += 1
    return {
        "checked_count": checked,
        "invalid_page_span_count": invalid,
        "region_outside_page_span_count": region_outside_span,
        "ok": invalid == 0 and region_outside_span == 0,
    }


def readiness_checks(
    chunks: Sequence[Mapping[str, Any]],
    report_payload: Mapping[str, Any],
) -> dict[str, Any]:
    chunk_coverage = coverage_block(chunks)
    integrity = _page_span_integrity(chunks)
    return {
        "page_metadata_coverage_gt_0": chunk_coverage["any_page_metadata_coverage"] > 0,
        "chunk_page_span_integrity": integrity,
        "citation_renderer_compatible": integrity["ok"],
        "no_private_path_leakage": not _has_private_path_or_filename_value(report_payload),
        "aggregate_only_outputs": bool(
            (report_payload.get("privacy") or {}).get("aggregate_only")
        ),
    }


def _iter_string_values(node: Any) -> Iterable[str]:
    if isinstance(node, Mapping):
        for value in node.values():
            yield from _iter_string_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_string_values(item)
    elif isinstance(node, str):
        yield node


def _has_private_path_or_filename_value(payload: Mapping[str, Any]) -> bool:
    for value in _iter_string_values(payload):
        if ABSOLUTE_PATH_VALUE_RE.search(value) or FILENAME_VALUE_RE.search(value):
            return True
    return False


def recovery_recommendation(recoverability: str, requires_reindex: bool) -> str:
    if not requires_reindex and recoverability == "recoverable_from_current_index":
        return "lightweight metadata recovery"
    if recoverability == "possibly_recoverable_from_kordoc_cache_requires_adapter":
        return "parser patch"
    if recoverability == "recoverable_from_visual_artifacts_requires_reindex":
        return "visual ingestion rebuild"
    if requires_reindex:
        return "full re-index"
    return "impossible with current artifacts"


def source_group_coverage(
    chunks: Sequence[Mapping[str, Any]],
    parent_sections: Sequence[Mapping[str, Any]],
    documents: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    docs_by_id = {str(doc.get("doc_id") or ""): doc for doc in documents}
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for chunk in chunks:
        key = _source_group_key(chunk, docs_by_id)
        group = grouped.setdefault(
            key,
            {
                "file_format": key[0],
                "text_source": key[1],
                "document_type": key[2],
                "chunking_strategy": key[3],
                "_doc_ids": set(),
                "_chunks": [],
                "_parents": [],
            },
        )
        group["_chunks"].append(chunk)
        if chunk.get("doc_id"):
            group["_doc_ids"].add(str(chunk.get("doc_id")))

    for parent in parent_sections:
        key = _source_group_key(parent, docs_by_id)
        group = grouped.setdefault(
            key,
            {
                "file_format": key[0],
                "text_source": key[1],
                "document_type": key[2],
                "chunking_strategy": key[3],
                "_doc_ids": set(),
                "_chunks": [],
                "_parents": [],
            },
        )
        group["_parents"].append(parent)
        if parent.get("doc_id"):
            group["_doc_ids"].add(str(parent.get("doc_id")))

    results: list[dict[str, Any]] = []
    for group in sorted(grouped.values(), key=lambda item: (
        item["file_format"],
        item["text_source"],
        item["document_type"],
        item["chunking_strategy"],
    )):
        chunk_block = coverage_block(group["_chunks"])
        parent_block = coverage_block(group["_parents"])
        result = {
            "file_format": group["file_format"],
            "text_source": group["text_source"],
            "document_type": group["document_type"],
            "chunking_strategy": group["chunking_strategy"],
            "doc_count": len(group["_doc_ids"]),
            "chunk_count": chunk_block["count"],
            "parent_section_count": parent_block["count"],
            "any_page_metadata_coverage": chunk_block["any_page_metadata_coverage"],
            "page_span_coverage": chunk_block["page_span_coverage"],
            "regions_page_number_coverage": chunk_block["regions_page_number_coverage"],
            "regions_bbox_coverage": chunk_block["regions_bbox_coverage"],
            "parent_any_page_metadata_coverage": parent_block["any_page_metadata_coverage"],
        }
        result["page_metadata_capability"] = classify_parser_source_group(
            file_format=result["file_format"],
            text_source=result["text_source"],
            document_type=result["document_type"],
            any_page_metadata_coverage=result["any_page_metadata_coverage"],
            parent_any_page_metadata_coverage=result["parent_any_page_metadata_coverage"],
        )
        result["decision"] = _group_decision(result)
        results.append(result)
    return results


def _count_page_like_keys(node: Any) -> Counter[str]:
    counts: Counter[str] = Counter()
    if isinstance(node, Mapping):
        for key, value in node.items():
            key_text = str(key)
            if PAGE_LIKE_KEY_RE.search(key_text):
                counts[key_text] += 1
            counts.update(_count_page_like_keys(value))
    elif isinstance(node, list):
        for item in node:
            counts.update(_count_page_like_keys(item))
    return counts


def ingestion_report_audit(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"present": False, "status": "not_provided"}
    payload, error = _load_json(path)
    if error:
        return {"present": False, "status": error}
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    text_source_counts = summary.get("text_source_counts") if isinstance(summary, Mapping) else {}
    page_keys = _count_page_like_keys(payload)
    return {
        "present": True,
        "status": "ok",
        "has_text_source_counts": isinstance(text_source_counts, Mapping),
        "page_like_key_counts": dict(sorted(page_keys.items())),
        "has_page_like_keys": bool(page_keys),
    }


def kordoc_cache_audit(cache_dir: Path | None) -> dict[str, Any]:
    if cache_dir is None:
        return {"present": False, "status": "not_provided"}
    if not cache_dir.is_dir():
        return {"present": False, "status": "missing"}

    manifest_payload, manifest_error = _load_json(cache_dir / "manifest.json")
    entries = manifest_payload.get("entries") if isinstance(manifest_payload.get("entries"), Mapping) else {}
    entry_key_counts: Counter[str] = Counter()
    if isinstance(entries, Mapping):
        for entry in entries.values():
            if isinstance(entry, Mapping):
                entry_key_counts.update(str(key) for key in entry.keys())

    marker_counts = Counter()
    md_count = 0
    for md_path in cache_dir.glob("*.md"):
        md_count += 1
        try:
            text = md_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lower = text.lower()
        marker_counts["formfeed_files"] += int("\f" in text)
        marker_counts["html_page_break_files"] += int("page-break" in lower)
        marker_counts["markdown_page_marker_files"] += int(
            any(marker in lower for marker in ("page_number", "page number", "<!-- page", "[[page"))
        )

    page_like_entry_keys = {
        key: count
        for key, count in entry_key_counts.items()
        if PAGE_LIKE_KEY_RE.search(key)
    }
    return {
        "present": True,
        "status": "ok",
        "manifest_present": manifest_error is None,
        "manifest_status": manifest_error or "ok",
        "manifest_entry_count": len(entries) if isinstance(entries, Mapping) else 0,
        "manifest_entry_key_counts": dict(sorted(entry_key_counts.items())),
        "manifest_has_page_like_keys": bool(page_like_entry_keys),
        "manifest_page_like_key_counts": dict(sorted(page_like_entry_keys.items())),
        "markdown_file_count": md_count,
        "markdown_page_marker_file_counts": dict(sorted(marker_counts.items())),
        "markdown_has_page_markers": any(marker_counts.values()),
    }


def _iter_visual_artifact_paths(artifact_dir: Path) -> Iterable[Path]:
    yield from artifact_dir.glob("*.visual.json")
    for path in artifact_dir.glob("*.json"):
        if path.name.endswith(".visual.json"):
            continue
        yield path


def visual_artifact_audit(artifact_dir: Path | None) -> dict[str, Any]:
    if artifact_dir is None:
        return {"present": False, "status": "not_provided"}
    if not artifact_dir.is_dir():
        return {"present": False, "status": "missing"}

    artifact_count = 0
    page_count = 0
    section_count = 0
    sections_with_page = 0
    blocks_with_page = 0
    blocks_with_bbox = 0
    for path in _iter_visual_artifact_paths(artifact_dir):
        payload, error = _load_json(path)
        if error:
            continue
        artifact_count += 1
        pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
        sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
        page_count += len(pages)
        for section in sections:
            if not isinstance(section, Mapping):
                continue
            section_count += 1
            sections_with_page += int(_has_page_metadata(section))
        for page in pages:
            if not isinstance(page, Mapping):
                continue
            blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
            for block in blocks:
                if not isinstance(block, Mapping):
                    continue
                blocks_with_page += int(isinstance(block.get("page_number"), int))
                blocks_with_bbox += int(_is_bbox(block.get("bbox")))

    section_page_coverage = _rate(sections_with_page, section_count)
    return {
        "present": True,
        "status": "ok",
        "artifact_count": artifact_count,
        "page_count": page_count,
        "section_count": section_count,
        "sections_with_any_page_metadata_count": sections_with_page,
        "section_page_metadata_coverage": section_page_coverage,
        "blocks_with_page_number_count": blocks_with_page,
        "blocks_with_bbox_count": blocks_with_bbox,
        "has_recoverable_page_metadata": sections_with_page > 0 or blocks_with_page > 0,
        "page_metadata_capability": classify_parser_source_group(
            text_source="visual_artifacts",
            document_type="visual_artifacts",
            any_page_metadata_coverage=section_page_coverage,
        ),
    }


def _artifact_recoverability(
    chunk_coverage: Mapping[str, Any],
    parent_coverage: Mapping[str, Any],
    visual_artifacts: Mapping[str, Any],
    kordoc_cache: Mapping[str, Any],
) -> str:
    if chunk_coverage["any_page_metadata_coverage"] > 0:
        return "recoverable_from_current_index"
    if parent_coverage["any_page_metadata_coverage"] > 0:
        return "recoverable_from_parent_sections_requires_rechunk"
    if visual_artifacts.get("has_recoverable_page_metadata"):
        return "recoverable_from_visual_artifacts_requires_reindex"
    if kordoc_cache.get("manifest_has_page_like_keys") or kordoc_cache.get("markdown_has_page_markers"):
        return "possibly_recoverable_from_kordoc_cache_requires_adapter"
    return "not_recoverable_from_existing_artifacts"


def _requires_parser_change(source_groups: Sequence[Mapping[str, Any]], recoverability: str) -> bool:
    if recoverability in {
        "recoverable_from_current_index",
        "recoverable_from_parent_sections_requires_rechunk",
        "recoverable_from_visual_artifacts_requires_reindex",
    }:
        return False
    return any(
        group["decision"]
        in {
            "requires_page_aware_hwp_parser_change",
            "requires_pdf_visual_ingestion_or_page_aware_parser",
        }
        for group in source_groups
    )


def build_audit_report(
    index_dir: Path,
    *,
    ingestion_report_path: Path | None = None,
    kordoc_cache_dir: Path | None = None,
    visual_artifact_dir: Path | None = None,
) -> dict[str, Any]:
    index_payload, index_error = _load_json(index_dir / "index.json")
    if index_error:
        return {
            "schema_version": 1,
            "status": "failed",
            "error": f"index_json_{index_error}",
            "index_dir_provided": True,
        }

    chunks = [item for item in index_payload.get("chunks") or [] if isinstance(item, Mapping)]
    documents = [item for item in index_payload.get("documents") or [] if isinstance(item, Mapping)]
    parent_sections = [
        item for item in index_payload.get("parent_sections") or [] if isinstance(item, Mapping)
    ]
    chunk_coverage = coverage_block(chunks)
    document_coverage = coverage_block(documents)
    parent_coverage = coverage_block(parent_sections)
    embedding_payload = index_payload.get("embedding") if isinstance(index_payload.get("embedding"), Mapping) else {}
    embedding = _embedding_block(index_payload)
    private_eval_guard = _private_eval_index_guard(embedding_payload, chunk_coverage)
    source_groups = source_group_coverage(chunks, parent_sections, documents)

    ingestion_report_path = ingestion_report_path or (
        index_dir / "ingestion_report.json" if (index_dir / "ingestion_report.json").exists() else None
    )
    ingestion = ingestion_report_audit(ingestion_report_path)
    kordoc = kordoc_cache_audit(kordoc_cache_dir)
    visual = visual_artifact_audit(visual_artifact_dir)

    max_source_page_coverage = max(
        (float(group["any_page_metadata_coverage"]) for group in source_groups),
        default=0.0,
    )
    recoverability = _artifact_recoverability(chunk_coverage, parent_coverage, visual, kordoc)
    requires_reindex = recoverability != "recoverable_from_current_index"
    requires_parser_change = _requires_parser_change(source_groups, recoverability)
    privacy = {
        "aggregate_only": True,
        "omits_raw_text": True,
        "omits_doc_ids": True,
        "omits_chunk_ids": True,
        "omits_file_names": True,
        "omits_source_paths": True,
    }
    matrix = implementation_matrix(source_groups)
    report = {
        "schema_version": 1,
        "profile_type": "private_real100_v2_page_metadata_readiness",
        "status": "ok",
        "privacy": privacy,
        "index": {
            "schema_version": index_payload.get("schema_version"),
            "document_count": len(documents),
            "chunk_count": len(chunks),
            "parent_section_count": len(parent_sections),
            "embedding": embedding,
            "chunk": chunk_coverage,
            "document": document_coverage,
            "parent_section": parent_coverage,
            "source_groups": source_groups,
        },
        "artifacts": {
            "ingestion_report": ingestion,
            "kordoc_cache": kordoc,
            "visual_artifacts": visual,
        },
        "implementation_matrix": matrix,
        "decision": {
            "citation_page_claim_go_no_go": "GO" if max_source_page_coverage > 0 else "NO-GO",
            "private_real_eval_index_go_no_go": private_eval_guard["status"],
            "private_real_eval_index_no_go_reasons": private_eval_guard["reasons"],
            "page_claim_scope": (
                "covered_source_groups_only" if max_source_page_coverage > 0 else "not_supported"
            ),
            "recoverability": recoverability,
            "recoverable_from_existing_local_artifacts": recoverability
            != "not_recoverable_from_existing_artifacts",
            "requires_reindex": requires_reindex,
            "requires_parser_change": requires_parser_change,
            "current_index_behavior_change": False,
            "retrieval_verifier_prompt_answer_change": False,
            "recommendation": recovery_recommendation(recoverability, requires_reindex),
        },
        "follow_up_issue_plan": [
            "Keep page-level citation claims disabled while source-group page coverage is zero.",
            "Run a page-aware rebuild spike for page-blind PDF and HWP source groups and verify non-zero regions.page_number coverage.",
            "Evaluate page-aware HWP extraction or an adapter that emits sections[].regions or sections[].page_span.",
            "Rebuild the private index only after page-aware parser output populates sections[].regions or sections[].page_span.",
            "Commit only aggregate reports; keep private raw content, filenames, doc_ids, and source paths out of artifacts.",
        ],
    }
    report["readiness_checks"] = readiness_checks(chunks, report)
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    if report.get("status") != "ok":
        return f"# real100_v2 Page Metadata Recovery Audit\n\n- Status: `{report.get('status')}`\n"

    decision = report["decision"]
    index = report["index"]
    lines = [
        "# real100_v2 Page Metadata Recovery Audit",
        "",
        "## Decision",
        f"- Citation page claim: `{decision['citation_page_claim_go_no_go']}`",
        f"- Private real-eval index: `{decision['private_real_eval_index_go_no_go']}`",
        f"- Private real-eval index no-go reasons: `{', '.join(decision['private_real_eval_index_no_go_reasons']) or '-'}`",
        f"- Recoverability: `{decision['recoverability']}`",
        f"- Requires re-index: `{decision['requires_reindex']}`",
        f"- Requires parser change: `{decision['requires_parser_change']}`",
        f"- Retrieval/verifier/prompt/answer behavior change: `{decision['retrieval_verifier_prompt_answer_change']}`",
        f"- Embedding backend/model/dim: `{index['embedding']['backend']}` / `{index['embedding']['model']}` / `{index['embedding']['dimension']}`",
        "",
        "## Coverage",
        f"- Documents / chunks / parent sections: `{index['document_count']}` / `{index['chunk_count']}` / `{index['parent_section_count']}`",
        f"- Chunk page metadata coverage: `{index['chunk']['any_page_metadata_coverage']}`",
        f"- Chunk page_span coverage: `{index['chunk']['page_span_coverage']}`",
        f"- Chunk regions.page_number coverage: `{index['chunk']['regions_page_number_coverage']}`",
        f"- Chunk regions.bbox coverage: `{index['chunk']['regions_bbox_coverage']}`",
        "",
        "## Source Groups",
    ]
    for group in index["source_groups"]:
        lines.append(
            "- "
            f"`{_format_source_group(group)}`: "
            f"docs=`{group['doc_count']}`, chunks=`{group['chunk_count']}`, "
            f"parents=`{group['parent_section_count']}`, "
            f"page=`{group['any_page_metadata_coverage']}`, "
            f"page_span=`{group['page_span_coverage']}`, "
            f"regions.page_number=`{group['regions_page_number_coverage']}`, "
            f"regions.bbox=`{group['regions_bbox_coverage']}`, "
            f"capability=`{group.get('page_metadata_capability')}`, "
            f"decision=`{group['decision']}`"
        )
    lines.extend(
        [
            "",
            "## Implementation Matrix",
            "| source type | current coverage | recoverable? | parser change? | re-index? | OCR/visual? | cost | expected eval impact |",
            "|---|---:|---|---|---|---|---|---|",
        ]
    )
    for row in report.get("implementation_matrix") or []:
        lines.append(
            "| "
            f"`{row['source_type']}` | "
            f"{row['current_coverage']:.6f} | "
            f"{row['recoverable']} | "
            f"{row['requires_parser_change']} | "
            f"{row['requires_reindex']} | "
            f"{row['requires_ocr_visual_ingestion']} | "
            f"{row['estimated_engineering_cost']} | "
            f"{row['expected_eval_impact']} |"
        )
    readiness = report.get("readiness_checks") or {}
    integrity = readiness.get("chunk_page_span_integrity") or {}
    lines.extend(
        [
            "",
            "## Readiness Checks",
            f"- Page metadata coverage > 0: `{readiness.get('page_metadata_coverage_gt_0')}`",
            f"- Chunk page_span integrity: `{integrity.get('ok')}` "
            f"(checked=`{integrity.get('checked_count')}`, invalid=`{integrity.get('invalid_page_span_count')}`, "
            f"region_outside=`{integrity.get('region_outside_page_span_count')}`)",
            f"- Citation renderer compatible: `{readiness.get('citation_renderer_compatible')}`",
            f"- No private path leakage: `{readiness.get('no_private_path_leakage')}`",
            f"- Aggregate-only outputs: `{readiness.get('aggregate_only_outputs')}`",
        ]
    )
    lines.extend(["", "## Follow-Up Issue Plan"])
    lines.extend(f"- {item}" for item in report["follow_up_issue_plan"])
    lines.extend(["", "## Recommendation", f"`{decision['recommendation']}`"])
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", type=Path, required=True, help="Directory containing index.json.")
    parser.add_argument(
        "--ingestion-report",
        type=Path,
        default=None,
        help="Optional ingestion_report.json. Defaults to <index-dir>/ingestion_report.json when present.",
    )
    parser.add_argument("--kordoc-cache-dir", type=Path, default=None)
    parser.add_argument("--visual-artifact-dir", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional directory for page_metadata_recovery_audit.json/.md.",
    )
    parser.add_argument("--out-json", type=Path, default=None, help="Optional aggregate JSON output path.")
    parser.add_argument("--out-md", type=Path, default=None, help="Optional Markdown report output path.")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    return parser.parse_args(argv)


def _repo_relative(path: Path) -> Path:
    return path if path.is_absolute() else _REPO_ROOT / path


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_audit_report(
        args.index_dir,
        ingestion_report_path=args.ingestion_report,
        kordoc_cache_dir=args.kordoc_cache_dir,
        visual_artifact_dir=args.visual_artifact_dir,
    )
    text = (
        render_markdown(report)
        if args.format == "markdown"
        else json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "page_metadata_recovery_audit.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (args.output_dir / "page_metadata_recovery_audit.md").write_text(
            render_markdown(report),
            encoding="utf-8",
        )
    if args.out_json:
        out_json = _repo_relative(args.out_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.out_md:
        out_md = _repo_relative(args.out_md)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(render_markdown(report), encoding="utf-8")
    sys.stdout.write(text)
    return 0 if report.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
