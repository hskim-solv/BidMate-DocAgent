#!/usr/bin/env python3
"""Local-only aggregate audit for private parse/index quality.

The script reads private inputs and index content, but every artifact it writes
is aggregate/redacted only. It does not change ingestion, chunking, retrieval,
reranking, prompt, or verifier behavior.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import datetime as dt
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:  # direct script execution
    from scripts.private_data_quality_audit_utils import (
        assert_public_safe,
        compact,
        hash_ref,
        page_metadata_present,
        percentile,
        repo_path,
        require_safe_out_dir,
        write_json,
        write_jsonl,
    )
except ImportError:  # pragma: no cover
    from private_data_quality_audit_utils import (  # type: ignore
        assert_public_safe,
        compact,
        hash_ref,
        page_metadata_present,
        percentile,
        repo_path,
        require_safe_out_dir,
        write_json,
        write_jsonl,
    )

try:
    from ingestion import canonical_doc_id, clean_cell, normalize_file_format
except Exception:  # pragma: no cover - keeps audit usable if ingestion deps drift
    canonical_doc_id = None  # type: ignore[assignment]

    def clean_cell(value: Any) -> str:  # type: ignore[no-redef]
        return compact(value)

    def normalize_file_format(value: Any, file_name: str = "") -> str:  # type: ignore[no-redef]
        raw = str(value or Path(file_name).suffix.lstrip(".") or "").strip().lower()
        return raw


EMPTY_DOC_CHAR_THRESHOLD = 1
VERY_SHORT_DOC_CHAR_THRESHOLD = 200
HIGH_GARBLED_RATIO = 0.02
TABLE_LIKE_RE = re.compile(
    r"(\|[^|\n]+?\||\t|[┌┬┐├┼┤└┴┘]|(?:^|\n)\s*(?:구분|항목|내용|배점|평가)\s+)",
    re.MULTILINE,
)
DATE_RE = re.compile(
    r"(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|20\d{2}\s*년\s*\d{1,2}\s*월|\d{1,2}\s*월\s*\d{1,2}\s*일)"
)
AMOUNT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:원|천원|만원|억원|%)|(?:예산|금액|사업비)")
SCORE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:점|%)|(?:배점|평가점수|정량|정성)")
GARBLED_RE = re.compile(r"[�□■◆◇●○▯�]")


def _load_index(index_dir: Path) -> dict[str, Any]:
    index_file = index_dir / "index.json"
    if not index_file.is_file():
        raise FileNotFoundError("index metadata is missing")
    payload = json.loads(index_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("index metadata root must be an object")
    return payload


def _safe_format(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_+-]+", "_", value.strip().lower()).strip("_")
    return normalized[:40] if normalized else "unknown"


def _manifest_document_ref(row: dict[str, str], row_number: int) -> str:
    for key in ("doc_id", "document_id", "notice_id"):
        value = clean_cell(row.get(key))
        if value:
            return value
    notice_id = clean_cell(row.get("공고 번호"))
    notice_round = clean_cell(row.get("공고 차수"))
    file_value = clean_cell(row.get("file_path") or row.get("파일명") or row.get("file_name"))
    if canonical_doc_id is not None:
        candidate = canonical_doc_id(notice_id, notice_round, file_value)
        if candidate:
            return str(candidate)
    if notice_id:
        return f"{notice_id}-{notice_round}" if notice_round else notice_id
    if file_value:
        return Path(file_value).stem
    return f"manifest-row-{row_number}"


def _manifest_file_value(row: dict[str, str]) -> str:
    return clean_cell(row.get("file_path") or row.get("파일명") or row.get("file_name"))


def _source_exists(documents_dir: Path, file_value: str) -> bool:
    if not file_value:
        return False
    candidate = Path(file_value)
    if candidate.is_absolute():
        return candidate.is_file()
    return (documents_dir / candidate).is_file()


def _load_manifest(documents_dir: Path, data_list: Path) -> dict[str, Any]:
    if not data_list.is_file():
        raise FileNotFoundError("data list is missing")
    refs: list[str] = []
    category_counts: Counter[str] = Counter()
    format_counts: Counter[str] = Counter()
    manifest_flags: list[dict[str, Any]] = []
    seen_refs: set[str] = set()

    with data_list.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            has_ref_signal = any(
                clean_cell(row.get(key))
                for key in ("doc_id", "document_id", "notice_id", "공고 번호", "file_path", "파일명", "file_name")
            )
            row_ref = _manifest_document_ref(row, row_number)
            file_value = _manifest_file_value(row)
            file_format = _safe_format(normalize_file_format(row.get("파일형식"), file_value))
            refs.append(row_ref)
            format_counts[file_format] += 1

            row_categories: list[str] = []
            if not has_ref_signal:
                row_categories.append("missing_document_ref")
            if row_ref in seen_refs:
                row_categories.append("duplicate_document_ref")
            seen_refs.add(row_ref)
            if not file_value:
                row_categories.append("missing_source_file_ref")
            elif not _source_exists(documents_dir, file_value):
                row_categories.append("missing_source_file")
            if file_format not in {"pdf", "hwp", "hwpx", "json", "txt", "md"}:
                row_categories.append("unsupported_or_unknown_format")
            if "텍스트" in row and not clean_cell(row.get("텍스트")):
                row_categories.append("empty_manifest_content")

            for category in row_categories:
                category_counts[category] += 1
                manifest_flags.append(
                    {
                        "schema_version": 1,
                        "audit_type": "private_parse_quality",
                        "severity": "error" if category in {"missing_source_file", "empty_manifest_content"} else "warning",
                        "flag_type": category,
                        "subject_ref": hash_ref(f"{row_number}:{row_ref}:{file_value}", namespace="manifest-row"),
                    }
                )

    return {
        "row_count": len(refs),
        "document_refs": refs,
        "category_counts": dict(category_counts),
        "format_distribution": dict(sorted(format_counts.items())),
        "flags": manifest_flags,
    }


def _chunk_text(chunk: dict[str, Any]) -> str:
    return str(chunk.get("text") or "")


def _garbled_ratio(value: str) -> float:
    compacted = re.sub(r"\s+", "", value)
    if not compacted:
        return 0.0
    return len(GARBLED_RE.findall(value)) / len(compacted)


def _has_date_amount_or_score(value: str) -> bool:
    return bool(DATE_RE.search(value) or AMOUNT_RE.search(value) or SCORE_RE.search(value))


def _document_ref_for_chunk(chunk: dict[str, Any]) -> str:
    return str(chunk.get("doc_id") or chunk.get("metadata", {}).get("doc_id") or "")


def _collect_chunk_metrics(index: dict[str, Any]) -> dict[str, Any]:
    chunks = [chunk for chunk in index.get("chunks") or [] if isinstance(chunk, dict)]
    documents = [doc for doc in index.get("documents") or [] if isinstance(doc, dict)]
    doc_refs = {str(doc.get("doc_id") or "") for doc in documents if str(doc.get("doc_id") or "").strip()}

    lengths = [len(_chunk_text(chunk)) for chunk in chunks]
    normalized_contents = [compact(_chunk_text(chunk)).lower() for chunk in chunks]
    non_empty_contents = [value for value in normalized_contents if value]
    duplicate_excess = len(non_empty_contents) - len(set(non_empty_contents))

    missing_page = 0
    high_garbled = 0
    whitespace_only = 0
    table_like = 0
    date_amount_score_coverage = 0
    flags: list[dict[str, Any]] = []
    chunks_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for chunk in chunks:
        raw = _chunk_text(chunk)
        doc_ref = _document_ref_for_chunk(chunk)
        chunk_ref = str(chunk.get("chunk_id") or f"{doc_ref}:{len(chunks_by_doc[doc_ref])}")
        chunks_by_doc[doc_ref].append(chunk)
        chunk_hash = hash_ref(chunk_ref, namespace="chunk")
        doc_hash = hash_ref(doc_ref, namespace="document")

        if not page_metadata_present(chunk):
            missing_page += 1
        ratio = _garbled_ratio(raw)
        if ratio >= HIGH_GARBLED_RATIO:
            high_garbled += 1
            flags.append(
                {
                    "schema_version": 1,
                    "audit_type": "private_parse_quality",
                    "severity": "error",
                    "flag_type": "high_garbled_character_ratio",
                    "document_ref": doc_hash,
                    "chunk_ref": chunk_hash,
                    "metrics": {"garbled_ratio": round(ratio, 4), "content_chars": len(raw)},
                }
            )
        if raw and not raw.strip():
            whitespace_only += 1
            flags.append(
                {
                    "schema_version": 1,
                    "audit_type": "private_parse_quality",
                    "severity": "error",
                    "flag_type": "whitespace_only_chunk",
                    "document_ref": doc_hash,
                    "chunk_ref": chunk_hash,
                    "metrics": {"content_chars": len(raw)},
                }
            )
        if TABLE_LIKE_RE.search(raw):
            table_like += 1
        if _has_date_amount_or_score(raw):
            date_amount_score_coverage += 1

    document_category_counts: Counter[str] = Counter()
    document_flags: list[dict[str, Any]] = []
    all_doc_refs = set(doc_refs) | {doc_ref for doc_ref in chunks_by_doc if doc_ref}
    for doc_ref in sorted(all_doc_refs):
        doc_chunks = chunks_by_doc.get(doc_ref, [])
        content_chars = sum(len(_chunk_text(chunk).strip()) for chunk in doc_chunks)
        categories: list[tuple[str, str]] = []
        if content_chars <= EMPTY_DOC_CHAR_THRESHOLD:
            categories.append(("empty_document", "error"))
        elif content_chars < VERY_SHORT_DOC_CHAR_THRESHOLD:
            categories.append(("very_short_document", "warning"))
        if doc_chunks and all(not page_metadata_present(chunk) for chunk in doc_chunks):
            categories.append(("missing_page_metadata_document", "warning"))
        if any(_garbled_ratio(_chunk_text(chunk)) >= HIGH_GARBLED_RATIO for chunk in doc_chunks):
            categories.append(("high_garbled_document", "error"))
        for category, severity in categories:
            document_category_counts[category] += 1
            document_flags.append(
                {
                    "schema_version": 1,
                    "audit_type": "private_parse_quality",
                    "severity": severity,
                    "flag_type": category,
                    "document_ref": hash_ref(doc_ref, namespace="document"),
                    "metrics": {"chunk_count": len(doc_chunks), "content_chars": content_chars},
                }
            )

    return {
        "document_refs": doc_refs,
        "chunk_count": len(chunks),
        "lengths": lengths,
        "duplicate_chunk_ratio": round((duplicate_excess / len(chunks)) if chunks else 0.0, 6),
        "missing_page_metadata_count": missing_page,
        "missing_page_metadata_rate": round((missing_page / len(chunks)) if chunks else 0.0, 6),
        "high_garbled_character_ratio_count": high_garbled,
        "suspicious_whitespace_only_chunk_count": whitespace_only,
        "table_like_chunk_count": table_like,
        "date_amount_score_like_token_coverage_count": date_amount_score_coverage,
        "failed_suspicious_document_category_counts": dict(sorted(document_category_counts.items())),
        "flags": flags + document_flags,
    }


def _length_block(lengths: list[int]) -> dict[str, Any]:
    return {
        "min": min(lengths) if lengths else None,
        "p50": percentile(lengths, 0.50),
        "p95": percentile(lengths, 0.95),
        "max": max(lengths) if lengths else None,
    }


def _render_report(summary: dict[str, Any]) -> str:
    chunk_lengths = summary["chunk_length_chars"]
    lines = [
        "# Private Parse Quality Audit",
        "",
        "Local-only aggregate audit. Raw content, source names, exact local locations, and raw identifiers are omitted.",
        "",
        "## Verdict",
        "",
        f"- Passed: `{summary['passed']}`",
        f"- Error flags: {summary['flag_counts']['error']}",
        f"- Warning flags: {summary['flag_counts']['warning']}",
        "",
        "## Counts",
        "",
        f"- Total documents: {summary['total_document_count']}",
        f"- Parse success: {summary['parse_success_count']}",
        f"- Parse failure: {summary['parse_failure_count']}",
        f"- Empty documents: {summary['empty_document_count']}",
        f"- Very short documents: {summary['very_short_document_count']}",
        f"- Chunks: {summary['chunk_count']}",
        "",
        "## Chunk Lengths",
        "",
        "| min | p50 | p95 | max |",
        "|---:|---:|---:|---:|",
        f"| {chunk_lengths['min']} | {chunk_lengths['p50']} | {chunk_lengths['p95']} | {chunk_lengths['max']} |",
        "",
        "## Signals",
        "",
        f"- Duplicate chunk ratio: {summary['duplicate_chunk_ratio']}",
        f"- Missing page metadata: {summary['missing_page_metadata_count']} ({summary['missing_page_metadata_rate']})",
        f"- High garbled-character ratio chunks: {summary['high_garbled_character_ratio_count']}",
        f"- Whitespace-only chunks: {summary['suspicious_whitespace_only_chunk_count']}",
        f"- Table-like chunks: {summary['table_like_chunk_count']}",
        f"- Date/amount/score-like token coverage chunks: {summary['date_amount_score_like_token_coverage_count']}",
        "",
        "## Document Categories",
        "",
    ]
    categories = summary["failed_suspicious_document_category_counts"]
    if categories:
        for key, count in sorted(categories.items()):
            lines.append(f"- `{key}`: {count}")
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def build_parse_quality_audit(
    *,
    documents_dir: Path,
    data_list: Path,
    index_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    manifest = _load_manifest(documents_dir, data_list)
    index = _load_index(index_dir)
    chunk_metrics = _collect_chunk_metrics(index)

    manifest_refs = {str(ref) for ref in manifest["document_refs"] if str(ref).strip()}
    index_doc_refs = set(chunk_metrics["document_refs"])
    missing_manifest_refs = sorted(manifest_refs - index_doc_refs)
    parse_success_count = len(manifest_refs & index_doc_refs) if manifest_refs else len(index_doc_refs)
    parse_failure_count = len(missing_manifest_refs)

    flags = list(manifest["flags"]) + list(chunk_metrics["flags"])
    for ref in missing_manifest_refs:
        flags.append(
            {
                "schema_version": 1,
                "audit_type": "private_parse_quality",
                "severity": "error",
                "flag_type": "parse_failure_missing_from_index",
                "document_ref": hash_ref(ref, namespace="document"),
            }
        )

    category_counts = Counter(chunk_metrics["failed_suspicious_document_category_counts"])
    category_counts.update(manifest["category_counts"])
    if parse_failure_count:
        category_counts["parse_failure_missing_from_index"] += parse_failure_count

    error_count = sum(1 for flag in flags if flag.get("severity") == "error")
    warning_count = sum(1 for flag in flags if flag.get("severity") == "warning")
    lengths = [int(value) for value in chunk_metrics["lengths"]]
    summary = {
        "schema_version": 1,
        "audit_type": "private_parse_quality",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "passed": error_count == 0,
        "total_document_count": manifest["row_count"] or len(index_doc_refs),
        "parse_success_count": parse_success_count,
        "parse_failure_count": parse_failure_count,
        "empty_document_count": int(category_counts.get("empty_document", 0)),
        "very_short_document_count": int(category_counts.get("very_short_document", 0)),
        "chunk_count": chunk_metrics["chunk_count"],
        "chunk_length_chars": _length_block(lengths),
        "duplicate_chunk_ratio": chunk_metrics["duplicate_chunk_ratio"],
        "missing_page_metadata_count": chunk_metrics["missing_page_metadata_count"],
        "missing_page_metadata_rate": chunk_metrics["missing_page_metadata_rate"],
        "high_garbled_character_ratio_count": chunk_metrics["high_garbled_character_ratio_count"],
        "suspicious_whitespace_only_chunk_count": chunk_metrics["suspicious_whitespace_only_chunk_count"],
        "table_like_chunk_count": chunk_metrics["table_like_chunk_count"],
        "date_amount_score_like_token_coverage_count": chunk_metrics[
            "date_amount_score_like_token_coverage_count"
        ],
        "failed_suspicious_document_category_counts": dict(sorted(category_counts.items())),
        "source_format_distribution": manifest["format_distribution"],
        "flag_counts": {"error": error_count, "warning": warning_count, "total": len(flags)},
        "privacy": {
            "aggregate_only": True,
            "redacted_references_only": True,
            "raw_private_content_omitted": True,
        },
    }
    assert_public_safe(summary)
    for flag in flags:
        assert_public_safe(flag)
    return summary, flags, _render_report(summary)


def run_audit(
    *,
    documents_dir: Path,
    data_list: Path,
    index_dir: Path,
    out_dir: Path,
) -> dict[str, Any]:
    documents_dir = repo_path(documents_dir)
    data_list = repo_path(data_list)
    index_dir = repo_path(index_dir)
    out_dir = repo_path(out_dir)
    require_safe_out_dir(out_dir)

    summary, flags, report = build_parse_quality_audit(
        documents_dir=documents_dir,
        data_list=data_list,
        index_dir=index_dir,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "parse_quality_summary.json", summary)
    (out_dir / "parse_quality_report.md").write_text(report, encoding="utf-8")
    write_jsonl(out_dir / "parse_quality_flags.jsonl", flags)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents-dir", required=True)
    parser.add_argument("--data-list", required=True)
    parser.add_argument("--index-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_audit(
            documents_dir=Path(args.documents_dir),
            data_list=Path(args.data_list),
            index_dir=Path(args.index_dir),
            out_dir=Path(args.out_dir),
        )
    except Exception as exc:
        print(f"[ERROR] private parse quality audit failed: {exc}", file=sys.stderr)
        return 2
    print(
        "[OK]" if summary["passed"] else "[FAIL]",
        "private parse quality audit:",
        f"documents={summary['total_document_count']}",
        f"chunks={summary['chunk_count']}",
        f"errors={summary['flag_counts']['error']}",
        f"warnings={summary['flag_counts']['warning']}",
    )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
