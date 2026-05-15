#!/usr/bin/env python3
"""1-page comparison spike: pymupdf+pytesseract baseline vs. Donut vision model.

Generates a synthetic complex-layout PDF with known ground truth, runs both
pipelines, and writes a metrics table. Donut + torch + transformers are lazy-
imported only when --backend includes 'donut'. See docs/vision/vision-spike.md and
issue #168 for context.

Usage:
    python scripts/run_donut_spike.py                     # both, stdout only
    python scripts/run_donut_spike.py --write-doc         # update docs/vision/vision-spike.md
    python scripts/run_donut_spike.py --input <pdf>       # use real PDF (no GT metrics)
    python scripts/run_donut_spike.py --backend baseline  # skip Donut
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from visual_ingestion import (  # noqa: E402
    DEFAULT_DONUT_MODEL,
    classify_layout_block,
    extract_field_candidates,
    extract_table_candidates,
    parse_visual_document,
    tesseract_ocr_provider,
)


@dataclass
class GroundTruth:
    full_text: str
    headings: list[str]
    table_cells: list[str]
    fields: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class PipelineResult:
    label: str
    full_text: str
    headings: list[str]
    table_cells: list[str]
    fields: list[tuple[str, str]]
    latency_seconds: float
    error: str | None = None


def generate_complex_layout_pdf(path: Path) -> GroundTruth:
    """Generate a 1-page PDF with title / metadata / fields / table / paragraph.

    Uses ASCII-only content so fitz base14 fonts render correctly without
    requiring a system Korean font. Real Korean RFPs can be passed via --input.
    """
    import fitz  # type: ignore

    headings = ["1. Overview", "2. Requirements", "3. Evaluation"]
    fields_dict = {
        "Project": "AI Document Intelligence RFP Visual Spike",
        "Agency": "Public Data Authority",
        "Budget": "USD 180,000",
        "Published": "2026-05-11",
    }
    table_rows = [
        ["Area", "Requirement", "Note"],
        ["Security", "Access control", "Mandatory"],
        ["Logging", "Audit trail", "Recommended"],
        ["Performance", "p95 800ms", "Measured"],
    ]
    body = (
        "This spike compares the OCR baseline against a layout-aware Donut model "
        "on a single complex-layout RFP page. See docs/vision/vision-spike.md for context."
    )

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 56
    page.insert_text((56, y), "RFP Visual Parsing Spike", fontsize=16)
    y += 30

    page.insert_text((56, y), "1. Overview", fontsize=13)
    y += 20
    for k, v in fields_dict.items():
        page.insert_text((56, y), f"{k}: {v}", fontsize=10)
        y += 16
    y += 8

    page.insert_text((56, y), "2. Requirements", fontsize=13)
    y += 20
    for row in table_rows:
        line = "  |  ".join(row)
        page.insert_text((56, y), line, fontsize=10)
        y += 16
    y += 8

    page.insert_text((56, y), "3. Evaluation", fontsize=13)
    y += 20
    page.insert_text((56, y), body, fontsize=10)

    doc.save(path)
    doc.close()

    table_cells = [cell for row in table_rows for cell in row]
    full_text_parts = [
        "RFP Visual Parsing Spike",
        *headings,
        *(f"{k}: {v}" for k, v in fields_dict.items()),
        *(" ".join(row) for row in table_rows),
        body,
    ]
    return GroundTruth(
        full_text="\n".join(full_text_parts),
        headings=headings,
        table_cells=table_cells,
        fields=list(fields_dict.items()),
    )


def run_baseline(pdf_path: Path) -> PipelineResult:
    start = time.perf_counter()
    document, artifact = parse_visual_document(
        pdf_path,
        doc_id="spike-baseline",
        title=pdf_path.stem,
        ocr_provider=tesseract_ocr_provider,
    )
    elapsed = time.perf_counter() - start
    if artifact["diagnostics"]["status"] == "failed":
        return PipelineResult(
            label="pymupdf+pytesseract",
            full_text="",
            headings=[],
            table_cells=[],
            fields=[],
            latency_seconds=elapsed,
            error=str(artifact["diagnostics"].get("reasons")),
        )
    blocks = [block for page in artifact["pages"] for block in page["blocks"]]
    full_text = "\n".join(block["text"] for block in blocks)
    headings = [block["text"].splitlines()[0] for block in blocks if block.get("type") == "heading"]
    table_cells = [cell for table in artifact["tables"] for row in table["rows"] for cell in row]
    fields = [(c["key"], c["value"]) for c in artifact["field_candidates"]]
    return PipelineResult(
        label="pymupdf+pytesseract",
        full_text=full_text,
        headings=headings,
        table_cells=table_cells,
        fields=fields,
        latency_seconds=elapsed,
    )


def run_donut(pdf_path: Path) -> PipelineResult:
    try:
        import fitz  # type: ignore
        from PIL import Image  # type: ignore
    except Exception as exc:
        return PipelineResult(
            label=f"donut ({os.environ.get('BIDMATE_DONUT_MODEL', DEFAULT_DONUT_MODEL)})",
            full_text="",
            headings=[],
            table_cells=[],
            fields=[],
            latency_seconds=0.0,
            error=f"pymupdf or pillow missing: {exc}",
        )
    try:
        from visual_ingestion import donut_ocr_provider
    except Exception as exc:
        return PipelineResult(
            label=f"donut ({os.environ.get('BIDMATE_DONUT_MODEL', DEFAULT_DONUT_MODEL)})",
            full_text="",
            headings=[],
            table_cells=[],
            fields=[],
            latency_seconds=0.0,
            error=f"donut import failed: {exc}",
        )

    start = time.perf_counter()
    page_texts: list[str] = []
    error: str | None = None
    try:
        pdf_doc = fitz.open(str(pdf_path))
        with pdf_doc:
            for page in pdf_doc:
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                page_texts.append(donut_ocr_provider(image))
    except Exception as exc:
        error = f"donut inference failed: {exc}"
    elapsed = time.perf_counter() - start

    full_text = strip_donut_tags("\n".join(page_texts))
    if not full_text and not error:
        error = "donut produced empty text"

    pseudo_blocks = [
        {
            "text": full_text,
            "page_number": 1,
            "bbox": None,
            "source": "donut",
            "confidence": 1.0,
        }
    ]
    headings = [line.strip() for line in full_text.splitlines() if classify_layout_block(line) == "heading"]
    table_cells = [cell for table in extract_table_candidates(pseudo_blocks) for row in table["rows"] for cell in row]
    fields = [(c["key"], c["value"]) for c in extract_field_candidates(pseudo_blocks)]

    return PipelineResult(
        label=f"donut ({os.environ.get('BIDMATE_DONUT_MODEL', DEFAULT_DONUT_MODEL)})",
        full_text=full_text,
        headings=headings,
        table_cells=table_cells,
        fields=fields,
        latency_seconds=elapsed,
        error=error,
    )


def run_paddleocr(pdf_path: Path) -> PipelineResult:
    try:
        import fitz  # type: ignore
        from PIL import Image  # type: ignore
    except Exception as exc:
        return PipelineResult(
            label="paddleocr (PP-OCRv4)",
            full_text="", headings=[], table_cells=[], fields=[],
            latency_seconds=0.0,
            error=f"pymupdf or pillow missing: {exc}",
        )
    try:
        from visual_ingestion import paddleocr_provider
    except Exception as exc:
        return PipelineResult(
            label="paddleocr (PP-OCRv4)",
            full_text="", headings=[], table_cells=[], fields=[],
            latency_seconds=0.0,
            error=f"paddleocr import failed: {exc}",
        )

    start = time.perf_counter()
    error: str | None = None
    artifact: dict[str, Any] = {}
    try:
        _, artifact = parse_visual_document(
            pdf_path, doc_id="spike-paddleocr", title=pdf_path.stem, ocr_provider=paddleocr_provider
        )
    except Exception as exc:
        error = f"paddleocr inference failed: {exc}"
    elapsed = time.perf_counter() - start

    if artifact and artifact.get("diagnostics", {}).get("status") == "failed":
        error = str(artifact["diagnostics"].get("reasons"))

    blocks = [block for page in artifact.get("pages", []) for block in page.get("blocks", [])]
    full_text = "\n".join(str(b.get("text") or "") for b in blocks).strip()
    if not full_text and not error:
        error = "paddleocr produced empty text"
    headings = [str(b.get("text") or "").strip() for b in blocks if b.get("type") == "heading"]
    table_cells = [cell for table in (artifact.get("tables") or []) for row in table.get("rows", []) for cell in row]
    fields = [(c["key"], c["value"]) for c in (artifact.get("field_candidates") or [])]
    return PipelineResult(
        label="paddleocr (PP-OCRv4)",
        full_text=full_text,
        headings=headings,
        table_cells=table_cells,
        fields=fields,
        latency_seconds=elapsed,
        error=error,
    )


def strip_donut_tags(text: str) -> str:
    return re.sub(r"</?s_[^>]+>", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"\s+", text.lower().strip()) if t}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def coverage(needles: list[str], haystack: str) -> tuple[int, int]:
    matched = sum(1 for n in needles if n.strip() and n.strip() in haystack)
    return matched, len(needles)


def field_pr(extracted: list[tuple[str, str]], expected: list[tuple[str, str]]) -> tuple[float, float]:
    e_set = {(k.strip(), v.strip()) for k, v in extracted}
    x_set = {(k.strip(), v.strip()) for k, v in expected}
    tp = len(e_set & x_set)
    p = tp / len(e_set) if e_set else 0.0
    r = tp / len(x_set) if x_set else 0.0
    return p, r


def compute_metrics(result: PipelineResult, gt: GroundTruth | None) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "label": result.label,
        "latency_s": round(result.latency_seconds, 3),
        "error": result.error,
    }
    if gt is None:
        metrics.update(
            {
                "text_chars": len(result.full_text),
                "headings_found": len(result.headings),
                "table_cells_found": len(result.table_cells),
                "fields_found": len(result.fields),
            }
        )
        return metrics
    text_recall = jaccard(tokenize(result.full_text), tokenize(gt.full_text))
    h_match, h_total = coverage(gt.headings, result.full_text)
    cell_match, cell_total = coverage(gt.table_cells, result.full_text)
    f_p, f_r = field_pr(result.fields, gt.fields)
    metrics.update(
        {
            "text_recall_jaccard": round(text_recall, 3),
            "heading_recall": round(h_match / h_total, 3) if h_total else 0.0,
            "heading_match": f"{h_match}/{h_total}",
            "table_cell_recall": round(cell_match / cell_total, 3) if cell_total else 0.0,
            "table_cell_match": f"{cell_match}/{cell_total}",
            "field_p": round(f_p, 3),
            "field_r": round(f_r, 3),
        }
    )
    return metrics


def render_markdown_table(rows: list[dict[str, Any]], gt_available: bool) -> str:
    if gt_available:
        cols = [
            ("metric", "Metric"),
            ("text_recall_jaccard", "text_recall"),
            ("heading_match", "heading_match"),
            ("table_cell_match", "table_cell_match"),
            ("field_p", "field_p"),
            ("field_r", "field_r"),
            ("latency_s", "latency_s"),
        ]
    else:
        cols = [
            ("metric", "Metric"),
            ("text_chars", "text_chars"),
            ("headings_found", "headings_found"),
            ("table_cells_found", "table_cells_found"),
            ("fields_found", "fields_found"),
            ("latency_s", "latency_s"),
        ]
    header = "| " + " | ".join(c[1] for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = [header, sep]
    for row in rows:
        cells = [row["label"]] + [str(row.get(k, "")) for k, _ in cols[1:]]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_doc_results(doc_path: Path, table_md: str, gt_available: bool, errors: list[str]) -> None:
    if not doc_path.exists():
        raise FileNotFoundError(f"docs file missing: {doc_path}. Create the scaffold first.")
    body = doc_path.read_text(encoding="utf-8")
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S %z")
    note = (
        f"_Generated by `scripts/run_donut_spike.py` at {timestamp}. "
        f"Ground truth: {'synthetic generated PDF' if gt_available else 'user-provided PDF (no GT)'}._"
    )
    error_block = ""
    if errors:
        error_block = "\n\n**Errors:**\n" + "\n".join(f"- {e}" for e in errors)
    new_section = f"## Results\n\n{note}\n\n{table_md}{error_block}\n"
    pattern = re.compile(r"## Results.*?(?=\n## |\Z)", re.DOTALL)
    if pattern.search(body):
        body = pattern.sub(new_section, body)
    else:
        body = body.rstrip() + "\n\n" + new_section
    doc_path.write_text(body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Donut vs OCR 1-page comparison spike (issue #168).")
    parser.add_argument("--input", type=Path, default=None, help="optional real PDF path; default = synthetic")
    parser.add_argument("--backend", choices=["both", "baseline", "donut", "paddleocr", "all"], default="both")
    parser.add_argument("--write-doc", action="store_true", help="update docs/vision/vision-spike.md Results section")
    parser.add_argument("--doc-path", type=Path, default=REPO_ROOT / "docs" / "vision-spike.md")
    args = parser.parse_args(argv)

    gt: GroundTruth | None = None
    if args.input is not None:
        pdf_path = args.input
        if not pdf_path.exists():
            print(f"input PDF not found: {pdf_path}", file=sys.stderr)
            return 2
    else:
        tmp_dir = REPO_ROOT / "artifacts" / "runs" / "donut_spike"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = tmp_dir / "synthetic_complex_layout.pdf"
        gt = generate_complex_layout_pdf(pdf_path)
        print(f"generated synthetic PDF: {pdf_path}")

    results: list[PipelineResult] = []
    if args.backend in ("both", "baseline", "all"):
        results.append(run_baseline(pdf_path))
    if args.backend in ("both", "donut", "all"):
        results.append(run_donut(pdf_path))
    if args.backend in ("paddleocr", "all"):
        results.append(run_paddleocr(pdf_path))

    rows = [compute_metrics(r, gt) for r in results]
    table_md = render_markdown_table(rows, gt_available=gt is not None)
    print()
    print(table_md)
    print()
    for r, m in zip(results, rows):
        if r.error:
            print(f"[error] {r.label}: {r.error}", file=sys.stderr)
    print(json.dumps([_serializable(m) for m in rows], ensure_ascii=False, indent=2))

    if args.write_doc:
        errors = [f"{r.label}: {r.error}" for r in results if r.error]
        write_doc_results(args.doc_path, table_md, gt is not None, errors)
        print(f"\nwrote results to {args.doc_path}")

    return 0


def _serializable(metrics: dict[str, Any]) -> dict[str, Any]:
    return {k: (v if not isinstance(v, set) else sorted(v)) for k, v in metrics.items()}


if __name__ == "__main__":
    raise SystemExit(main())
