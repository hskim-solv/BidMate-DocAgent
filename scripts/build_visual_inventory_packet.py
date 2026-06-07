#!/usr/bin/env python3
"""Build a local/private visual inventory packet for VLM-needed pages.

This is an offline review scaffold, not a parser or hosted VLM call. It consumes
`parser_page_audit` output, selects pages by route/label/row, renders local page
thumbnails for review, and writes:

- private packet under data/private/real100_v2/visual_inventory/<run_id>/
- text/image-body-free aggregate under reports/parser_candidate_eval/<run_id>/

No raw page text is extracted or written by this script.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_parser_candidate_eval import CandidateEvalError, utc_now, write_json  # noqa: E402

SCHEMA_VERSION = 1
DEFAULT_PAGE_AUDIT = (
    "data/private/real100_v2/parser_page_audit/"
    "page-audit-96path-routing-v2-20260605T092124Z/page_audit.json"
)
DEFAULT_PRIMARY_ROUTES = "vlm_needed"
DEFAULT_MAX_PAGES = 12


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def round4(value: float) -> float:
    return round(float(value), 4)


def normalize_path(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


def parse_int_set(value: str | None) -> set[int]:
    if not value:
        return set()
    return {int(part.strip()) for part in value.split(",") if part.strip()}


def parse_str_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


def render_page_image(pdf_path: Path, page_number: int, *, dpi: int, output_path: Path) -> None:
    import pymupdf  # type: ignore  # noqa: PLC0415

    scale = dpi / 72.0
    doc = pymupdf.open(str(pdf_path))
    try:
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(output_path))
    finally:
        doc.close()


def page_priority(page: dict[str, Any]) -> float:
    """Rank visually rich/ambiguous pages first for manual review."""

    image_area = float(page.get("image_area_ratio") or 0.0)
    image_count = int(page.get("image_count") or 0)
    text_chars = int(page.get("text_chars") or 0)
    table_count = page.get("table_count")
    low_text_bonus = 1.0 if text_chars < 300 else 0.0
    unknown_table_bonus = 0.5 if table_count is None else 0.0
    return round4((100.0 * image_area) + (2.0 * image_count) + low_text_bonus + unknown_table_bonus)


def visual_need_tags(page: dict[str, Any]) -> list[str]:
    tags = []
    text_chars = int(page.get("text_chars") or 0)
    image_count = int(page.get("image_count") or 0)
    image_area = float(page.get("image_area_ratio") or 0.0)
    table_count = page.get("table_count")
    labels = {str(label) for label in page.get("labels") or []}
    if image_area >= 0.20:
        tags.append("large_image_area")
        if text_chars < 100:
            tags.append("scanned_form_or_fullpage_image")
        else:
            tags.append("visual_layout")
    if image_count >= 4:
        tags.append("image_rich")
        if image_area < 0.05:
            tags.append("low_area_multi_image")
    if text_chars < 80:
        tags.append("low_text")
    elif text_chars < 300:
        tags.append("moderate_text")
    if table_count is None:
        tags.append("table_unknown")
    elif int(table_count or 0) > 0:
        tags.append("table_detected")
    if "ocr_needed" in labels:
        tags.append("ocr_overlap")
    if not tags:
        tags.append("visual_review")
    return list(dict.fromkeys(tags))


def select_pages(
    page_audit: dict[str, Any],
    *,
    csv_rows: set[int],
    primary_routes: set[str],
    labels: set[str],
    max_pages: int | None,
) -> list[dict[str, Any]]:
    selected = []
    for document in page_audit.get("documents") or []:
        if not isinstance(document, dict):
            continue
        csv_row = int(document.get("csv_row") or 0)
        if csv_rows and csv_row not in csv_rows:
            continue
        for page in document.get("pages") or []:
            if not isinstance(page, dict):
                continue
            page_labels = {str(label) for label in page.get("labels") or []}
            primary_route = str(page.get("primary_route") or "")
            route_match = not primary_routes or primary_route in primary_routes
            label_match = not labels or bool(page_labels & labels)
            if not (route_match and label_match):
                continue
            record = {
                "csv_row": csv_row,
                "subset_rank": document.get("subset_rank"),
                "doc_id": document.get("doc_id"),
                "source_sha256": document.get("source_sha256"),
                "source_file": document.get("source_file"),
                "path_pdf": document.get("path_pdf"),
                "expected_page_count": document.get("expected_page_count"),
                "page": int(page.get("page") or 0),
                "features": {
                    "text_chars": int(page.get("text_chars") or 0),
                    "hangul_ratio": page.get("hangul_ratio"),
                    "mojibake_count": int(page.get("mojibake_count") or 0),
                    "image_count": int(page.get("image_count") or 0),
                    "image_area_ratio": float(page.get("image_area_ratio") or 0.0),
                    "table_count": page.get("table_count"),
                    "warnings": page.get("warnings") or [],
                },
                "route": {
                    "primary_route": primary_route,
                    "labels": sorted(page_labels),
                    "reasons": page.get("reasons") or [],
                },
            }
            record["priority_score"] = page_priority(page)
            record["visual_need_tags"] = visual_need_tags(page)
            selected.append(record)
    selected.sort(key=lambda item: (-float(item.get("priority_score") or 0.0), int(item.get("csv_row") or 0), int(item.get("page") or 0)))
    if max_pages and max_pages > 0:
        return selected[:max_pages]
    return selected


def build_private_packet(
    selected_pages: list[dict[str, Any]],
    *,
    run_manifest: dict[str, Any],
    out_dir: Path,
    render_images: bool,
    render_dpi: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    pages = []
    for page in selected_pages:
        record = dict(page)
        if render_images:
            image_rel = Path("images") / f"row-{int(page['csv_row']):04d}-page-{int(page['page']):04d}.png"
            render_page_image(normalize_path(str(page.get("path_pdf") or "")), int(page["page"]), dpi=render_dpi, output_path=out_dir / image_rel)
            record["image_path"] = str(out_dir / image_rel)
            record["image_relpath"] = str(image_rel)
        else:
            record["image_path"] = None
            record["image_relpath"] = None
        record["review"] = {
            "status": "draft_unreviewed",
            "reviewer": None,
            "visual_question": "What non-text visual facts, chart/diagram/table relationships, or image-only constraints matter for RAG?",
            "required_facts": [],
            "notes": "Fill manually if this page should produce a future visual sidecar.",
        }
        pages.append(record)
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "visual_inventory_packet",
        "generated_at_utc": utc_now(),
        "run": run_manifest,
        "runtime_s": round4(time.perf_counter() - started),
        "pages": pages,
    }


def aggregate_packet(packet: dict[str, Any]) -> dict[str, Any]:
    tag_counts = Counter()
    route_counts = Counter()
    label_counts = Counter()
    warning_counts = Counter()
    by_page = []
    for page in packet.get("pages") or []:
        tags = [str(tag) for tag in page.get("visual_need_tags") or []]
        tag_counts.update(tags)
        route = page.get("route") or {}
        route_counts.update([str(route.get("primary_route") or "unknown")])
        label_counts.update(str(label) for label in route.get("labels") or [])
        features = page.get("features") or {}
        warning_counts.update(str(warning) for warning in features.get("warnings") or [])
        by_page.append(
            {
                "csv_row": page.get("csv_row"),
                "page": page.get("page"),
                "doc_id": page.get("doc_id"),
                "source_sha256": page.get("source_sha256"),
                "source_file": page.get("source_file"),
                "priority_score": page.get("priority_score"),
                "visual_need_tags": tags,
                "features": features,
                "route": route,
                "image_rendered": bool(page.get("image_relpath")),
                "image_relpath": page.get("image_relpath"),
                "review_status": (page.get("review") or {}).get("status"),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "visual_inventory_aggregate",
        "generated_at_utc": utc_now(),
        "run": packet.get("run") or {},
        "summary": {
            "pages": len(by_page),
            "route_counts": dict(sorted(route_counts.items())),
            "label_counts": dict(sorted(label_counts.items())),
            "visual_need_tag_counts": dict(sorted(tag_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
        },
        "pages": by_page,
    }


def markdown_private(packet: dict[str, Any]) -> str:
    lines = ["# Visual Inventory Packet", ""]
    run = packet.get("run") or {}
    lines.append(f"- Run ID: `{run.get('run_id')}`")
    lines.append(f"- Generated: `{packet.get('generated_at_utc')}`")
    lines.append(f"- Review status: `draft_unreviewed`")
    lines.append("")
    lines.append("> This private packet contains rendered local page images for review. It contains no extracted raw page text.")
    lines.append("")
    for page in packet.get("pages") or []:
        lines.append(f"## row {page.get('csv_row')} page {page.get('page')}")
        lines.append("")
        lines.append(f"- doc_id: `{page.get('doc_id')}`")
        lines.append(f"- source_file: `{page.get('source_file')}`")
        lines.append(f"- path_pdf: `{page.get('path_pdf')}`")
        lines.append(f"- priority_score: `{page.get('priority_score')}`")
        lines.append(f"- visual_need_tags: `{page.get('visual_need_tags')}`")
        lines.append(f"- route: `{page.get('route')}`")
        lines.append(f"- features: `{page.get('features')}`")
        if page.get("image_relpath"):
            lines.append(f"- image: `{page.get('image_path')}`")
            lines.append("")
            lines.append(f"![row {page.get('csv_row')} page {page.get('page')}]({page.get('image_relpath')})")
        lines.append("")
        lines.append("### Review notes")
        lines.append("")
        lines.append("- Required visual facts:")
        lines.append("- Chart/diagram/table semantics:")
        lines.append("- RAG sidecar recommendation:")
        lines.append("")
    return "\n".join(lines) + "\n"


def markdown_aggregate(aggregate: dict[str, Any]) -> str:
    run = aggregate.get("run") or {}
    summary = aggregate.get("summary") or {}
    lines = ["# Visual Inventory Aggregate", ""]
    lines.append(f"- Run ID: `{run.get('run_id')}`")
    lines.append(f"- Generated: `{aggregate.get('generated_at_utc')}`")
    lines.append(f"- Pages: `{summary.get('pages')}`")
    lines.append(f"- Routes: `{summary.get('route_counts')}`")
    lines.append(f"- Labels: `{summary.get('label_counts')}`")
    lines.append(f"- Visual tags: `{summary.get('visual_need_tag_counts')}`")
    lines.append("")
    lines.append("This aggregate omits rendered image bodies and raw page text. See private packet for local thumbnails.")
    lines.append("")
    lines.append("| csv_row | page | priority | tags | features | route | image |")
    lines.append("|---:|---:|---:|---|---|---|---|")
    for page in aggregate.get("pages") or []:
        lines.append(
            f"| {page.get('csv_row')} | {page.get('page')} | {page.get('priority_score')} | "
            f"`{page.get('visual_need_tags')}` | `{page.get('features')}` | `{page.get('route')}` | "
            f"`{page.get('image_relpath')}` |"
        )
    return "\n".join(lines) + "\n"


def out_dir_default(run_id: str) -> Path:
    return REPO_ROOT / "data/private/real100_v2/visual_inventory" / run_id


def report_dir_default(run_id: str) -> Path:
    return REPO_ROOT / "reports/parser_candidate_eval" / run_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local visual inventory packet from parser page audit.")
    parser.add_argument("--page-audit", default=DEFAULT_PAGE_AUDIT)
    parser.add_argument("--csv-rows", default=None)
    parser.add_argument("--primary-routes", default=DEFAULT_PRIMARY_ROUTES)
    parser.add_argument("--labels", default=None)
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--render-dpi", type=int, default=72)
    parser.add_argument("--no-render-images", action="store_true")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--report-dir", default=None)
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        run_id = args.run_id or f"visual-inventory-{utc_now()}"
        page_audit_path = normalize_path(args.page_audit)
        page_audit = read_json(page_audit_path)
        csv_rows = parse_int_set(args.csv_rows)
        primary_routes = parse_str_set(args.primary_routes)
        labels = parse_str_set(args.labels)
        out_dir = Path(args.out_dir) if args.out_dir else out_dir_default(run_id)
        report_dir = Path(args.report_dir) if args.report_dir else report_dir_default(run_id)
        selected = select_pages(
            page_audit,
            csv_rows=csv_rows,
            primary_routes=primary_routes,
            labels=labels,
            max_pages=args.max_pages,
        )
        run_manifest = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "generated_at_utc": utc_now(),
            "page_audit": str(page_audit_path),
            "source_page_audit_run_id": (page_audit.get("run") or {}).get("run_id"),
            "csv_rows": sorted(csv_rows),
            "primary_routes": sorted(primary_routes),
            "labels": sorted(labels),
            "max_pages": args.max_pages,
            "render_dpi": args.render_dpi,
            "render_images": not bool(args.no_render_images),
            "out_dir": str(out_dir),
            "report_dir": str(report_dir),
        }
        packet = build_private_packet(
            selected,
            run_manifest=run_manifest,
            out_dir=out_dir,
            render_images=not bool(args.no_render_images),
            render_dpi=args.render_dpi,
        )
        aggregate = aggregate_packet(packet)
        write_json(out_dir / "visual_inventory.json", packet)
        (out_dir / "visual_inventory.md").write_text(markdown_private(packet), encoding="utf-8")
        write_json(report_dir / "visual_inventory.aggregate.json", aggregate)
        (report_dir / "visual_inventory.md").write_text(markdown_aggregate(aggregate), encoding="utf-8")
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "out_dir": str(out_dir),
                    "report_dir": str(report_dir),
                    "pages": aggregate["summary"]["pages"],
                    "visual_need_tag_counts": aggregate["summary"]["visual_need_tag_counts"],
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
