#!/usr/bin/env python3
"""Run a minimal parser-candidate bake-off on path-level real100_v2 PDFs.

This harness is intentionally small and additive. It does not change canonical
indexing or ingestion defaults. Raw per-page parser output is written under a
local/private run directory; aggregate summaries should be produced with
``scripts/summarize_parser_candidate_eval.py``.
"""

from __future__ import annotations

import argparse
import datetime as _dt
from collections import Counter, defaultdict
import importlib.metadata as importlib_metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = 1
RUN_MANIFEST = "run_manifest.json"
SUMMARY_FILENAME = "parser_candidate_eval_summary.json"
SUPPORTED_CANDIDATES = (
    "pymupdf4llm_current",
    "pdfplumber_table_sidecar",
)
REQUIRED_METADATA_KEYS = (
    "공고 번호",
    "공고 차수",
    "사업명",
    "사업 금액",
    "발주 기관",
    "공개 일자",
    "입찰 참여 시작일",
    "입찰 참여 마감일",
    "파일명",
)
MOJIBAKE_MARKERS = ("�", "Ã", "Â", "ì", "í", "ë")
PYMUPDF4LLM_USE_OCR_ENV = "BIDMATE_PYMUPDF4LLM_USE_OCR"
PYMUPDF4LLM_OCR_LANGUAGE_ENV = "BIDMATE_PYMUPDF4LLM_OCR_LANGUAGE"
PYMUPDF4LLM_EVAL_DEFAULT_USE_OCR = False
PYMUPDF4LLM_EVAL_DEFAULT_OCR_LANGUAGE = "kor+eng"
PYMUPDF4LLM_EVAL_DEFAULT_TIMEOUT_S = 120.0


class CandidateEvalError(RuntimeError):
    """Raised when the eval harness cannot safely continue."""


def utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def today_iso() -> str:
    return _dt.datetime.now(_dt.UTC).date().isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def package_version(distribution: str) -> str | None:
    try:
        return importlib_metadata.version(distribution)
    except importlib_metadata.PackageNotFoundError:
        return None


def parse_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def resolve_pymupdf4llm_ocr_options(
    *,
    use_ocr: bool | None = None,
    ocr_language: str | None = None,
) -> tuple[bool, str]:
    """Resolve PyMuPDF4LLM OCR options for the eval control.

    This intentionally differs from the canonical ingestion runtime default:
    the candidate-eval control should measure text-layer/page-citation behavior
    without document-wide OCR unless the run explicitly opts in.
    """

    resolved_use_ocr = (
        bool(use_ocr)
        if use_ocr is not None
        else parse_bool(
            os.environ.get(PYMUPDF4LLM_USE_OCR_ENV),
            default=PYMUPDF4LLM_EVAL_DEFAULT_USE_OCR,
        )
    )
    resolved_language = (
        ocr_language
        or os.environ.get(PYMUPDF4LLM_OCR_LANGUAGE_ENV)
        or PYMUPDF4LLM_EVAL_DEFAULT_OCR_LANGUAGE
    )
    resolved_language = resolved_language.strip() or PYMUPDF4LLM_EVAL_DEFAULT_OCR_LANGUAGE
    return resolved_use_ocr, resolved_language


def parse_candidates(raw: str) -> list[str]:
    candidates = [item.strip() for item in raw.split(",") if item.strip()]
    if not candidates:
        raise CandidateEvalError("--candidates must include at least one candidate")
    unknown = [candidate for candidate in candidates if candidate not in SUPPORTED_CANDIDATES]
    if unknown:
        raise CandidateEvalError(
            f"Unsupported candidate(s): {', '.join(unknown)}. "
            f"Supported: {', '.join(SUPPORTED_CANDIDATES)}"
        )
    return candidates


def load_manifest_rows(path: Path) -> dict[int, dict[str, Any]]:
    data = read_json(path)
    if not isinstance(data, list):
        raise CandidateEvalError(f"Manifest must be a JSON list: {path}")
    rows: dict[int, dict[str, Any]] = {}
    for item in data:
        if not isinstance(item, dict):
            raise CandidateEvalError("Manifest entries must be JSON objects")
        try:
            csv_row = int(item["csv_row"])
        except Exception as exc:  # noqa: BLE001 - turn malformed local artifact into a clear error
            raise CandidateEvalError(f"Manifest row missing integer csv_row: {item!r}") from exc
        if csv_row in rows:
            raise CandidateEvalError(f"Duplicate csv_row in manifest: {csv_row}")
        rows[csv_row] = item
    return rows


