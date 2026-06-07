#!/usr/bin/env python3
"""Build a private OCR review packet for tiny page-level ground-truth review.

This script does not change ingestion. It collects already-produced route-filtered
OCR artifacts, groups candidate outputs by (csv_row, page), renders page images
for visual review when requested, and writes:

- private packet with raw OCR text under data/private/real100_v2/ocr_review/<run_id>/
- aggregate report without raw OCR text under reports/parser_candidate_eval/<run_id>/

The packet is intentionally a review/ground-truth scaffold, not a quality verdict.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
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
DEFAULT_ARTIFACTS = (
    "data/private/real100_v2/route_candidate_eval/route-row16-ocr-primary-smoke-20260605T064211Z/"
    "candidates/tesseract_baseline/row-0016.json",
    "data/private/real100_v2/route_candidate_eval/route-row16-ocr-primary-smoke-20260605T064211Z/"
    "candidates/paddleocr_classic/row-0016.json",
    "data/private/real100_v2/route_candidate_eval/route-ocr-needed-tesseract-vs-paddleocr-20260605T062703Z/"
    "candidates/tesseract_baseline/row-0017.json",
    "data/private/real100_v2/route_candidate_eval/route-paddleocr-ocr-needed-smoke-20260605T055750Z/"
    "candidates/paddleocr_classic/row-0017.json",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def round4(value: float) -> float:
    return round(float(value), 4)


def normalize_path(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


def candidate_text_for_page(artifact: dict[str, Any], page_number: int) -> str:
    parts = []
    for element in artifact.get("elements") or []:
        if not isinstance(element, dict):
            continue
        page_span = element.get("page_span") or []
        if len(page_span) != 2:
            continue
        start, end = int(page_span[0]), int(page_span[1])
        if start <= page_number <= end:
            text = str(element.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def candidate_blocks_for_page(artifact: dict[str, Any], page_number: int) -> list[dict[str, Any]]:
    for page in artifact.get("pages") or []:
        if isinstance(page, dict) and int(page.get("page") or 0) == page_number:
            return [block for block in page.get("blocks") or [] if isinstance(block, dict)]
    return []


def candidate_page_record(artifact_path: Path, artifact: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
    page_number = int(page.get("page") or 0)
    text = candidate_text_for_page(artifact, page_number)
    blocks = candidate_blocks_for_page(artifact, page_number)
    return {
        "candidate": artifact.get("candidate"),
        "artifact_path": str(artifact_path),
        "document_status": artifact.get("status"),
        "page_status": page.get("status"),
        "page": page_number,
        "text": text,
        "text_chars": len(text),
        "block_count": len(blocks),
        "avg_confidence": page.get("avg_confidence"),
        "runtime_s": page.get("runtime_s"),
        "failure": page.get("failure"),
        "attempts": page.get("attempts") or [],
        "blocks": blocks,
        "provenance": artifact.get("provenance") or {},
    }


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


def group_artifacts(artifact_paths: list[Path]) -> dict[tuple[int, int], dict[str, Any]]:
    groups: dict[tuple[int, int], dict[str, Any]] = {}
    for artifact_path in artifact_paths:
        artifact = read_json(artifact_path)
        csv_row = int(artifact.get("csv_row") or 0)
        for page in artifact.get("pages") or []:
            if not isinstance(page, dict):
                continue
            page_number = int(page.get("page") or 0)
            key = (csv_row, page_number)
            group = groups.setdefault(
                key,
                {
                    "csv_row": csv_row,
                    "page": page_number,
                    "doc_id": artifact.get("doc_id"),
                    "source_sha256": artifact.get("source_sha256"),
                    "source_file": artifact.get("source_file"),
                    "path_pdf": artifact.get("path_pdf"),
                    "audit": page.get("audit") or {},
                    "candidates": [],
                },
            )
            group["candidates"].append(candidate_page_record(artifact_path, artifact, page))
    return groups


def build_private_packet(
    groups: dict[tuple[int, int], dict[str, Any]],
    *,
    run_manifest: dict[str, Any],
    out_dir: Path,
    render_images: bool,
    render_dpi: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    pages = []
    for key, group in sorted(groups.items()):
        csv_row, page_number = key
        page_record = dict(group)
        page_record["review"] = {
            "status": "draft_unverified",
            "reviewer": None,
            "expected_text": "",
            "required_facts": [],
            "candidate_verdicts": {
                str(candidate.get("candidate")): {
                    "accuracy": "unreviewed",
                    "misses": [],
                    "false_positives": [],
                    "notes": "",
                }
                for candidate in group.get("candidates") or []
            },
            "winner": None,
            "notes": "Fill this section by visually comparing the page image against candidate OCR text.",
        }
        if render_images:
            image_rel = Path("images") / f"row-{csv_row:04d}-page-{page_number:04d}.png"
            render_page_image(
                normalize_path(str(group.get("path_pdf") or "")),
                page_number,
                dpi=render_dpi,
                output_path=out_dir / image_rel,
            )
            page_record["image_path"] = str(out_dir / image_rel)
        else:
            page_record["image_path"] = None
        pages.append(page_record)
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "ocr_review_packet",
        "generated_at_utc": utc_now(),
        "run": run_manifest,
        "runtime_s": round4(time.perf_counter() - started),
        "pages": pages,
    }


def summarize_private_packet(packet: dict[str, Any]) -> dict[str, Any]:
    pages_summary = []
    candidate_totals: dict[str, Counter] = defaultdict(Counter)
    for page in packet.get("pages") or []:
        candidate_summaries = []
        for candidate in page.get("candidates") or []:
            name = str(candidate.get("candidate") or "unknown")
            status = str(candidate.get("page_status") or "unknown")
            candidate_totals[name].update([status])
            candidate_summaries.append(
                {
                    "candidate": name,
                    "document_status": candidate.get("document_status"),
                    "page_status": candidate.get("page_status"),
                    "text_chars": candidate.get("text_chars"),
                    "block_count": candidate.get("block_count"),
                    "avg_confidence": candidate.get("avg_confidence"),
                    "runtime_s": candidate.get("runtime_s"),
                    "failure_code": (candidate.get("failure") or {}).get("code")
                    if isinstance(candidate.get("failure"), dict)
                    else None,
                    "artifact_path": candidate.get("artifact_path"),
                }
            )
        pages_summary.append(
            {
                "csv_row": page.get("csv_row"),
                "page": page.get("page"),
                "doc_id": page.get("doc_id"),
                "source_sha256": page.get("source_sha256"),
                "path_pdf": page.get("path_pdf"),
                "image_path": page.get("image_path"),
                "audit_primary_route": (page.get("audit") or {}).get("primary_route"),
                "audit_labels": (page.get("audit") or {}).get("labels"),
                "review_status": (page.get("review") or {}).get("status"),
                "review_winner": (page.get("review") or {}).get("winner"),
                "candidates": candidate_summaries,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "ocr_review_packet_aggregate",
        "generated_at_utc": utc_now(),
        "run": packet.get("run") or {},
        "summary": {
            "pages": len(pages_summary),
            "candidate_page_status_counts": {name: dict(counter) for name, counter in sorted(candidate_totals.items())},
        },
        "pages": pages_summary,
    }


def markdown_for_private_packet(packet: dict[str, Any]) -> str:
    lines = ["# OCR Mini Review Packet", ""]
    run = packet.get("run") or {}
    lines.append(f"- Run ID: `{run.get('run_id')}`")
    lines.append(f"- Generated: `{packet.get('generated_at_utc')}`")
    lines.append(f"- Review status: `draft_unverified`")
    lines.append("")
    lines.append("> Raw OCR text below is local/private review material, not aggregate evidence.")
    lines.append("")
    for page in packet.get("pages") or []:
        lines.append(f"## row {page.get('csv_row')} page {page.get('page')}")
        lines.append("")
        lines.append(f"- doc_id: `{page.get('doc_id')}`")
        lines.append(f"- path_pdf: `{page.get('path_pdf')}`")
        lines.append(f"- image: `{page.get('image_path')}`")
        audit = page.get("audit") or {}
        lines.append(f"- audit route: `{audit.get('primary_route')}` labels=`{audit.get('labels')}`")
        lines.append("")
        lines.append("### Candidate outputs")
        lines.append("")
        for candidate in page.get("candidates") or []:
            lines.append(f"#### `{candidate.get('candidate')}`")
            lines.append("")
            lines.append(
                f"- status: `{candidate.get('page_status')}`; chars: `{candidate.get('text_chars')}`; "
                f"blocks: `{candidate.get('block_count')}`; confidence: `{candidate.get('avg_confidence')}`; "
                f"runtime_s: `{candidate.get('runtime_s')}`"
            )
            failure = candidate.get("failure")
            if failure:
                lines.append(f"- failure: `{failure}`")
            lines.append("")
            lines.append("```text")
            lines.append(str(candidate.get("text") or ""))
            lines.append("```")
            lines.append("")
        lines.append("### Ground-truth review scaffold")
        lines.append("")
        review = page.get("review") or {}
        status = review.get("status") or "draft_unverified"
        checked = "x" if status != "draft_unverified" else " "
        lines.append(f"- [{checked}] Visual page checked against candidate text")
        lines.append(f"- [{checked}] Required facts listed")
        lines.append(f"- [{checked}] Misses / false positives recorded per candidate")
        lines.append(f"- [{checked}] Winner or no-winner decision recorded")
        lines.append(f"- review_status: `{status}`")
        lines.append(f"- reviewer: `{review.get('reviewer')}`")
        lines.append(f"- winner: `{review.get('winner')}`")
        lines.append("")
        lines.append("Expected text / required facts:")
        lines.append("")
        lines.append("```text")
        lines.append(str(review.get("expected_text") or ""))
        lines.append("```")
        lines.append("")
        required_facts = review.get("required_facts") or []
        if required_facts:
            lines.append("Required facts:")
            for fact in required_facts:
                lines.append(f"- {fact}")
            lines.append("")
        verdicts = review.get("candidate_verdicts") or {}
        if verdicts:
            lines.append("Candidate verdicts:")
            for candidate_name, verdict in verdicts.items():
                if not isinstance(verdict, dict):
                    continue
                lines.append(
                    f"- `{candidate_name}`: accuracy=`{verdict.get('accuracy')}`, "
                    f"misses=`{verdict.get('misses')}`, false_positives=`{verdict.get('false_positives')}`, "
                    f"notes=`{verdict.get('notes')}`"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def markdown_for_aggregate(aggregate: dict[str, Any]) -> str:
    run = aggregate.get("run") or {}
    lines = ["# OCR Mini Review Aggregate", ""]
    lines.append(f"- Run ID: `{run.get('run_id')}`")
    lines.append(f"- Generated: `{aggregate.get('generated_at_utc')}`")
    lines.append(f"- Pages: `{(aggregate.get('summary') or {}).get('pages')}`")
    lines.append(f"- Candidate page statuses: `{(aggregate.get('summary') or {}).get('candidate_page_status_counts')}`")
    lines.append("")
    lines.append("This aggregate intentionally omits raw OCR text. See the private packet for review text/images.")
    lines.append("")
    lines.append("| csv_row | page | route | labels | candidate | status | chars | blocks | confidence | runtime_s |")
    lines.append("|---:|---:|---|---|---|---|---:|---:|---:|---:|")
    for page in aggregate.get("pages") or []:
        for candidate in page.get("candidates") or []:
            lines.append(
                f"| {page.get('csv_row')} | {page.get('page')} | {page.get('audit_primary_route')} | "
                f"`{page.get('audit_labels')}` | {candidate.get('candidate')} | {candidate.get('page_status')} | "
                f"{candidate.get('text_chars')} | {candidate.get('block_count')} | "
                f"{candidate.get('avg_confidence')} | {candidate.get('runtime_s')} |"
            )
    lines.append("")
    lines.append("Review decisions:")
    lines.append("")
    lines.append("| csv_row | page | review_status | winner |")
    lines.append("|---:|---:|---|---|")
    for page in aggregate.get("pages") or []:
        lines.append(
            f"| {page.get('csv_row')} | {page.get('page')} | "
            f"{page.get('review_status')} | {page.get('review_winner')} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def private_out_dir_default(run_id: str) -> Path:
    return REPO_ROOT / "data/private/real100_v2/ocr_review" / run_id


def report_dir_default(run_id: str) -> Path:
    return REPO_ROOT / "reports/parser_candidate_eval" / run_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a private OCR mini review packet.")
    parser.add_argument(
        "--artifacts",
        nargs="*",
        default=list(DEFAULT_ARTIFACTS),
        help="Route-filtered OCR candidate artifact JSON paths. Defaults to row16/row17 tiny sample artifacts.",
    )
    parser.add_argument("--run-id", default=None, help="Run id. Defaults to ocr-mini-review-<UTC>.")
    parser.add_argument("--out-dir", default=None, help="Private packet output directory.")
    parser.add_argument("--report-dir", default=None, help="Textless aggregate report directory.")
    parser.add_argument("--render-dpi", type=int, default=96)
    parser.add_argument("--no-render-images", action="store_true")
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        artifact_paths = [normalize_path(path) for path in args.artifacts]
        missing = [str(path) for path in artifact_paths if not path.exists()]
        if missing:
            raise CandidateEvalError(f"Missing artifact(s): {', '.join(missing)}")
        run_id = args.run_id or f"ocr-mini-review-{utc_now()}"
        out_dir = Path(args.out_dir) if args.out_dir else private_out_dir_default(run_id)
        report_dir = Path(args.report_dir) if args.report_dir else report_dir_default(run_id)
        run_manifest = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "generated_at_utc": utc_now(),
            "artifact_paths": [str(path) for path in artifact_paths],
            "out_dir": str(out_dir),
            "report_dir": str(report_dir),
            "render_images": not bool(args.no_render_images),
            "render_dpi": args.render_dpi,
        }
        groups = group_artifacts(artifact_paths)
        if not groups:
            raise CandidateEvalError("No pages found in artifact set")
        packet = build_private_packet(
            groups,
            run_manifest=run_manifest,
            out_dir=out_dir,
            render_images=not bool(args.no_render_images),
            render_dpi=args.render_dpi,
        )
        aggregate = summarize_private_packet(packet)
        write_json(out_dir / "review_packet.json", packet)
        (out_dir / "review_packet.md").parent.mkdir(parents=True, exist_ok=True)
        (out_dir / "review_packet.md").write_text(markdown_for_private_packet(packet), encoding="utf-8")
        write_json(report_dir / "ocr_review.aggregate.json", aggregate)
        (report_dir / "ocr_review.md").parent.mkdir(parents=True, exist_ok=True)
        (report_dir / "ocr_review.md").write_text(markdown_for_aggregate(aggregate), encoding="utf-8")
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "out_dir": str(out_dir),
                    "report_dir": str(report_dir),
                    "pages": len(packet.get("pages") or []),
                    "candidate_page_status_counts": aggregate["summary"]["candidate_page_status_counts"],
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
