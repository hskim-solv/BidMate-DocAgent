#!/usr/bin/env python3
"""Audit path-level parser pages and assign OCR/VLM routing labels.

The output is a routing surface, not a parser replacement. It records page-level
features needed to decide where OCR, table sidecars, or document VLM parsers
should run. Per-page artifacts avoid raw page text; aggregate reports are safe to
read as routing evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import signal
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_parser_candidate_eval import (  # noqa: E402
    CandidateEvalError,
    load_manifest_rows,
    load_subset_rows,
    make_doc_id,
    selected_rows,
    utc_now,
    write_json,
)

SCHEMA_VERSION = 1
DEFAULT_MIN_TEXT_CHARS = 80
DEFAULT_VLM_IMAGE_AREA_RATIO = 0.20
DEFAULT_VLM_IMAGE_COUNT = 4
DEFAULT_VLM_IMAGE_COUNT_MIN_AREA_RATIO = 0.05
DEFAULT_OCR_IMAGE_AREA_RATIO = 0.05
DEFAULT_MODERATE_TEXT_CHARS = 300
MOJIBAKE_MARKERS = ("�", "Ã", "Â", "ì", "í", "ë")
ROUTE_PRIORITY = (
    "vlm_needed",
    "ocr_needed",
    "table_sidecar",
    "text_layer",
    "manual_review",
    "skip",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def round4(value: float) -> float:
    return round(float(value), 4)


def hangul_ratio(text: str) -> float:
    if not text:
        return 0.0
    hangul = sum(1 for char in text if "가" <= char <= "힣")
    return round4(hangul / max(1, len(text)))


def mojibake_count(text: str) -> int:
    return sum(text.count(marker) for marker in MOJIBAKE_MARKERS)


def image_block_area_ratio(page: Any, page_dict: dict[str, Any]) -> float:
    rect = getattr(page, "rect", None)
    page_area = float(getattr(rect, "width", 0.0) or 0.0) * float(getattr(rect, "height", 0.0) or 0.0)
    if page_area <= 0:
        return 0.0
    area = 0.0
    for block in page_dict.get("blocks") or []:
        if not isinstance(block, dict) or block.get("type") != 1:
            continue
        bbox = block.get("bbox") or []
        if len(bbox) != 4:
            continue
        x0, y0, x1, y1 = (float(value or 0.0) for value in bbox)
        area += max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return round4(min(1.0, area / page_area))


class _TableDetectionTimeout(Exception):
    pass


def _raise_table_timeout(_signum: int, _frame: Any) -> None:
    raise _TableDetectionTimeout


def find_table_count(page: Any, *, timeout_s: float | None = None) -> tuple[int | None, str | None]:
    finder = getattr(page, "find_tables", None)
    if not callable(finder):
        return None, "pymupdf_find_tables_unavailable"
    previous_handler = None
    previous_timer = None
    try:
        if timeout_s and timeout_s > 0:
            previous_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, _raise_table_timeout)
            previous_timer = signal.setitimer(signal.ITIMER_REAL, float(timeout_s))
        result = finder()
    except _TableDetectionTimeout:
        return None, "pymupdf_find_tables_timeout"
    except Exception as exc:  # noqa: BLE001 - table detection is advisory
        return None, f"pymupdf_find_tables_failed:{type(exc).__name__}"
    finally:
        if timeout_s and timeout_s > 0 and previous_handler is not None and previous_timer is not None:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])
            signal.signal(signal.SIGALRM, previous_handler)
    tables = getattr(result, "tables", result)
    try:
        return len(tables or []), None
    except TypeError:
        return None, "pymupdf_find_tables_unknown_shape"


def extract_page_features(
    page: Any,
    *,
    page_number: int,
    table_detection_enabled: bool = True,
    table_timeout_s: float | None = None,
    table_max_pages_per_doc: int | None = None,
) -> dict[str, Any]:
    text = page.get_text("text") or ""
    try:
        page_dict = page.get_text("dict") or {}
    except Exception:  # noqa: BLE001
        page_dict = {}
    try:
        image_count = len(page.get_images(full=True) or [])
    except Exception:  # noqa: BLE001
        image_count = 0
    if not table_detection_enabled:
        table_count, table_warning = None, "pymupdf_find_tables_disabled"
    elif table_max_pages_per_doc and table_max_pages_per_doc > 0 and page_number > table_max_pages_per_doc:
        table_count, table_warning = None, "pymupdf_find_tables_skipped_by_cap"
    else:
        table_count, table_warning = find_table_count(page, timeout_s=table_timeout_s)
    warnings = []
    if table_warning:
        warnings.append(table_warning)
    return {
        "page": page_number,
        "text_chars": len(text.strip()),
        "hangul_ratio": hangul_ratio(text),
        "mojibake_count": mojibake_count(text),
        "image_count": image_count,
        "image_area_ratio": image_block_area_ratio(page, page_dict),
        "table_count": table_count,
        "warnings": warnings,
    }


def classify_page_route(
    features: dict[str, Any],
    *,
    min_text_chars: int = DEFAULT_MIN_TEXT_CHARS,
    moderate_text_chars: int = DEFAULT_MODERATE_TEXT_CHARS,
    vlm_image_area_ratio: float = DEFAULT_VLM_IMAGE_AREA_RATIO,
    vlm_image_count: int = DEFAULT_VLM_IMAGE_COUNT,
    vlm_image_count_min_area_ratio: float = DEFAULT_VLM_IMAGE_COUNT_MIN_AREA_RATIO,
    ocr_image_area_ratio: float = DEFAULT_OCR_IMAGE_AREA_RATIO,
) -> dict[str, Any]:
    text_chars = int(features.get("text_chars") or 0)
    image_count = int(features.get("image_count") or 0)
    image_area_ratio = float(features.get("image_area_ratio") or 0.0)
    table_count_raw = features.get("table_count")
    table_count = int(table_count_raw or 0) if table_count_raw is not None else 0
    mojibake = int(features.get("mojibake_count") or 0)

    labels: list[str] = []
    reasons: list[str] = []

    if text_chars >= min_text_chars:
        labels.append("text_layer")
        reasons.append("text_chars_above_threshold")

    if table_count > 0:
        labels.append("table_sidecar")
        reasons.append("tables_detected")

    image_signal = image_count > 0 or image_area_ratio >= ocr_image_area_ratio
    if (text_chars < min_text_chars and image_signal) or mojibake > 0:
        labels.append("ocr_needed")
        if text_chars < min_text_chars:
            reasons.append("low_text_with_image_signal")
        if mojibake > 0:
            reasons.append("mojibake_detected")

    image_count_vlm_signal = (
        image_count >= vlm_image_count
        and text_chars < moderate_text_chars
        and image_area_ratio >= vlm_image_count_min_area_ratio
    )
    if image_area_ratio >= vlm_image_area_ratio or image_count_vlm_signal:
        labels.append("vlm_needed")
        if image_area_ratio >= vlm_image_area_ratio:
            reasons.append("large_image_area")
        else:
            reasons.append("image_rich_low_or_moderate_text_with_area")

    if not labels:
        if text_chars == 0 and not image_signal and table_count == 0:
            labels.append("skip")
            reasons.append("empty_no_image_no_table")
        elif text_chars < min_text_chars:
            labels.append("manual_review")
            reasons.append("low_text_no_clear_image_signal")
        else:
            labels.append("text_layer")
            reasons.append("default_text_layer")

    # Preserve insertion order while deduplicating.
    labels = list(dict.fromkeys(labels))
    reasons = list(dict.fromkeys(reasons))
    primary_route = next(route for route in ROUTE_PRIORITY if route in labels)
    return {"labels": labels, "primary_route": primary_route, "reasons": reasons}


def audit_document(row: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    import pymupdf  # type: ignore  # noqa: PLC0415

    started = time.perf_counter()
    pages: list[dict[str, Any]] = []
    pdf_path = Path(str(row["_absolute_path_pdf"]))
    doc = pymupdf.open(str(pdf_path))
    try:
        page_count = int(getattr(doc, "page_count", len(doc)) or 0)
        max_pages = args.max_pages_per_doc if args.max_pages_per_doc and args.max_pages_per_doc > 0 else page_count
        for page_index in range(min(page_count, max_pages)):
            page = doc.load_page(page_index)
            features = extract_page_features(
                page,
                page_number=page_index + 1,
                table_detection_enabled=not bool(args.disable_table_detection),
                table_timeout_s=args.table_timeout_s,
                table_max_pages_per_doc=args.table_max_pages_per_doc,
            )
            route = classify_page_route(
                features,
                min_text_chars=args.min_text_chars,
                moderate_text_chars=args.moderate_text_chars,
                vlm_image_area_ratio=args.vlm_image_area_ratio,
                vlm_image_count=args.vlm_image_count,
                vlm_image_count_min_area_ratio=args.vlm_image_count_min_area_ratio,
                ocr_image_area_ratio=args.ocr_image_area_ratio,
            )
            pages.append({**features, **route})
    finally:
        doc.close()

    route_counts = Counter(page["primary_route"] for page in pages)
    label_counts = Counter(label for page in pages for label in page["labels"])
    return {
        "schema_version": SCHEMA_VERSION,
        "csv_row": int(row["csv_row"]),
        "subset_rank": int(row.get("subset_rank") or 0),
        "subset_reason": row.get("subset_reason") or "selected",
        "doc_id": make_doc_id(row),
        "source_sha256": row.get("source_sha256"),
        "source_file": row.get("source_file"),
        "path_pdf": row.get("path_pdf"),
        "expected_page_count": int(row.get("page_count") or page_count),
        "pages_audited": len(pages),
        "audit_truncated": len(pages) < page_count,
        "route_counts": dict(sorted(route_counts.items())),
        "label_counts": dict(sorted(label_counts.items())),
        "runtime_s": round4(time.perf_counter() - started),
        "pages": pages,
    }


def duplicate_alias_checks(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in documents:
        sha = str(doc.get("source_sha256") or "")
        if sha:
            groups[sha].append(doc)
    checks = []
    for sha, grouped in sorted(groups.items()):
        if len(grouped) < 2:
            continue
        doc_ids = [str(doc.get("doc_id") or "") for doc in grouped]
        csv_rows = [int(doc.get("csv_row") or 0) for doc in grouped]
        checks.append(
            {
                "source_sha256": sha,
                "csv_rows": csv_rows,
                "doc_ids": doc_ids,
                "unique_doc_ids": len(set(doc_ids)),
                "ok": len(set(doc_ids)) == len(doc_ids) and len(set(csv_rows)) == len(csv_rows),
            }
        )
    return checks


def build_aggregate(run_manifest: dict[str, Any], documents: list[dict[str, Any]]) -> dict[str, Any]:
    route_counts = Counter()
    label_counts = Counter()
    pages_audited = 0
    text_chars_total = 0
    image_pages = 0
    table_pages = 0
    warnings = Counter()
    by_doc = []
    for document in documents:
        pages = document.get("pages") or []
        pages_audited += len(pages)
        route_counts.update(document.get("route_counts") or {})
        label_counts.update(document.get("label_counts") or {})
        for page in pages:
            text_chars_total += int(page.get("text_chars") or 0)
            if int(page.get("image_count") or 0) > 0 or float(page.get("image_area_ratio") or 0.0) > 0:
                image_pages += 1
            if int(page.get("table_count") or 0) > 0:
                table_pages += 1
            warnings.update(page.get("warnings") or [])
        by_doc.append(
            {
                "csv_row": document.get("csv_row"),
                "subset_rank": document.get("subset_rank"),
                "subset_reason": document.get("subset_reason"),
                "doc_id": document.get("doc_id"),
                "source_sha256": document.get("source_sha256"),
                "expected_page_count": document.get("expected_page_count"),
                "pages_audited": document.get("pages_audited"),
                "audit_truncated": document.get("audit_truncated"),
                "route_counts": document.get("route_counts"),
                "label_counts": document.get("label_counts"),
                "runtime_s": document.get("runtime_s"),
            }
        )
    duplicate_checks = duplicate_alias_checks(documents)
    return {
        "mode": "parser_page_audit",
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "run": run_manifest,
        "summary": {
            "documents": len(documents),
            "pages_audited": pages_audited,
            "route_counts": dict(sorted(route_counts.items())),
            "label_counts": dict(sorted(label_counts.items())),
            "image_pages": image_pages,
            "table_pages": table_pages,
            "avg_text_chars_per_page": round4(text_chars_total / pages_audited) if pages_audited else 0.0,
            "duplicate_alias_ok": all(check["ok"] for check in duplicate_checks) if duplicate_checks else None,
            "duplicate_alias_checks": duplicate_checks,
            "warnings": dict(sorted(warnings.items())),
        },
        "documents": sorted(by_doc, key=lambda item: int(item.get("subset_rank") or 0)),
    }


def write_markdown_summary(path: Path, aggregate: dict[str, Any]) -> None:
    run = aggregate.get("run") or {}
    summary = aggregate.get("summary") or {}
    lines = ["# Parser Page Audit", ""]
    lines.append(f"- Run ID: `{run.get('run_id', '')}`")
    lines.append(f"- Generated: `{aggregate.get('generated_at_utc')}`")
    lines.append(f"- Pages audited: `{summary.get('pages_audited')}`")
    lines.append(f"- Duplicate alias ok: `{summary.get('duplicate_alias_ok')}`")
    lines.append("")
    lines.append("## Route counts")
    lines.append("")
    lines.append("| route | pages |")
    lines.append("|---|---:|")
    for route, count in (summary.get("route_counts") or {}).items():
        lines.append(f"| `{route}` | {count} |")
    lines.append("")
    lines.append("## Label counts")
    lines.append("")
    lines.append("| label | pages |")
    lines.append("|---|---:|")
    for label, count in (summary.get("label_counts") or {}).items():
        lines.append(f"| `{label}` | {count} |")
    lines.append("")
    lines.append("## By document")
    lines.append("")
    lines.append("| csv_row | pages | primary routes | labels | runtime_s |")
    lines.append("|---:|---:|---|---|---:|")
    for doc in aggregate.get("documents") or []:
        routes = ", ".join(f"{k}:{v}" for k, v in (doc.get("route_counts") or {}).items())
        labels = ", ".join(f"{k}:{v}" for k, v in (doc.get("label_counts") or {}).items())
        lines.append(
            f"| {doc.get('csv_row')} | {doc.get('pages_audited')} | {routes} | {labels} | {doc.get('runtime_s')} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_dir_default(run_id: str) -> Path:
    return REPO_ROOT / "data/private/real100_v2/parser_page_audit" / run_id


def report_dir_default(run_id: str) -> Path:
    return REPO_ROOT / "reports/parser_candidate_eval" / run_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit parser pages and assign OCR/VLM routing labels.")
    parser.add_argument("--manifest", required=True, help="Path-level converted PDF manifest JSON.")
    parser.add_argument("--subset", required=True, help="Subset JSON with csv_row entries.")
    parser.add_argument("--run-id", default=None, help="Run id. Defaults to page-audit-<UTC>.")
    parser.add_argument("--audit-dir", default=None, help="Local/private per-page audit output dir.")
    parser.add_argument("--report-dir", default=None, help="Aggregate report output dir.")
    parser.add_argument("--max-pages-per-doc", type=int, default=None, help="Optional debug cap per document.")
    parser.add_argument(
        "--disable-table-detection",
        action="store_true",
        help="Skip PyMuPDF find_tables() entirely and keep table_count as unknown.",
    )
    parser.add_argument(
        "--table-timeout-s",
        type=float,
        default=None,
        help="Optional per-page PyMuPDF find_tables() timeout. Use before full-corpus audits.",
    )
    parser.add_argument(
        "--table-max-pages-per-doc",
        type=int,
        default=None,
        help="Optional per-document cap for pages that run table detection; later pages are audited without find_tables().",
    )
    parser.add_argument("--min-text-chars", type=int, default=DEFAULT_MIN_TEXT_CHARS)
    parser.add_argument("--moderate-text-chars", type=int, default=DEFAULT_MODERATE_TEXT_CHARS)
    parser.add_argument("--ocr-image-area-ratio", type=float, default=DEFAULT_OCR_IMAGE_AREA_RATIO)
    parser.add_argument("--vlm-image-area-ratio", type=float, default=DEFAULT_VLM_IMAGE_AREA_RATIO)
    parser.add_argument("--vlm-image-count", type=int, default=DEFAULT_VLM_IMAGE_COUNT)
    parser.add_argument("--vlm-image-count-min-area-ratio", type=float, default=DEFAULT_VLM_IMAGE_COUNT_MIN_AREA_RATIO)
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        run_id = args.run_id or f"page-audit-{utc_now()}"
        manifest_path = Path(args.manifest)
        subset_path = Path(args.subset)
        audit_dir = Path(args.audit_dir) if args.audit_dir else audit_dir_default(run_id)
        report_dir = Path(args.report_dir) if args.report_dir else report_dir_default(run_id)
        manifest = load_manifest_rows(manifest_path)
        subset = load_subset_rows(subset_path)
        rows = selected_rows(manifest, subset)
        run_manifest = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "generated_at_utc": utc_now(),
            "manifest": str(manifest_path),
            "subset": str(subset_path),
            "audit_dir": str(audit_dir),
            "report_dir": str(report_dir),
            "documents": len(rows),
            "thresholds": {
                "min_text_chars": args.min_text_chars,
                "moderate_text_chars": args.moderate_text_chars,
                "ocr_image_area_ratio": args.ocr_image_area_ratio,
                "vlm_image_area_ratio": args.vlm_image_area_ratio,
                "vlm_image_count": args.vlm_image_count,
                "vlm_image_count_min_area_ratio": args.vlm_image_count_min_area_ratio,
                "max_pages_per_doc": args.max_pages_per_doc,
                "disable_table_detection": bool(args.disable_table_detection),
                "table_timeout_s": args.table_timeout_s,
                "table_max_pages_per_doc": args.table_max_pages_per_doc,
            },
        }
        documents = [audit_document(row, args) for row in rows]
        write_json(audit_dir / "page_audit.json", {"run": run_manifest, "documents": documents})
        aggregate = build_aggregate(run_manifest, documents)
        write_json(report_dir / "page_audit.aggregate.json", aggregate)
        write_markdown_summary(report_dir / "page_audit.md", aggregate)
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "audit_dir": str(audit_dir),
                    "report_dir": str(report_dir),
                    "documents": len(documents),
                    "pages_audited": aggregate["summary"]["pages_audited"],
                    "route_counts": aggregate["summary"]["route_counts"],
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