def load_subset_rows(path: Path) -> list[dict[str, Any]]:
    data = read_json(path)
    if isinstance(data, dict):
        data = data.get("rows") or data.get("documents") or data.get("subset")
    if not isinstance(data, list) or not data:
        raise CandidateEvalError(f"Subset must be a non-empty JSON list: {path}")
    subset: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in data:
        if isinstance(item, int):
            csv_row = item
            reason = "selected"
            rank = len(subset) + 1
        elif isinstance(item, dict):
            try:
                csv_row = int(item["csv_row"])
            except Exception as exc:  # noqa: BLE001
                raise CandidateEvalError(f"Subset entry missing integer csv_row: {item!r}") from exc
            reason = str(item.get("reason") or "selected")
            rank = int(item.get("rank") or len(subset) + 1)
        else:
            raise CandidateEvalError(f"Unsupported subset entry: {item!r}")
        if csv_row in seen:
            raise CandidateEvalError(f"Duplicate csv_row in subset: {csv_row}")
        seen.add(csv_row)
        subset.append({"csv_row": csv_row, "reason": reason, "rank": rank})
    return subset


def selected_rows(manifest: dict[int, dict[str, Any]], subset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for subset_entry in sorted(subset, key=lambda item: int(item["rank"])):
        csv_row = int(subset_entry["csv_row"])
        row = manifest.get(csv_row)
        if row is None:
            raise CandidateEvalError(f"Subset csv_row not present in manifest: {csv_row}")
        merged = dict(row)
        merged["subset_reason"] = subset_entry["reason"]
        merged["subset_rank"] = subset_entry["rank"]
        pdf_path = Path(str(merged.get("path_pdf") or ""))
        if not pdf_path.is_absolute():
            pdf_path = REPO_ROOT / pdf_path
        if not pdf_path.is_file():
            raise CandidateEvalError(f"path_pdf missing for csv_row {csv_row}: {pdf_path}")
        merged["_absolute_path_pdf"] = str(pdf_path)
        selected.append(merged)
    return selected


def slug_for_doc_id(value: str) -> str:
    stem = Path(value).stem if value else "document"
    stem = re.sub(r"\s+", "-", stem.strip())
    stem = re.sub(r"[\\/:*?\"<>|]+", "-", stem)
    return stem[:120] or "document"


def make_doc_id(row: dict[str, Any]) -> str:
    return f"real100_v2:path:{int(row['csv_row'])}:{slug_for_doc_id(str(row.get('path_pdf') or row.get('source_file') or 'document'))}"


def normalize_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return dict(metadata)


def base_artifact(candidate: str, row: dict[str, Any], *, status: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate": candidate,
        "candidate_version": None,
        "provider": "local",
        "status": status,
        "csv_row": int(row["csv_row"]),
        "subset_rank": int(row.get("subset_rank") or 0),
        "subset_reason": row.get("subset_reason") or "selected",
        "doc_id": make_doc_id(row),
        "source_file": row.get("source_file"),
        "source_sha256": row.get("source_sha256"),
        "path_pdf": row.get("path_pdf"),
        "expected_page_count": int(row.get("page_count") or 0),
        "metadata": normalize_metadata(row),
        "pages": [],
        "elements": [],
        "provenance": {
            "date": today_iso(),
            "runtime_s": 0.0,
            "cost_usd": None,
            "model": None,
        },
        "failure": None,
    }


def failure_artifact(
    candidate: str,
    row: dict[str, Any],
    *,
    status: str,
    code: str,
    message: str,
    runtime_s: float = 0.0,
    version: str | None = None,
) -> dict[str, Any]:
    artifact = base_artifact(candidate, row, status=status)
    artifact["candidate_version"] = version
    artifact["provenance"]["runtime_s"] = round(runtime_s, 4)
    artifact["failure"] = {"code": code, "message": message}
    return artifact


def page_number_from_chunk(chunk: dict[str, Any], fallback: int) -> int:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    for key in ("page_number", "page"):
        value = metadata.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return fallback


def pymupdf4llm_to_markdown(
    pdf_path: str,
    *,
    use_ocr: bool,
    ocr_language: str,
    timeout_s: float | None,
) -> Any:
    if timeout_s is None:
        import pymupdf4llm  # type: ignore  # noqa: PLC0415

        return pymupdf4llm.to_markdown(
            pdf_path,
            page_chunks=True,
            use_ocr=use_ocr,
            ocr_language=ocr_language,
        )

    with tempfile.NamedTemporaryFile(
        prefix="bidmate_parser_eval_pymupdf4llm_",
        suffix=".json",
        delete=False,
    ) as handle:
        output_path = Path(handle.name)
    worker = r"""
import json
from pathlib import Path
import sys

import pymupdf4llm

pdf_path = sys.argv[1]
output_path = Path(sys.argv[2])
use_ocr = sys.argv[3] == "1"
ocr_language = sys.argv[4]
output = pymupdf4llm.to_markdown(
    pdf_path,
    page_chunks=True,
    use_ocr=use_ocr,
    ocr_language=ocr_language,
)
output_path.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
"""
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                worker,
                pdf_path,
                str(output_path),
                "1" if use_ocr else "0",
                ocr_language,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output_path.unlink(missing_ok=True)
        raise TimeoutError(f"timeout after {timeout_s:g}s") from exc
    if proc.returncode != 0:
        output_path.unlink(missing_ok=True)
        stderr = (proc.stderr or "").strip().splitlines()
        tail = stderr[-1] if stderr else f"subprocess_exit_{proc.returncode}"
        raise CandidateEvalError(tail)
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    finally:
        output_path.unlink(missing_ok=True)


def run_pymupdf4llm_current(
    row: dict[str, Any],
    *,
    use_ocr: bool,
    ocr_language: str,
    timeout_s: float | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    version = package_version("pymupdf4llm")
    if version is None:
        return failure_artifact(
            "pymupdf4llm_current",
            row,
            status="skipped",
            code="dependency_unavailable",
            message="pymupdf4llm is not installed",
            version=version,
        )
    try:
        import pymupdf4llm  # type: ignore  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return failure_artifact(
            "pymupdf4llm_current",
            row,
            status="skipped",
            code="dependency_unavailable",
            message=f"{type(exc).__name__}: {exc}",
            version=version,
        )

    artifact = base_artifact("pymupdf4llm_current", row, status="ok")
    artifact["candidate_version"] = version
    artifact["provenance"].update(
        {
            "use_ocr": use_ocr,
            "ocr_language": ocr_language,
            "page_chunks": True,
            "timeout_s": timeout_s,
        }
    )
    try:
        output = pymupdf4llm_to_markdown(
            str(row["_absolute_path_pdf"]),
            use_ocr=use_ocr,
            ocr_language=ocr_language,
            timeout_s=timeout_s,
        )
        if isinstance(output, str):
            text = output.strip()
            artifact["pages"].append({"page": 1, "markdown": text, "chars": len(text), "tables": [], "warnings": []})
            if text:
                artifact["elements"].append(
                    {"type": "paragraph", "page_span": [1, 1], "text": text, "bbox": None}
                )
        elif isinstance(output, list):
            for index, chunk in enumerate(output, start=1):
                if not isinstance(chunk, dict):
                    continue
                text = str(chunk.get("text") or "").strip()
                page_number = page_number_from_chunk(chunk, index)
                warnings = [] if text else ["empty_page_chunk"]
                artifact["pages"].append(
                    {
                        "page": page_number,
                        "markdown": text,
                        "chars": len(text),
                        "tables": [],
                        "warnings": warnings,
                    }
                )
                if text:
                    artifact["elements"].append(
                        {
                            "type": "paragraph",
                            "page_span": [page_number, page_number],
                            "text": text,
                            "bbox": None,
                        }
                    )
        else:
            raise CandidateEvalError(f"pymupdf4llm returned unsupported type: {type(output).__name__}")
    except TimeoutError as exc:
        return failure_artifact(
            "pymupdf4llm_current",
            row,
            status="failed",
            code="parse_timeout",
            message=str(exc),
            runtime_s=time.perf_counter() - started,
            version=version,
        )
    except Exception as exc:  # noqa: BLE001
        return failure_artifact(
            "pymupdf4llm_current",
            row,
            status="failed",
            code="parse_failed",
            message=f"{type(exc).__name__}: {exc}",
            runtime_s=time.perf_counter() - started,
            version=version,
        )
    artifact["provenance"]["runtime_s"] = round(time.perf_counter() - started, 4)
    return artifact


def table_to_markdown(rows: list[list[Any]]) -> str:
    normalized = [["" if cell is None else str(cell).replace("\n", " ").strip() for cell in row] for row in rows]
    if not normalized:
        return ""
    width = max(len(row) for row in normalized)
    normalized = [row + [""] * (width - len(row)) for row in normalized]
    lines = ["| " + " | ".join(row) + " |" for row in normalized]
    return "\n".join(lines)


def run_pdfplumber_table_sidecar(row: dict[str, Any], *, max_pages: int | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    version = package_version("pdfplumber")
    if version is None:
        return failure_artifact(
            "pdfplumber_table_sidecar",
            row,
            status="skipped",
            code="dependency_unavailable",
            message="pdfplumber is not installed",
            version=version,
        )
    try:
        import pdfplumber  # type: ignore  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return failure_artifact(
            "pdfplumber_table_sidecar",
            row,
            status="skipped",
            code="dependency_unavailable",
            message=f"{type(exc).__name__}: {exc}",
            version=version,
        )

    artifact = base_artifact("pdfplumber_table_sidecar", row, status="ok")
    artifact["candidate_version"] = version
    artifact["provenance"].update({"mode": "text_plus_find_tables", "max_pages": max_pages})
    try:
        with pdfplumber.open(str(row["_absolute_path_pdf"])) as pdf:
            pages = pdf.pages if not max_pages or max_pages < 1 else pdf.pages[:max_pages]
            for page_index, page in enumerate(pages, start=1):
                page_number = int(getattr(page, "page_number", page_index) or page_index)
                text = (page.extract_text() or "").strip()
                page_tables = []
                for table_index, table in enumerate(page.find_tables(), start=1):
                    rows = table.extract() or []
                    nonempty_cells = sum(1 for table_row in rows for cell in table_row if str(cell or "").strip())
                    total_cells = sum(len(table_row) for table_row in rows)
                    table_record = {
                        "table_id": f"{artifact['doc_id']}::p{page_number:03d}::table{table_index:03d}",
                        "page": page_number,
                        "table_index": table_index,
                        "bbox": list(table.bbox) if getattr(table, "bbox", None) else None,
                        "rows": rows,
                        "row_count": len(rows),
                        "column_count": max((len(table_row) for table_row in rows), default=0),
                        "total_cells": total_cells,
                        "nonempty_cells": nonempty_cells,
                    }
                    page_tables.append(table_record)
                    artifact["elements"].append(
                        {
                            "type": "table",
                            "page_span": [page_number, page_number],
                            "text": table_to_markdown(rows),
                            "bbox": table_record["bbox"],
                            "table_id": table_record["table_id"],
                        }
                    )
                if text:
                    artifact["elements"].append(
                        {"type": "paragraph", "page_span": [page_number, page_number], "text": text, "bbox": None}
                    )
                artifact["pages"].append(
                    {
                        "page": page_number,
                        "markdown": text,
                        "chars": len(text),
                        "tables": page_tables,
                        "warnings": [] if text or page_tables else ["empty_pdfplumber_page"],
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return failure_artifact(
            "pdfplumber_table_sidecar",
            row,
            status="failed",
            code="parse_failed",
            message=f"{type(exc).__name__}: {exc}",
            runtime_s=time.perf_counter() - started,
            version=version,
        )
    artifact["provenance"]["runtime_s"] = round(time.perf_counter() - started, 4)
    return artifact


def run_candidate(
    candidate: str,
    row: dict[str, Any],
    *,
    pdfplumber_max_pages: int | None = None,
    pymupdf4llm_use_ocr: bool,
    pymupdf4llm_ocr_language: str,
    pymupdf4llm_timeout_s: float | None,
) -> dict[str, Any]:
    if candidate == "pymupdf4llm_current":
        return run_pymupdf4llm_current(
            row,
            use_ocr=pymupdf4llm_use_ocr,
            ocr_language=pymupdf4llm_ocr_language,
            timeout_s=pymupdf4llm_timeout_s,
        )
    if candidate == "pdfplumber_table_sidecar":
        return run_pdfplumber_table_sidecar(row, max_pages=pdfplumber_max_pages)
    raise CandidateEvalError(f"Unsupported candidate: {candidate}")


def candidate_artifact_path(run_dir: Path, candidate: str, csv_row: int) -> Path:
    return run_dir / "candidates" / candidate / f"row-{csv_row:04d}.json"


def run_dir_default(manifest_path: Path, run_id: str) -> Path:
    # data/private/real100_v2/converted_pdfs_by_path/manifest.json ->
    # data/private/real100_v2/parser_candidate_eval/<run_id>
    return manifest_path.parent.parent / "parser_candidate_eval" / run_id


def report_dir_default(run_id: str) -> Path:
    return REPO_ROOT / "reports" / "parser_candidate_eval" / run_id


def valid_page_span(value: Any, expected_page_count: int) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    start, end = value
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in (start, end)):
        return False
    if start < 1 or end < start:
        return False
    return expected_page_count <= 0 or end <= expected_page_count


def iter_tables(artifact: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for page in artifact.get("pages") or []:
        if not isinstance(page, dict):
            continue
        for table in page.get("tables") or []:
            if isinstance(table, dict):
                yield table


def compute_artifact_metrics(artifact: dict[str, Any]) -> dict[str, Any]:
    pages = [page for page in artifact.get("pages") or [] if isinstance(page, dict)]
    elements = [element for element in artifact.get("elements") or [] if isinstance(element, dict)]
    expected_pages = int(artifact.get("expected_page_count") or 0)
    pages_seen = len({int(page.get("page") or 0) for page in pages if int(page.get("page") or 0) > 0})
    nonempty_pages = sum(1 for page in pages if int(page.get("chars") or 0) > 0 or page.get("tables"))
    total_chars = sum(int(page.get("chars") or 0) for page in pages)
    markdown = "\n".join(str(page.get("markdown") or "") for page in pages)
    hangul = sum(1 for char in markdown if "가" <= char <= "힣")
    mojibake_count = sum(markdown.count(marker) for marker in MOJIBAKE_MARKERS)
    valid_spans = sum(1 for element in elements if valid_page_span(element.get("page_span"), expected_pages))
    tables = list(iter_tables(artifact))
    table_cells = sum(int(table.get("total_cells") or 0) for table in tables)
    nonempty_table_cells = sum(int(table.get("nonempty_cells") or 0) for table in tables)
    metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
    metadata_present = sum(1 for key in REQUIRED_METADATA_KEYS if str(metadata.get(key) or "").strip())
    runtime_s = float((artifact.get("provenance") or {}).get("runtime_s") or 0.0)
    return {
        "status": artifact.get("status") or "unknown",
        "expected_page_count": expected_pages,
        "pages_seen": pages_seen,
        "page_count_agreement": expected_pages == pages_seen if expected_pages else None,
        "pages_seen_rate": round(pages_seen / expected_pages, 4) if expected_pages else None,
        "nonempty_page_rate": round(nonempty_pages / expected_pages, 4) if expected_pages else None,
        "element_count": len(elements),
        "page_span_coverage": round(valid_spans / len(elements), 4) if elements else 0.0,
        "total_chars": total_chars,
        "hangul_ratio": round(hangul / total_chars, 4) if total_chars else 0.0,
        "mojibake_count": mojibake_count,
        "total_tables": len(tables),
        "table_cells": table_cells,
        "nonempty_table_cells": nonempty_table_cells,
        "table_nonempty_cell_rate": round(nonempty_table_cells / table_cells, 4) if table_cells else None,
        "metadata_required_present": metadata_present,
        "metadata_required_present_rate": round(metadata_present / len(REQUIRED_METADATA_KEYS), 4),
        "runtime_s": round(runtime_s, 4),
        "runtime_s_per_expected_page": round(runtime_s / expected_pages, 4) if expected_pages else None,
    }


def weighted_rate(numerators: Iterable[float], denominators: Iterable[float]) -> float | None:
    num = sum(numerators)
    den = sum(denominators)
    if den == 0:
        return None
    return round(num / den, 4)


def mean(values: Iterable[float | int | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 4)


def duplicate_alias_checks(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in docs:
        sha = str(doc.get("source_sha256") or "")
        if sha:
            groups[sha].append(doc)
    checks = []
    for sha, grouped in sorted(groups.items()):
        if len(grouped) < 2:
            continue
        doc_ids = [str(doc.get("doc_id") or "") for doc in grouped]
        csv_rows = [int(doc.get("csv_row") or 0) for doc in grouped]
        metadata_fingerprints = {
            json.dumps(doc.get("metadata") or {}, ensure_ascii=False, sort_keys=True) for doc in grouped
        }
        checks.append(
            {
                "source_sha256": sha,
                "csv_rows": csv_rows,
                "doc_ids": doc_ids,
                "unique_doc_ids": len(set(doc_ids)),
                "metadata_variants": len(metadata_fingerprints),
                "ok": len(set(doc_ids)) == len(doc_ids) and len(set(csv_rows)) == len(csv_rows),
            }
        )
    return checks


def summarize_candidate_docs(candidate: str, docs: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [doc["metrics"] for doc in docs]
    failure_counts = Counter(
        str((doc.get("failure") or {}).get("code") or "none")
        for doc in docs
        if doc.get("status") != "ok"
    )
    duplicate_checks = duplicate_alias_checks(docs)
    expected_pages = sum(int(item.get("expected_page_count") or 0) for item in metrics)
    pages_seen = sum(int(item.get("pages_seen") or 0) for item in metrics)
    nonempty_pages_num = sum(
        (float(item.get("nonempty_page_rate") or 0.0) * int(item.get("expected_page_count") or 0))
        for item in metrics
    )
    total_chars = sum(int(item.get("total_chars") or 0) for item in metrics)
    hangul_num = sum(float(item.get("hangul_ratio") or 0.0) * int(item.get("total_chars") or 0) for item in metrics)
    table_cells = sum(int(item.get("table_cells") or 0) for item in metrics)
    nonempty_table_cells = sum(int(item.get("nonempty_table_cells") or 0) for item in metrics)
    runtime_s = sum(float(item.get("runtime_s") or 0.0) for item in metrics)
    return {
        "candidate": candidate,
        "documents": len(docs),
        "ok": sum(1 for doc in docs if doc.get("status") == "ok"),
        "skipped": sum(1 for doc in docs if doc.get("status") == "skipped"),
        "failed": sum(1 for doc in docs if doc.get("status") == "failed"),
        "parse_success_rate": round(sum(1 for doc in docs if doc.get("status") == "ok") / len(docs), 4)
        if docs
        else None,
        "page_count_agreement_rate": mean(1.0 if item.get("page_count_agreement") else 0.0 for item in metrics),
        "pages_seen_rate": round(pages_seen / expected_pages, 4) if expected_pages else None,
        "nonempty_page_rate": round(nonempty_pages_num / expected_pages, 4) if expected_pages else None,
        "page_span_coverage": mean(item.get("page_span_coverage") for item in metrics),
        "metadata_required_present_rate": mean(item.get("metadata_required_present_rate") for item in metrics),
        "hangul_ratio": round(hangul_num / total_chars, 4) if total_chars else 0.0,
        "mojibake_count": sum(int(item.get("mojibake_count") or 0) for item in metrics),
        "total_chars": total_chars,
        "total_tables": sum(int(item.get("total_tables") or 0) for item in metrics),
        "table_nonempty_cell_rate": round(nonempty_table_cells / table_cells, 4) if table_cells else None,
        "runtime_s": round(runtime_s, 4),
        "runtime_s_per_expected_page": round(runtime_s / expected_pages, 4) if expected_pages else None,
        "duplicate_alias_ok": all(check["ok"] for check in duplicate_checks) if duplicate_checks else None,
        "duplicate_alias_checks": duplicate_checks,
        "failure_counts": dict(sorted(failure_counts.items())),
    }


def load_artifacts(run_dir: Path) -> list[dict[str, Any]]:
    artifacts = []
    for artifact_path in sorted((run_dir / "candidates").glob("*/*.json")):
        artifact = read_json(artifact_path)
        if not isinstance(artifact, dict):
            raise CandidateEvalError(f"Artifact must be a JSON object: {artifact_path}")
        artifact["artifact_path"] = str(artifact_path)
        artifact["metrics"] = compute_artifact_metrics(artifact)
        artifacts.append(artifact)
    return artifacts


def build_run_summary(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / RUN_MANIFEST
    run_manifest = read_json(manifest_path) if manifest_path.exists() else {}
    artifacts = load_artifacts(run_dir)
    by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for artifact in artifacts:
        by_candidate[str(artifact.get("candidate") or "unknown")].append(artifact)
    candidate_summaries = {
        candidate: summarize_candidate_docs(candidate, docs) for candidate, docs in sorted(by_candidate.items())
    }
    documents = []
    for artifact in artifacts:
        metrics = artifact["metrics"]
        documents.append(
            {
                "candidate": artifact.get("candidate"),
                "csv_row": artifact.get("csv_row"),
                "subset_rank": artifact.get("subset_rank"),
                "subset_reason": artifact.get("subset_reason"),
                "doc_id": artifact.get("doc_id"),
                "source_sha256": artifact.get("source_sha256"),
                "source_file": artifact.get("source_file"),
                "agency": (artifact.get("metadata") or {}).get("발주 기관"),
                "status": artifact.get("status"),
                "failure": artifact.get("failure"),
                "metrics": metrics,
                "artifact_path": artifact.get("artifact_path"),
            }
        )
    return {
        "mode": "parser_candidate_eval",
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "run": run_manifest,
        "summary": {
            "candidates": sorted(candidate_summaries),
            "candidate_summaries": candidate_summaries,
            "documents": len(documents),
        },
        "documents": sorted(documents, key=lambda item: (str(item["candidate"]), int(item["csv_row"] or 0))),
    }


def write_markdown_summary(path: Path, summary: dict[str, Any]) -> None:
    lines = ["# Parser Candidate Eval Summary", ""]
    run = summary.get("run") or {}
    lines.append(f"- Run ID: `{run.get('run_id', '')}`")
    lines.append(f"- Generated: `{summary.get('generated_at_utc')}`")
    lines.append("")
    lines.append("| candidate | docs | ok | skipped | failed | pages_seen_rate | page_span_coverage | total_tables | duplicate_alias_ok | runtime_s |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|---:|")
    for candidate, item in (summary.get("summary", {}).get("candidate_summaries") or {}).items():
        lines.append(
            "| {candidate} | {documents} | {ok} | {skipped} | {failed} | {pages_seen_rate} | {page_span_coverage} | {total_tables} | {duplicate_alias_ok} | {runtime_s} |".format(
                candidate=candidate,
                documents=item.get("documents"),
                ok=item.get("ok"),
                skipped=item.get("skipped"),
                failed=item.get("failed"),
                pages_seen_rate=item.get("pages_seen_rate"),
                page_span_coverage=item.get("page_span_coverage"),
                total_tables=item.get("total_tables"),
                duplicate_alias_ok=item.get("duplicate_alias_ok"),
                runtime_s=item.get("runtime_s"),
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run parser candidate extraction on a path-level PDF subset.")
    parser.add_argument("--manifest", required=True, help="Path-level converted PDF manifest JSON.")
    parser.add_argument("--subset", required=True, help="Subset JSON with csv_row entries.")
    parser.add_argument(
        "--candidates",
        default=",".join(SUPPORTED_CANDIDATES),
        help=f"Comma-separated candidates. Supported: {', '.join(SUPPORTED_CANDIDATES)}",
    )
    parser.add_argument("--run-id", default=None, help="Stable run id. Defaults to UTC timestamp.")
    parser.add_argument("--run-dir", default=None, help="Directory for raw/private candidate artifacts.")
    parser.add_argument("--limit-docs", type=int, default=None, help="Debug/test limit after subset ordering.")
    parser.add_argument(
        "--pdfplumber-max-pages",
        type=int,
        default=None,
        help="Optional page cap for pdfplumber sidecar. Omit/0 means all pages.",
    )
    parser.add_argument(
        "--pymupdf4llm-use-ocr",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Enable/disable PyMuPDF4LLM OCR for the eval control. "
            f"Default resolves from {PYMUPDF4LLM_USE_OCR_ENV}, else off."
        ),
    )
    parser.add_argument(
        "--pymupdf4llm-ocr-language",
        default=None,
        help=(
            "OCR language passed to PyMuPDF4LLM when OCR is enabled. "
            f"Default resolves from {PYMUPDF4LLM_OCR_LANGUAGE_ENV}, else "
            f"{PYMUPDF4LLM_EVAL_DEFAULT_OCR_LANGUAGE!r}."
        ),
    )
    parser.add_argument(
        "--pymupdf4llm-timeout-s",
        type=float,
        default=PYMUPDF4LLM_EVAL_DEFAULT_TIMEOUT_S,
        help=(
            "Per-document PyMuPDF4LLM timeout. Use 0 or a negative value to disable. "
            f"Default: {PYMUPDF4LLM_EVAL_DEFAULT_TIMEOUT_S:g}s."
        ),
    )
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        manifest_path = Path(args.manifest)
        subset_path = Path(args.subset)
        run_id = args.run_id or utc_now()
        run_dir = Path(args.run_dir) if args.run_dir else run_dir_default(manifest_path, run_id)
        candidates = parse_candidates(args.candidates)
        manifest = load_manifest_rows(manifest_path)
        subset = load_subset_rows(subset_path)
        rows = selected_rows(manifest, subset)
        if args.limit_docs is not None:
            if args.limit_docs < 1:
                raise CandidateEvalError("--limit-docs must be positive when provided")
            rows = rows[: args.limit_docs]
        pdfplumber_max_pages = args.pdfplumber_max_pages if args.pdfplumber_max_pages and args.pdfplumber_max_pages > 0 else None
        pymupdf4llm_use_ocr, pymupdf4llm_ocr_language = resolve_pymupdf4llm_ocr_options(
            use_ocr=args.pymupdf4llm_use_ocr,
            ocr_language=args.pymupdf4llm_ocr_language,
        )
        pymupdf4llm_timeout_s = (
            float(args.pymupdf4llm_timeout_s)
            if args.pymupdf4llm_timeout_s and args.pymupdf4llm_timeout_s > 0
            else None
        )
        run_manifest = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "generated_at_utc": utc_now(),
            "manifest": str(manifest_path),
            "subset": str(subset_path),
            "run_dir": str(run_dir),
            "candidates": candidates,
            "documents": [
                {
                    "csv_row": int(row["csv_row"]),
                    "subset_rank": int(row.get("subset_rank") or 0),
                    "subset_reason": row.get("subset_reason"),
                    "doc_id": make_doc_id(row),
                    "source_sha256": row.get("source_sha256"),
                    "source_file": row.get("source_file"),
                    "path_pdf": row.get("path_pdf"),
                    "expected_page_count": int(row.get("page_count") or 0),
                    "agency": normalize_metadata(row).get("발주 기관"),
                }
                for row in rows
            ],
            "options": {
                "pdfplumber_max_pages": pdfplumber_max_pages,
                "pymupdf4llm_use_ocr": pymupdf4llm_use_ocr,
                "pymupdf4llm_ocr_language": pymupdf4llm_ocr_language,
                "pymupdf4llm_timeout_s": pymupdf4llm_timeout_s,
            },
        }
        write_json(run_dir / RUN_MANIFEST, run_manifest)
        matrix = []
        for candidate in candidates:
            for row in rows:
                artifact = run_candidate(
                    candidate,
                    row,
                    pdfplumber_max_pages=pdfplumber_max_pages,
                    pymupdf4llm_use_ocr=pymupdf4llm_use_ocr,
                    pymupdf4llm_ocr_language=pymupdf4llm_ocr_language,
                    pymupdf4llm_timeout_s=pymupdf4llm_timeout_s,
                )
                artifact["metrics"] = compute_artifact_metrics(artifact)
                artifact_path = candidate_artifact_path(run_dir, candidate, int(row["csv_row"]))
                write_json(artifact_path, artifact)
                matrix.append(
                    {
                        "candidate": candidate,
                        "csv_row": int(row["csv_row"]),
                        "status": artifact.get("status"),
                        "failure": artifact.get("failure"),
                        "artifact_path": str(artifact_path),
                    }
                )
        write_json(run_dir / "candidate_matrix.json", matrix)
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "candidates": candidates,
                    "documents": len(rows),
                    "artifacts": len(matrix),
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
