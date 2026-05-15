#!/usr/bin/env python3
"""Compare two native-parse paths for HWP files (issue #121).

Path A — ``hwp5txt`` (pyhwp CLI): text-only extraction.
Path B — ``libreoffice --headless --convert-to pdf`` followed by the existing
``visual_ingestion.parse_pdf_artifact`` pipeline: text + tables + layout via
the visual-v2 stack.

This is a measurement harness, not a pipeline component. The default HWP
ingestion path (CSV ``텍스트`` column, ADR 0001) is unchanged. Outputs go to
``outputs/hwp_extraction_comparison.json`` (gitignored) and feed
``docs/hwp/hwp-extraction-comparison.md``'s 결과 table.

The script is import-safe and ``--help``-safe without either tool installed;
missing tools are reported per-file as ``skipped`` with a reason, never raised.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


HWP5TXT_BIN = "hwp5txt"
LIBREOFFICE_BINS = ("libreoffice", "soffice")
PER_FILE_TIMEOUT_S = 120
STDERR_TAIL_CHARS = 400
TEXT_SAMPLE_CHARS = 500


def _which_libreoffice() -> str | None:
    for name in LIBREOFFICE_BINS:
        found = shutil.which(name)
        if found:
            return found
    return None


def _stderr_tail(stderr: str | bytes | None) -> str:
    if not stderr:
        return ""
    if isinstance(stderr, bytes):
        try:
            stderr = stderr.decode("utf-8", errors="replace")
        except Exception:
            stderr = repr(stderr)
    return stderr[-STDERR_TAIL_CHARS:]


def run_hwp5txt(source: Path) -> dict[str, Any]:
    """Path A: hwp5txt CLI. Returns a status dict, never raises."""
    if not shutil.which(HWP5TXT_BIN):
        return {"status": "skipped", "reason": "hwp5txt_not_installed"}
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [HWP5TXT_BIN, str(source)],
            capture_output=True,
            timeout=PER_FILE_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "failed", "reason": "timeout", "latency_ms": PER_FILE_TIMEOUT_S * 1000}
    latency_ms = (time.perf_counter() - started) * 1000
    if proc.returncode != 0:
        return {
            "status": "failed",
            "reason": "nonzero_exit",
            "returncode": proc.returncode,
            "stderr_tail": _stderr_tail(proc.stderr),
            "latency_ms": round(latency_ms, 2),
        }
    text = proc.stdout.decode("utf-8", errors="replace")
    return {
        "status": "ok",
        "char_count": len(text),
        "line_count": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
        "text_sample": text[:TEXT_SAMPLE_CHARS],
        "latency_ms": round(latency_ms, 2),
    }


def run_libreoffice_to_pdf(source: Path, outdir: Path) -> dict[str, Any]:
    """Convert HWP → PDF via libreoffice --headless. Returns a status dict."""
    binary = _which_libreoffice()
    if not binary:
        return {"status": "skipped", "reason": "libreoffice_not_installed"}
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [binary, "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(source)],
            capture_output=True,
            timeout=PER_FILE_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "failed", "reason": "timeout", "latency_ms": PER_FILE_TIMEOUT_S * 1000}
    latency_ms = (time.perf_counter() - started) * 1000
    if proc.returncode != 0:
        return {
            "status": "failed",
            "reason": "nonzero_exit",
            "returncode": proc.returncode,
            "stderr_tail": _stderr_tail(proc.stderr),
            "latency_ms": round(latency_ms, 2),
        }
    pdf_path = outdir / (source.stem + ".pdf")
    if not pdf_path.exists():
        return {
            "status": "failed",
            "reason": "pdf_not_produced",
            "stderr_tail": _stderr_tail(proc.stderr),
            "latency_ms": round(latency_ms, 2),
        }
    return {"status": "ok", "pdf_path": str(pdf_path), "latency_ms": round(latency_ms, 2)}


def visual_metrics(artifact: dict[str, Any]) -> dict[str, Any]:
    pages = artifact.get("pages", []) or []
    block_count = sum(len(p.get("blocks", []) or []) for p in pages)
    text_chars = 0
    ocr_block_count = 0
    for page in pages:
        for block in page.get("blocks", []) or []:
            text_chars += len(block.get("text") or "")
            if (block.get("source") or "").startswith("ocr") or (block.get("source") or "") in {"tesseract", "donut"}:
                ocr_block_count += 1
    return {
        "page_count": len(pages),
        "block_count": block_count,
        "char_count": text_chars,
        "table_count": len(artifact.get("tables", []) or []),
        "ocr_block_count": ocr_block_count,
        "diagnostics_reasons": list(artifact.get("diagnostics", {}).get("reasons", []) or []),
    }


def run_libreoffice_path(source: Path, tmpdir: Path) -> dict[str, Any]:
    """Path B: libreoffice → PDF → visual_ingestion.parse_pdf_artifact."""
    convert = run_libreoffice_to_pdf(source, tmpdir)
    if convert["status"] != "ok":
        return convert
    try:
        from visual_ingestion import parse_pdf_artifact
    except Exception as exc:
        return {
            "status": "failed",
            "reason": "visual_ingestion_import_failed",
            "error": str(exc),
            "convert_latency_ms": convert["latency_ms"],
        }

    pdf_path = Path(convert["pdf_path"])
    started = time.perf_counter()
    try:
        artifact = parse_pdf_artifact(
            source_path=pdf_path,
            doc_id=source.stem,
            title=source.stem,
            agency="",
            project="",
            metadata={},
            ocr_provider=None,
        )
    except Exception as exc:
        return {
            "status": "failed",
            "reason": "pdf_parse_exception",
            "error": str(exc),
            "convert_latency_ms": convert["latency_ms"],
        }
    parse_latency_ms = (time.perf_counter() - started) * 1000

    metrics = visual_metrics(artifact)
    return {
        "status": "ok",
        "convert_latency_ms": convert["latency_ms"],
        "parse_latency_ms": round(parse_latency_ms, 2),
        "latency_ms": round(convert["latency_ms"] + parse_latency_ms, 2),
        **metrics,
    }


def summarize(per_file: list[dict[str, Any]]) -> dict[str, Any]:
    def latencies(path_key: str) -> list[float]:
        out = []
        for entry in per_file:
            result = entry.get(path_key) or {}
            if result.get("status") == "ok" and isinstance(result.get("latency_ms"), (int, float)):
                out.append(float(result["latency_ms"]))
        return out

    def char_counts(path_key: str) -> list[int]:
        out = []
        for entry in per_file:
            result = entry.get(path_key) or {}
            if result.get("status") == "ok" and isinstance(result.get("char_count"), int):
                out.append(result["char_count"])
        return out

    def status_breakdown(path_key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in per_file:
            status = (entry.get(path_key) or {}).get("status", "missing")
            counts[status] = counts.get(status, 0) + 1
        return counts

    def stats(values: list[float]) -> dict[str, float] | None:
        if not values:
            return None
        return {
            "n": len(values),
            "median": round(statistics.median(values), 2),
            "p95": round(_p95(values), 2),
            "mean": round(statistics.fmean(values), 2),
        }

    return {
        "file_count": len(per_file),
        "hwp5txt": {
            "status_counts": status_breakdown("hwp5txt"),
            "char_count": stats([float(v) for v in char_counts("hwp5txt")]),
            "latency_ms": stats(latencies("hwp5txt")),
        },
        "libreoffice_visual_v2": {
            "status_counts": status_breakdown("libreoffice_visual_v2"),
            "char_count": stats([float(v) for v in char_counts("libreoffice_visual_v2")]),
            "latency_ms": stats(latencies("libreoffice_visual_v2")),
        },
    }


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return ordered[idx]


def compare_directory(hwp_dir: Path) -> dict[str, Any]:
    files = sorted(p for p in hwp_dir.glob("*.hwp") if p.is_file())
    per_file: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="hwp_cmp_") as raw_tmp:
        tmp = Path(raw_tmp)
        for source in files:
            entry = {
                "file": source.name,
                "size_bytes": source.stat().st_size,
                "hwp5txt": run_hwp5txt(source),
                "libreoffice_visual_v2": run_libreoffice_path(source, tmp),
            }
            per_file.append(entry)
    return {
        "schema_version": 1,
        "hwp_dir": str(hwp_dir),
        "files": per_file,
        "summary": summarize(per_file),
        "tool_availability": {
            "hwp5txt": bool(shutil.which(HWP5TXT_BIN)),
            "libreoffice": bool(_which_libreoffice()),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare hwp5txt vs libreoffice→visual-v2 extraction across an HWP "
            "directory (issue #121). Off-pipeline measurement only."
        )
    )
    parser.add_argument(
        "--hwp-dir",
        type=Path,
        required=True,
        help="Directory containing .hwp files (local-only; ADR 0005 boundary).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "outputs" / "hwp_extraction_comparison.json",
        help="Output JSON path (default: outputs/hwp_extraction_comparison.json, gitignored).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    hwp_dir = args.hwp_dir
    if not hwp_dir.exists() or not hwp_dir.is_dir():
        print(f"error: --hwp-dir does not exist or is not a directory: {hwp_dir}", file=sys.stderr)
        return 2
    report = compare_directory(hwp_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"\nWrote {args.out} ({report['summary']['file_count']} files).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
