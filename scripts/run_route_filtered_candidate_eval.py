#!/usr/bin/env python3
"""Run parser candidates only on pages selected by the page-routing audit.

This is an additive evaluation harness. It does not change canonical ingestion.
Raw OCR text is written only under the local/private run directory. Aggregate
reports intentionally keep counts, runtimes, confidence, and provenance but not
recognized page text.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_parser_candidate_eval import (  # noqa: E402
    CandidateEvalError,
    package_version,
    utc_now,
    write_json,
)

SCHEMA_VERSION = 1
OCR_CANDIDATES = ("paddleocr_classic", "tesseract_baseline")
LOCAL_STRUCTURE_CANDIDATES = ("pp_structurev3_local", "paddleocr_vl_local")
HOSTED_API_CANDIDATES = ("paddleocr_official_api",)
VLM_CANDIDATES = (*LOCAL_STRUCTURE_CANDIDATES, *HOSTED_API_CANDIDATES)
SUPPORTED_CANDIDATES = (*OCR_CANDIDATES, *VLM_CANDIDATES)
DEFAULT_LABELS = ("ocr_needed",)
DEFAULT_RENDER_DPI = 144
DEFAULT_TESSERACT_LANG = "kor+eng"
DEFAULT_PADDLEOCR_API_MODEL = "PaddleOCR-VL-1.6"
DEFAULT_PADDLEOCR_VL_PIPELINE_VERSION = "v1.6"
PADDLEOCR_API_MODEL_CHOICES = ("PP-StructureV3", "PaddleOCR-VL", "PaddleOCR-VL-1.5", "PaddleOCR-VL-1.6")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def round4(value: float) -> float:
    return round(float(value), 4)


def parse_csv_values(raw: str | None, *, default: tuple[str, ...] = ()) -> list[str]:
    if raw is None:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_candidates(raw: str) -> list[str]:
    candidates = parse_csv_values(raw)
    if not candidates:
        raise CandidateEvalError("--candidates must include at least one candidate")
    unknown = [candidate for candidate in candidates if candidate not in SUPPORTED_CANDIDATES]
    if unknown:
        raise CandidateEvalError(
            f"Unsupported candidate(s): {', '.join(unknown)}. "
            f"Supported: {', '.join(SUPPORTED_CANDIDATES)}"
        )
    return candidates


def model_inventory() -> list[str]:
    model_dir = Path.home() / ".paddlex" / "official_models"
    if not model_dir.is_dir():
        return []
    interesting = ("ocr", "textline", "layout", "vl", "structure")
    return sorted(
        path.name
        for path in model_dir.iterdir()
        if path.is_dir() and any(marker in path.name.lower() for marker in interesting)
    )


def tesseract_version() -> str | None:
    try:
        proc = subprocess.run(
            ["tesseract", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:  # noqa: BLE001 - optional local binary
        return None
    if proc.returncode != 0:
        return None
    first_line = (proc.stdout or proc.stderr or "").splitlines()[0:1]
    return first_line[0].strip() if first_line else None


def tesseract_languages() -> list[str]:
    try:
        proc = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:  # noqa: BLE001 - optional local binary
        return []
    if proc.returncode != 0:
        return []
    return sorted(line.strip() for line in proc.stdout.splitlines() if line.strip() and not line.startswith("List of"))


def paddleocr_access_token_present() -> bool:
    return bool(os.environ.get("PADDLEOCR_ACCESS_TOKEN"))


def paddleocr_base_url_present() -> bool:
    return bool(os.environ.get("PADDLEOCR_BASE_URL"))


def local_model_cache_sufficient(candidate: str, models: list[str]) -> bool:
    """Best-effort cache gate to avoid accidental heavy model downloads.

    PaddleOCR pipelines can lazily download large model families during
    initialization. For this route harness, local VLM/structure inference only
    proceeds by default when a relevant local cache is already visible, unless
    the caller explicitly passes --allow-model-download.
    """

    lowered = [model.lower() for model in models]
    if candidate == "pp_structurev3_local":
        markers = ("layout", "table", "formula", "chart", "structure")
    elif candidate == "paddleocr_vl_local":
        markers = ("paddleocr-vl", "ocr-vl", "vl", "visual")
    else:
        return False
    return any(any(marker in model for marker in markers) for model in lowered)


def safe_jsonable(value: Any, *, max_depth: int = 4) -> Any:
    """Convert Paddle result objects into bounded JSON-safe diagnostics."""

    if max_depth <= 0:
        return repr(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): safe_jsonable(item, max_depth=max_depth - 1) for key, item in list(value.items())[:80]}
    if isinstance(value, (list, tuple)):
        return [safe_jsonable(item, max_depth=max_depth - 1) for item in list(value)[:80]]
    if hasattr(value, "tolist"):
        try:
            return safe_jsonable(value.tolist(), max_depth=max_depth - 1)
        except Exception:  # noqa: BLE001 - diagnostic conversion only
            return repr(value)
    if hasattr(value, "to_dict"):
        try:
            return safe_jsonable(value.to_dict(), max_depth=max_depth - 1)
        except Exception:  # noqa: BLE001 - diagnostic conversion only
            return repr(value)
    if hasattr(value, "json"):
        try:
            payload = value.json
            if callable(payload):
                payload = payload()
            return safe_jsonable(payload, max_depth=max_depth - 1)
        except Exception:  # noqa: BLE001 - diagnostic conversion only
            return repr(value)
    return repr(value)


def bounded_preview(value: Any, *, limit: int = 4000) -> str:
    raw = json.dumps(safe_jsonable(value), ensure_ascii=False, default=str)
    return raw if len(raw) <= limit else raw[:limit] + "...<truncated>"


def collect_label_counts(value: Any) -> Counter:
    counts: Counter = Counter()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized_key = str(key).lower()
                if normalized_key in {"label", "type", "element_type", "block_label"} and isinstance(nested, str):
                    counts.update([nested])
                visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    return counts


def collect_textish_chars(value: Any) -> int:
    total = 0

    def visit(item: Any) -> None:
        nonlocal total
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized_key = str(key).lower()
                if isinstance(nested, str) and (
                    "markdown" in normalized_key
                    or normalized_key in {"text", "content", "block_content", "rec_text", "html"}
                ):
                    total += len(nested.strip())
                else:
                    visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    return total


def load_page_audit(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = read_json(path)
    if not isinstance(data, dict):
        raise CandidateEvalError(f"Page audit must be a JSON object: {path}")
    run = data.get("run") if isinstance(data.get("run"), dict) else {}
    documents = data.get("documents")
    if not isinstance(documents, list):
        raise CandidateEvalError(f"Page audit missing documents list: {path}")
    return run, [doc for doc in documents if isinstance(doc, dict)]


def page_matches(page: dict[str, Any], *, labels: list[str], primary_routes: list[str]) -> bool:
    page_labels = {str(label) for label in page.get("labels") or []}
    primary_route = str(page.get("primary_route") or "")
    return bool((labels and page_labels.intersection(labels)) or (primary_routes and primary_route in primary_routes))


def selected_documents(
    documents: list[dict[str, Any]],
    *,
    labels: list[str],
    primary_routes: list[str],
    csv_rows: set[int] | None = None,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    remaining = max_pages if max_pages and max_pages > 0 else None
    for doc in sorted(documents, key=lambda item: int(item.get("subset_rank") or item.get("csv_row") or 0)):
        csv_row = int(doc.get("csv_row") or 0)
        if csv_rows is not None and csv_row not in csv_rows:
            continue
        pages = []
        for page in doc.get("pages") or []:
            if not isinstance(page, dict) or not page_matches(page, labels=labels, primary_routes=primary_routes):
                continue
            if remaining is not None and remaining <= 0:
                break
            pages.append(page)
            if remaining is not None:
                remaining -= 1
        if pages:
            selected_doc = dict(doc)
            selected_doc["selected_pages"] = pages
            selected.append(selected_doc)
        if remaining is not None and remaining <= 0:
            break
    return selected


def render_page_image(pdf_path: Path, page_number: int, *, dpi: int) -> Any:
    import pymupdf  # type: ignore  # noqa: PLC0415
    from PIL import Image  # type: ignore  # noqa: PLC0415

    scale = dpi / 72.0
    doc = pymupdf.open(str(pdf_path))
    try:
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        mode = "RGB" if pix.n >= 3 else "L"
        return Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


def audit_page_summary(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "page": page.get("page"),
        "text_chars": page.get("text_chars"),
        "image_count": page.get("image_count"),
        "image_area_ratio": page.get("image_area_ratio"),
        "table_count": page.get("table_count"),
        "labels": page.get("labels"),
        "primary_route": page.get("primary_route"),
        "reasons": page.get("reasons"),
        "warnings": page.get("warnings"),
    }


def page_text_chars(blocks: list[dict[str, Any]]) -> int:
    return sum(len(str(block.get("text") or "").strip()) for block in blocks)


def page_average_confidence(blocks: list[dict[str, Any]]) -> float | None:
    values = []
    for block in blocks:
        confidence = block.get("confidence")
        if isinstance(confidence, (int, float)):
            values.append(float(confidence))
    return round4(sum(values) / len(values)) if values else None


def run_paddleocr_page_direct(pdf_path: Path, page_number: int, *, dpi: int) -> dict[str, Any]:
    from visual_ingestion import paddleocr_provider  # noqa: PLC0415

    image = render_page_image(pdf_path, page_number, dpi=dpi)
    blocks = paddleocr_provider(image)
    return {
        "blocks": blocks,
        "text_chars": page_text_chars(blocks),
        "block_count": len(blocks),
        "avg_confidence": page_average_confidence(blocks),
    }


def run_paddleocr_page_subprocess(
    pdf_path: Path,
    page_number: int,
    *,
    dpi: int,
    timeout_s: float,
    python_executable: str,
) -> dict[str, Any]:
    worker = r"""
import json
from pathlib import Path
import sys

from scripts.run_route_filtered_candidate_eval import run_paddleocr_page_direct

pdf_path = Path(sys.argv[1])
page_number = int(sys.argv[2])
dpi = int(sys.argv[3])
output_path = Path(sys.argv[4])
result = run_paddleocr_page_direct(pdf_path, page_number, dpi=dpi)
output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
"""
    with tempfile.NamedTemporaryFile(prefix="bidmate_paddleocr_page_", suffix=".json", delete=False) as handle:
        output_path = Path(handle.name)
    try:
        proc = subprocess.run(
            [python_executable, "-c", worker, str(pdf_path), str(page_number), str(dpi), str(output_path)],
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
        return read_json(output_path)
    finally:
        output_path.unlink(missing_ok=True)


def run_paddleocr_page(
    pdf_path: Path,
    page_number: int,
    *,
    dpi: int,
    timeout_s: float | None,
    python_executable: str = sys.executable,
) -> dict[str, Any]:
    if timeout_s and timeout_s > 0:
        return run_paddleocr_page_subprocess(
            pdf_path,
            page_number,
            dpi=dpi,
            timeout_s=timeout_s,
            python_executable=python_executable,
        )
    return run_paddleocr_page_direct(pdf_path, page_number, dpi=dpi)


def run_tesseract_page_direct(
    pdf_path: Path,
    page_number: int,
    *,
    dpi: int,
    lang: str,
) -> dict[str, Any]:
    import pytesseract  # type: ignore  # noqa: PLC0415
    from visual_ingestion import union_bboxes  # noqa: PLC0415

    image = render_page_image(pdf_path, page_number, dpi=dpi)
    kwargs = {"output_type": pytesseract.Output.DICT}
    if lang:
        kwargs["lang"] = lang
    data = pytesseract.image_to_data(image, **kwargs)

    grouped: dict[tuple[int, int, int], dict[str, Any]] = {}
    for idx, raw_text in enumerate(data.get("text", [])):
        text = str(raw_text or "").strip()
        if not text:
            continue
        try:
            confidence = float(data.get("conf", [0])[idx])
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0:
            confidence = 0.0
        key = (
            int(data.get("block_num", [0])[idx]),
            int(data.get("par_num", [0])[idx]),
            int(data.get("line_num", [0])[idx]),
        )
        left = float(data.get("left", [0])[idx])
        top = float(data.get("top", [0])[idx])
        width = float(data.get("width", [0])[idx])
        height = float(data.get("height", [0])[idx])
        entry = grouped.setdefault(key, {"parts": [], "confidences": [], "boxes": []})
        entry["parts"].append(text)
        entry["confidences"].append(confidence / 100.0)
        entry["boxes"].append([left, top, left + width, top + height])

    blocks = []
    for entry in grouped.values():
        text = " ".join(entry["parts"]).strip()
        if not text:
            continue
        confidences = entry["confidences"] or [0.0]
        blocks.append(
            {
                "text": text,
                "bbox": union_bboxes(entry["boxes"]),
                "confidence": round(sum(confidences) / len(confidences), 3),
            }
        )
    return {
        "blocks": blocks,
        "text_chars": page_text_chars(blocks),
        "block_count": len(blocks),
        "avg_confidence": page_average_confidence(blocks),
    }


def run_tesseract_page_subprocess(
    pdf_path: Path,
    page_number: int,
    *,
    dpi: int,
    lang: str,
    timeout_s: float,
) -> dict[str, Any]:
    worker = r"""
import json
from pathlib import Path
import sys

from scripts.run_route_filtered_candidate_eval import run_tesseract_page_direct

pdf_path = Path(sys.argv[1])
page_number = int(sys.argv[2])
dpi = int(sys.argv[3])
lang = sys.argv[4]
output_path = Path(sys.argv[5])
result = run_tesseract_page_direct(pdf_path, page_number, dpi=dpi, lang=lang)
output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
"""
    with tempfile.NamedTemporaryFile(prefix="bidmate_tesseract_page_", suffix=".json", delete=False) as handle:
        output_path = Path(handle.name)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", worker, str(pdf_path), str(page_number), str(dpi), lang, str(output_path)],
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
        return read_json(output_path)
    finally:
        output_path.unlink(missing_ok=True)


def run_tesseract_page(
    pdf_path: Path,
    page_number: int,
    *,
    dpi: int,
    lang: str,
    timeout_s: float | None,
) -> dict[str, Any]:
    if timeout_s and timeout_s > 0:
        return run_tesseract_page_subprocess(pdf_path, page_number, dpi=dpi, lang=lang, timeout_s=timeout_s)
    return run_tesseract_page_direct(pdf_path, page_number, dpi=dpi, lang=lang)


def save_page_image(pdf_path: Path, page_number: int, *, dpi: int, output_path: Path) -> None:
    image = render_page_image(pdf_path, page_number, dpi=dpi)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def normalize_structured_result(raw_result: Any) -> dict[str, Any]:
    jsonable = safe_jsonable(raw_result)
    if isinstance(jsonable, list):
        result_count = len(jsonable)
    elif jsonable is None:
        result_count = 0
    else:
        result_count = 1
    label_counts = collect_label_counts(jsonable)
    text_chars = collect_textish_chars(jsonable)
    return {
        "blocks": [],
        "text_chars": int(text_chars),
        "block_count": int(result_count),
        "avg_confidence": None,
        "structured": {
            "result_count": result_count,
            "label_counts": dict(sorted(label_counts.items())),
            "textish_chars": int(text_chars),
            "json_preview": bounded_preview(jsonable),
        },
    }


def _prediction_result(pipeline: Any, image_path: Path) -> Any:
    if hasattr(pipeline, "predict"):
        result = pipeline.predict(str(image_path))
        if not isinstance(result, (dict, list, tuple, str)):
            try:
                return list(result)
            except TypeError:
                return result
        return result
    if callable(pipeline):
        return pipeline(str(image_path))
    raise CandidateEvalError("Paddle pipeline object does not expose predict()")


def run_local_structure_page_direct(
    candidate: str,
    pdf_path: Path,
    page_number: int,
    *,
    dpi: int,
    device: str | None,
    paddleocr_vl_pipeline_version: str,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(prefix="bidmate_local_vlm_page_", suffix=".png", delete=False) as handle:
        image_path = Path(handle.name)
    try:
        save_page_image(pdf_path, page_number, dpi=dpi, output_path=image_path)
        if candidate == "pp_structurev3_local":
            from paddleocr import PPStructureV3  # type: ignore  # noqa: PLC0415

            kwargs: dict[str, Any] = {
                "use_table_recognition": True,
                "use_formula_recognition": True,
                "use_chart_recognition": True,
                "format_block_content": True,
            }
            if device:
                kwargs["device"] = device
            pipeline = PPStructureV3(**kwargs)
        elif candidate == "paddleocr_vl_local":
            from paddleocr import PaddleOCRVL  # type: ignore  # noqa: PLC0415

            kwargs = {
                "pipeline_version": paddleocr_vl_pipeline_version,
                "use_layout_detection": True,
                "use_chart_recognition": True,
                "format_block_content": True,
            }
            if device:
                kwargs["device"] = device
            pipeline = PaddleOCRVL(**kwargs)
        else:
            raise CandidateEvalError(f"Unsupported local structure candidate: {candidate}")
        return normalize_structured_result(_prediction_result(pipeline, image_path))
    finally:
        image_path.unlink(missing_ok=True)


def run_local_structure_page_subprocess(
    candidate: str,
    pdf_path: Path,
    page_number: int,
    *,
    dpi: int,
    device: str | None,
    paddleocr_vl_pipeline_version: str,
    timeout_s: float,
    python_executable: str,
) -> dict[str, Any]:
    worker = r"""
import json
from pathlib import Path
import sys

from scripts.run_route_filtered_candidate_eval import run_local_structure_page_direct

candidate = sys.argv[1]
pdf_path = Path(sys.argv[2])
page_number = int(sys.argv[3])
dpi = int(sys.argv[4])
device = sys.argv[5] or None
paddleocr_vl_pipeline_version = sys.argv[6]
output_path = Path(sys.argv[7])
result = run_local_structure_page_direct(
    candidate,
    pdf_path,
    page_number,
    dpi=dpi,
    device=device,
    paddleocr_vl_pipeline_version=paddleocr_vl_pipeline_version,
)
output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
"""
    with tempfile.NamedTemporaryFile(prefix="bidmate_local_vlm_page_", suffix=".json", delete=False) as handle:
        output_path = Path(handle.name)
    try:
        proc = subprocess.run(
            [
                python_executable,
                "-c",
                worker,
                candidate,
                str(pdf_path),
                str(page_number),
                str(dpi),
                device or "",
                paddleocr_vl_pipeline_version,
                str(output_path),
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
        return read_json(output_path)
    finally:
        output_path.unlink(missing_ok=True)


def run_paddleocr_official_api_page_direct(
    pdf_path: Path,
    page_number: int,
    *,
    dpi: int,
    model: str,
    request_timeout_s: float,
    poll_timeout_s: float,
    base_url: str | None,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(prefix="bidmate_paddleocr_api_page_", suffix=".png", delete=False) as handle:
        image_path = Path(handle.name)
    client = None
    try:
        save_page_image(pdf_path, page_number, dpi=dpi, output_path=image_path)
        import paddleocr  # type: ignore  # noqa: PLC0415

        client_cls = getattr(paddleocr, "PaddleOCRClient", None)
        if client_cls is None:
            raise CandidateEvalError("PaddleOCRClient is not available in this paddleocr installation")
        client_kwargs: dict[str, Any] = {
            "request_timeout": request_timeout_s,
            "poll_timeout": poll_timeout_s,
        }
        if base_url:
            client_kwargs["base_url"] = base_url
        client = client_cls(**client_kwargs)
        options = None
        if model == "PP-StructureV3" and hasattr(paddleocr, "PPStructureV3Options"):
            options = paddleocr.PPStructureV3Options(
                use_table_recognition=True,
                use_formula_recognition=True,
                use_chart_recognition=True,
                prettify_markdown=True,
            )
        elif model.startswith("PaddleOCR-VL") and hasattr(paddleocr, "PaddleOCRVLOptions"):
            options = paddleocr.PaddleOCRVLOptions(
                use_layout_detection=True,
                use_chart_recognition=True,
                prettify_markdown=True,
            )
        kwargs: dict[str, Any] = {"file_path": str(image_path), "model": model}
        if options is not None:
            kwargs["options"] = options
        return normalize_structured_result(client.parse_document(**kwargs))
    finally:
        if client is not None and hasattr(client, "close"):
            client.close()
        image_path.unlink(missing_ok=True)


def run_paddleocr_official_api_page_subprocess(
    pdf_path: Path,
    page_number: int,
    *,
    dpi: int,
    model: str,
    request_timeout_s: float,
    poll_timeout_s: float,
    base_url: str | None,
    timeout_s: float,
    python_executable: str,
) -> dict[str, Any]:
    worker = r"""
import json
from pathlib import Path
import sys

from scripts.run_route_filtered_candidate_eval import run_paddleocr_official_api_page_direct

pdf_path = Path(sys.argv[1])
page_number = int(sys.argv[2])
dpi = int(sys.argv[3])
model = sys.argv[4]
request_timeout_s = float(sys.argv[5])
poll_timeout_s = float(sys.argv[6])
base_url = sys.argv[7] or None
output_path = Path(sys.argv[8])
result = run_paddleocr_official_api_page_direct(
    pdf_path,
    page_number,
    dpi=dpi,
    model=model,
    request_timeout_s=request_timeout_s,
    poll_timeout_s=poll_timeout_s,
    base_url=base_url,
)
output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
"""
    with tempfile.NamedTemporaryFile(prefix="bidmate_paddleocr_api_page_", suffix=".json", delete=False) as handle:
        output_path = Path(handle.name)
    try:
        proc = subprocess.run(
            [
                python_executable,
                "-c",
                worker,
                str(pdf_path),
                str(page_number),
                str(dpi),
                model,
                str(request_timeout_s),
                str(poll_timeout_s),
                base_url or "",
                str(output_path),
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
        return read_json(output_path)
    finally:
        output_path.unlink(missing_ok=True)


def failure_page(page: dict[str, Any], *, status: str, code: str, message: str, runtime_s: float = 0.0) -> dict[str, Any]:
    return {
        "page": int(page.get("page") or 0),
        "audit": audit_page_summary(page),
        "status": status,
        "blocks": [],
        "text_chars": 0,
        "block_count": 0,
        "avg_confidence": None,
        "runtime_s": round4(runtime_s),
        "failure": {"code": code, "message": message},
    }


def paddleocr_versions() -> dict[str, Any]:
    return {
        "paddleocr": package_version("paddleocr"),
        "paddlex": package_version("paddlex"),
        "paddlepaddle": package_version("paddlepaddle"),
        "models": model_inventory(),
    }


def tesseract_versions() -> dict[str, Any]:
    languages = tesseract_languages()
    return {
        "pytesseract": package_version("pytesseract"),
        "tesseract": tesseract_version(),
        "language_count": len(languages),
        "languages_available": {
            "eng": "eng" in languages,
            "kor": "kor" in languages,
        },
    }


def paddleocr_class_available(class_name: str) -> bool:
    try:
        import paddleocr  # type: ignore  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - optional local package
        return False
    return hasattr(paddleocr, class_name)


def vlm_candidate_versions(candidate: str) -> dict[str, Any]:
    if candidate == "pp_structurev3_local":
        return {
            "paddleocr": package_version("paddleocr"),
            "class": "PPStructureV3",
            "class_available": paddleocr_class_available("PPStructureV3"),
            "models": model_inventory(),
        }
    if candidate == "paddleocr_vl_local":
        return {
            "paddleocr": package_version("paddleocr"),
            "class": "PaddleOCRVL",
            "class_available": paddleocr_class_available("PaddleOCRVL"),
            "models": model_inventory(),
        }
    if candidate == "paddleocr_official_api":
        return {
            "paddleocr": package_version("paddleocr"),
            "class": "PaddleOCRClient",
            "class_available": paddleocr_class_available("PaddleOCRClient"),
            "model_targets": list(PADDLEOCR_API_MODEL_CHOICES),
            "access_token_present": paddleocr_access_token_present(),
            "base_url_present": paddleocr_base_url_present(),
        }
    raise CandidateEvalError(f"Unsupported candidate: {candidate}")


def candidate_versions(candidate: str) -> dict[str, Any]:
    if candidate == "paddleocr_classic":
        return paddleocr_versions()
    if candidate == "tesseract_baseline":
        return tesseract_versions()
    if candidate in VLM_CANDIDATES:
        return vlm_candidate_versions(candidate)
    raise CandidateEvalError(f"Unsupported candidate: {candidate}")


def candidate_versions_from_python(candidate: str, python_executable: str) -> dict[str, Any]:
    if str(Path(python_executable)) == str(Path(sys.executable)):
        return candidate_versions(candidate)
    probe = r"""
import importlib.metadata
import json
from pathlib import Path
import sys

candidate = sys.argv[1]

def package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None

def model_inventory():
    model_dir = Path.home() / ".paddlex" / "official_models"
    if not model_dir.is_dir():
        return []
    interesting = ("ocr", "textline", "layout", "vl", "structure")
    return sorted(
        path.name
        for path in model_dir.iterdir()
        if path.is_dir() and any(marker in path.name.lower() for marker in interesting)
    )

def class_available(name):
    try:
        import paddleocr
    except Exception:
        return False
    return hasattr(paddleocr, name)

payload = {"python": sys.executable}
if candidate == "paddleocr_classic":
    payload.update({
        "paddleocr": package_version("paddleocr"),
        "paddlex": package_version("paddlex"),
        "paddlepaddle": package_version("paddlepaddle"),
        "models": model_inventory(),
    })
elif candidate == "pp_structurev3_local":
    payload.update({
        "paddleocr": package_version("paddleocr"),
        "class": "PPStructureV3",
        "class_available": class_available("PPStructureV3"),
        "models": model_inventory(),
    })
elif candidate == "paddleocr_vl_local":
    payload.update({
        "paddleocr": package_version("paddleocr"),
        "class": "PaddleOCRVL",
        "class_available": class_available("PaddleOCRVL"),
        "models": model_inventory(),
    })
elif candidate == "paddleocr_official_api":
    payload.update({
        "paddleocr": package_version("paddleocr"),
        "class": "PaddleOCRClient",
        "class_available": class_available("PaddleOCRClient"),
        "model_targets": ["PP-StructureV3", "PaddleOCR-VL", "PaddleOCR-VL-1.5", "PaddleOCR-VL-1.6"],
    })
else:
    payload["probe_error"] = f"unsupported candidate: {candidate}"
print(json.dumps(payload, ensure_ascii=False))
"""
    try:
        proc = subprocess.run(
            [python_executable, "-c", probe, candidate],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic fallback
        data = candidate_versions(candidate)
        data["python"] = python_executable
        data["probe_error"] = f"{type(exc).__name__}: {exc}"
        return data
    if proc.returncode != 0:
        data = candidate_versions(candidate)
        data["python"] = python_executable
        stderr = (proc.stderr or "").strip().splitlines()
        data["probe_error"] = stderr[-1] if stderr else f"subprocess_exit_{proc.returncode}"
        return data
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = candidate_versions(candidate)
        data["python"] = python_executable
        data["probe_error"] = "invalid probe JSON"
        return data


def candidate_versions_for_runtime(candidate: str, args: argparse.Namespace) -> dict[str, Any]:
    python_executable = getattr(args, "paddleocr_python", sys.executable)
    if candidate == "tesseract_baseline":
        return candidate_versions(candidate)
    if candidate == "paddleocr_classic" or candidate in VLM_CANDIDATES:
        return candidate_versions_from_python(candidate, python_executable)
    return candidate_versions(candidate)


def dependency_missing_message(candidate: str, versions: dict[str, Any]) -> str | None:
    if candidate == "paddleocr_classic" and versions.get("paddleocr") is None:
        return "paddleocr is not installed"
    if candidate == "tesseract_baseline":
        if versions.get("pytesseract") is None:
            return "pytesseract is not installed"
        if versions.get("tesseract") is None:
            return "tesseract binary is not available"
    return None


def run_candidate_page(
    candidate: str,
    pdf_path: Path,
    page_number: int,
    *,
    dpi: int,
    timeout_s: float | None,
    tesseract_lang: str,
    local_vlm_device: str | None = None,
    paddleocr_vl_pipeline_version: str = DEFAULT_PADDLEOCR_VL_PIPELINE_VERSION,
    paddleocr_api_model: str = DEFAULT_PADDLEOCR_API_MODEL,
    paddleocr_api_request_timeout_s: float = 300.0,
    paddleocr_api_poll_timeout_s: float = 600.0,
    paddleocr_api_base_url: str | None = None,
    paddleocr_python: str = sys.executable,
) -> dict[str, Any]:
    if candidate == "paddleocr_classic":
        return run_paddleocr_page(
            pdf_path,
            page_number,
            dpi=dpi,
            timeout_s=timeout_s,
            python_executable=paddleocr_python,
        )
    if candidate == "tesseract_baseline":
        return run_tesseract_page(
            pdf_path,
            page_number,
            dpi=dpi,
            lang=tesseract_lang,
            timeout_s=timeout_s,
        )
    if candidate in LOCAL_STRUCTURE_CANDIDATES:
        if timeout_s and timeout_s > 0:
            return run_local_structure_page_subprocess(
                candidate,
                pdf_path,
                page_number,
                dpi=dpi,
                device=local_vlm_device,
                paddleocr_vl_pipeline_version=paddleocr_vl_pipeline_version,
                timeout_s=timeout_s,
                python_executable=paddleocr_python,
            )
        return run_local_structure_page_direct(
            candidate,
            pdf_path,
            page_number,
            dpi=dpi,
            device=local_vlm_device,
            paddleocr_vl_pipeline_version=paddleocr_vl_pipeline_version,
        )
    if candidate in HOSTED_API_CANDIDATES:
        if timeout_s and timeout_s > 0:
            return run_paddleocr_official_api_page_subprocess(
                pdf_path,
                page_number,
                dpi=dpi,
                model=paddleocr_api_model,
                request_timeout_s=paddleocr_api_request_timeout_s,
                poll_timeout_s=paddleocr_api_poll_timeout_s,
                base_url=paddleocr_api_base_url,
                timeout_s=timeout_s,
                python_executable=paddleocr_python,
            )
        return run_paddleocr_official_api_page_direct(
            pdf_path,
            page_number,
            dpi=dpi,
            model=paddleocr_api_model,
            request_timeout_s=paddleocr_api_request_timeout_s,
            poll_timeout_s=paddleocr_api_poll_timeout_s,
            base_url=paddleocr_api_base_url,
        )
    raise CandidateEvalError(f"Unsupported candidate: {candidate}")


def run_ocr_document(candidate: str, doc: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    started_doc = time.perf_counter()
    versions = candidate_versions_for_runtime(candidate, args)
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "mode": "route_filtered_candidate_eval",
        "candidate": candidate,
        "candidate_version": versions.get("paddleocr") or versions.get("pytesseract"),
        "provider": "hosted_api" if candidate in HOSTED_API_CANDIDATES else "local",
        "status": "ok",
        "csv_row": int(doc.get("csv_row") or 0),
        "subset_rank": int(doc.get("subset_rank") or 0),
        "subset_reason": doc.get("subset_reason") or "selected",
        "doc_id": doc.get("doc_id"),
        "source_sha256": doc.get("source_sha256"),
        "source_file": doc.get("source_file"),
        "path_pdf": doc.get("path_pdf"),
        "expected_page_count": int(doc.get("expected_page_count") or 0),
        "selected_page_count": len(doc.get("selected_pages") or []),
        "selection": {
            "labels": args.labels,
            "primary_routes": args.primary_routes,
            "selection_source": args.page_audit,
        },
        "provenance": {
            "runtime_s": 0.0,
            "render_dpi": args.render_dpi,
            "page_timeout_s": args.page_timeout_s,
            "page_retries": args.page_retries,
            "tesseract_lang": args.tesseract_lang if candidate == "tesseract_baseline" else None,
            "local_vlm_device": getattr(args, "local_vlm_device", None) if candidate in LOCAL_STRUCTURE_CANDIDATES else None,
            "paddleocr_vl_pipeline_version": (
                getattr(args, "paddleocr_vl_pipeline_version", DEFAULT_PADDLEOCR_VL_PIPELINE_VERSION)
                if candidate == "paddleocr_vl_local"
                else None
            ),
            "allow_model_download": bool(getattr(args, "allow_model_download", False))
            if candidate in LOCAL_STRUCTURE_CANDIDATES
            else None,
            "paddleocr_api_model": getattr(args, "paddleocr_api_model", None)
            if candidate in HOSTED_API_CANDIDATES
            else None,
            "paddleocr_api_request_timeout_s": getattr(args, "paddleocr_api_request_timeout_s", None)
            if candidate in HOSTED_API_CANDIDATES
            else None,
            "paddleocr_api_poll_timeout_s": getattr(args, "paddleocr_api_poll_timeout_s", None)
            if candidate in HOSTED_API_CANDIDATES
            else None,
            "paddleocr_api_base_url_present": bool(getattr(args, "paddleocr_api_base_url", None))
            if candidate in HOSTED_API_CANDIDATES
            else None,
            "paddleocr_access_token_present": paddleocr_access_token_present()
            if candidate in HOSTED_API_CANDIDATES
            else None,
            "paddleocr_python": getattr(args, "paddleocr_python", sys.executable)
            if candidate == "paddleocr_classic" or candidate in VLM_CANDIDATES
            else None,
            "dry_run": bool(args.dry_run),
            "versions": versions,
            "cost_usd": None if candidate in HOSTED_API_CANDIDATES else 0.0,
        },
        "pages": [],
        "elements": [],
        "failure": None,
    }

    if args.dry_run:
        artifact["status"] = "skipped"
        artifact["failure"] = {"code": "dry_run", "message": "Candidate inference was not executed"}
        artifact["pages"] = [
            failure_page(page, status="skipped", code="dry_run", message="Candidate inference was not executed")
            for page in doc.get("selected_pages") or []
        ]
        artifact["provenance"]["runtime_s"] = round4(time.perf_counter() - started_doc)
        return artifact

    missing = dependency_missing_message(candidate, versions)
    if missing:
        artifact["status"] = "skipped"
        artifact["failure"] = {"code": "dependency_unavailable", "message": missing}
        artifact["pages"] = [
            failure_page(page, status="skipped", code="dependency_unavailable", message=missing)
            for page in doc.get("selected_pages") or []
        ]
        artifact["provenance"]["runtime_s"] = round4(time.perf_counter() - started_doc)
        return artifact

    pdf_path = Path(str(doc.get("path_pdf") or ""))
    if not pdf_path.is_absolute():
        pdf_path = REPO_ROOT / pdf_path
    page_statuses = Counter()
    for page in doc.get("selected_pages") or []:
        page_number = int(page.get("page") or 0)
        started_page = time.perf_counter()
        attempts: list[dict[str, Any]] = []
        page_output: dict[str, Any] | None = None
        last_failure: str | None = None
        try:
            if page_number < 1:
                raise CandidateEvalError(f"invalid page number: {page_number}")
            for attempt in range(1, int(args.page_retries or 0) + 2):
                started_attempt = time.perf_counter()
                try:
                    page_output = run_candidate_page(
                        candidate,
                        pdf_path,
                        page_number,
                        dpi=int(args.render_dpi),
                        timeout_s=args.page_timeout_s,
                        tesseract_lang=args.tesseract_lang,
                        local_vlm_device=getattr(args, "local_vlm_device", None),
                        paddleocr_vl_pipeline_version=getattr(
                            args,
                            "paddleocr_vl_pipeline_version",
                            DEFAULT_PADDLEOCR_VL_PIPELINE_VERSION,
                        ),
                        paddleocr_api_model=getattr(args, "paddleocr_api_model", DEFAULT_PADDLEOCR_API_MODEL),
                        paddleocr_api_request_timeout_s=getattr(args, "paddleocr_api_request_timeout_s", 300.0),
                        paddleocr_api_poll_timeout_s=getattr(args, "paddleocr_api_poll_timeout_s", 600.0),
                        paddleocr_api_base_url=getattr(args, "paddleocr_api_base_url", None),
                        paddleocr_python=getattr(args, "paddleocr_python", sys.executable),
                    )
                    attempts.append(
                        {
                            "attempt": attempt,
                            "status": "ok",
                            "runtime_s": round4(time.perf_counter() - started_attempt),
                            "failure": None,
                        }
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - retry page-level local OCR failures
                    last_failure = f"{type(exc).__name__}: {exc}"
                    attempts.append(
                        {
                            "attempt": attempt,
                            "status": "failed",
                            "runtime_s": round4(time.perf_counter() - started_attempt),
                            "failure": last_failure,
                        }
                    )
            if page_output is None:
                raise CandidateEvalError(last_failure or "page inference failed")
            blocks = [block for block in page_output.get("blocks") or [] if isinstance(block, dict)]
            page_record = {
                "page": page_number,
                "audit": audit_page_summary(page),
                "status": "ok",
                "blocks": blocks,
                "text_chars": int(page_output.get("text_chars") or page_text_chars(blocks)),
                "block_count": int(page_output.get("block_count") or len(blocks)),
                "avg_confidence": page_output.get("avg_confidence"),
                "runtime_s": round4(time.perf_counter() - started_page),
                "attempts": attempts,
                "failure": None,
            }
            if isinstance(page_output.get("structured"), dict):
                page_record["structured"] = page_output["structured"]
            for block in blocks:
                text = str(block.get("text") or "").strip()
                if not text:
                    continue
                artifact["elements"].append(
                    {
                        "type": "ocr_text",
                        "page_span": [page_number, page_number],
                        "text": text,
                        "bbox": block.get("bbox"),
                        "confidence": block.get("confidence"),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            page_record = failure_page(
                page,
                status="failed",
                code="page_inference_failed",
                message=f"{type(exc).__name__}: {exc}",
                runtime_s=time.perf_counter() - started_page,
            )
            page_record["attempts"] = attempts
        page_statuses.update([page_record["status"]])
        artifact["pages"].append(page_record)

    if page_statuses["ok"]:
        artifact["status"] = "ok" if page_statuses["failed"] == 0 else "partial"
    elif page_statuses["failed"]:
        artifact["status"] = "failed"
        artifact["failure"] = {"code": "all_pages_failed", "message": "No selected page completed successfully"}
    else:
        artifact["status"] = "skipped"
        artifact["failure"] = {"code": "no_pages", "message": "No pages were selected"}
    artifact["provenance"]["runtime_s"] = round4(time.perf_counter() - started_doc)
    return artifact


def skip_candidate_document(
    candidate: str,
    doc: dict[str, Any],
    args: argparse.Namespace,
    *,
    code: str,
    message: str,
) -> dict[str, Any]:
    versions = candidate_versions_for_runtime(candidate, args)
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "mode": "route_filtered_candidate_eval",
        "candidate": candidate,
        "candidate_version": versions.get("paddleocr"),
        "provider": "hosted_api" if candidate in HOSTED_API_CANDIDATES else "local",
        "status": "skipped",
        "csv_row": int(doc.get("csv_row") or 0),
        "subset_rank": int(doc.get("subset_rank") or 0),
        "subset_reason": doc.get("subset_reason") or "selected",
        "doc_id": doc.get("doc_id"),
        "source_sha256": doc.get("source_sha256"),
        "source_file": doc.get("source_file"),
        "path_pdf": doc.get("path_pdf"),
        "expected_page_count": int(doc.get("expected_page_count") or 0),
        "selected_page_count": len(doc.get("selected_pages") or []),
        "selection": {
            "labels": args.labels,
            "primary_routes": args.primary_routes,
            "selection_source": args.page_audit,
        },
        "provenance": {
            "runtime_s": 0.0,
            "render_dpi": args.render_dpi,
            "page_timeout_s": args.page_timeout_s,
            "page_retries": args.page_retries,
            "dry_run": bool(args.dry_run),
            "versions": versions,
            "local_vlm_device": getattr(args, "local_vlm_device", None) if candidate in LOCAL_STRUCTURE_CANDIDATES else None,
            "allow_model_download": bool(getattr(args, "allow_model_download", False))
            if candidate in LOCAL_STRUCTURE_CANDIDATES
            else None,
            "paddleocr_vl_pipeline_version": (
                getattr(args, "paddleocr_vl_pipeline_version", DEFAULT_PADDLEOCR_VL_PIPELINE_VERSION)
                if candidate == "paddleocr_vl_local"
                else None
            ),
            "paddleocr_api_model": getattr(args, "paddleocr_api_model", None)
            if candidate in HOSTED_API_CANDIDATES
            else None,
            "paddleocr_api_request_timeout_s": getattr(args, "paddleocr_api_request_timeout_s", None)
            if candidate in HOSTED_API_CANDIDATES
            else None,
            "paddleocr_api_poll_timeout_s": getattr(args, "paddleocr_api_poll_timeout_s", None)
            if candidate in HOSTED_API_CANDIDATES
            else None,
            "paddleocr_api_base_url_present": bool(getattr(args, "paddleocr_api_base_url", None))
            if candidate in HOSTED_API_CANDIDATES
            else None,
            "paddleocr_access_token_present": paddleocr_access_token_present()
            if candidate in HOSTED_API_CANDIDATES
            else None,
            "paddleocr_python": getattr(args, "paddleocr_python", sys.executable),
            "cost_usd": None if candidate in HOSTED_API_CANDIDATES else 0.0,
        },
        "pages": [
            failure_page(
                page,
                status="skipped",
                code=code,
                message=message,
            )
            for page in doc.get("selected_pages") or []
        ],
        "elements": [],
        "failure": {"code": code, "message": message},
    }
    return artifact


def run_vlm_document(candidate: str, doc: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    versions = candidate_versions_for_runtime(candidate, args)
    if candidate in LOCAL_STRUCTURE_CANDIDATES:
        if not getattr(args, "enable_local_vlm", False):
            return skip_candidate_document(
                candidate,
                doc,
                args,
                code="candidate_not_enabled",
                message="Local VLM/structure inference requires --enable-local-vlm.",
            )
        if not versions.get("class_available"):
            return skip_candidate_document(
                candidate,
                doc,
                args,
                code="dependency_unavailable",
                message=f"{versions.get('class')} is not available in this paddleocr installation.",
            )
        if not getattr(args, "allow_model_download", False) and not local_model_cache_sufficient(
            candidate,
            list(versions.get("models") or []),
        ):
            return skip_candidate_document(
                candidate,
                doc,
                args,
                code="model_cache_missing",
                message=(
                    "No relevant local PaddleOCR VLM/structure model cache was found; "
                    "rerun with --allow-model-download to permit heavy model downloads."
                ),
            )
        return run_ocr_document(candidate, doc, args)

    if candidate in HOSTED_API_CANDIDATES:
        if not getattr(args, "enable_hosted_api", False):
            return skip_candidate_document(
                candidate,
                doc,
                args,
                code="candidate_not_enabled",
                message="Hosted PaddleOCR API inference requires --enable-hosted-api.",
            )
        if not paddleocr_access_token_present():
            return skip_candidate_document(
                candidate,
                doc,
                args,
                code="credential_unavailable",
                message="PADDLEOCR_ACCESS_TOKEN is not configured; no hosted API call was made.",
            )
        if not versions.get("class_available"):
            return skip_candidate_document(
                candidate,
                doc,
                args,
                code="sdk_unavailable",
                message="PaddleOCRClient is not available; install/upgrade paddleocr official API SDK support.",
            )
        return run_ocr_document(candidate, doc, args)

    raise CandidateEvalError(f"Unsupported candidate: {candidate}")


def run_candidate(candidate: str, doc: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if candidate in OCR_CANDIDATES:
        return run_ocr_document(candidate, doc, args)
    if candidate in VLM_CANDIDATES:
        return run_vlm_document(candidate, doc, args)
    raise CandidateEvalError(f"Unsupported candidate: {candidate}")


def artifact_path(run_dir: Path, candidate: str, csv_row: int) -> Path:
    return run_dir / "candidates" / candidate / f"row-{csv_row:04d}.json"


def run_dir_default(run_id: str) -> Path:
    return REPO_ROOT / "data/private/real100_v2/route_candidate_eval" / run_id


def report_dir_default(run_id: str) -> Path:
    return REPO_ROOT / "reports/parser_candidate_eval" / run_id


def summarize_page_for_report(page: dict[str, Any]) -> dict[str, Any]:
    structured = page.get("structured") if isinstance(page.get("structured"), dict) else {}
    return {
        "page": page.get("page"),
        "status": page.get("status"),
        "text_chars": page.get("text_chars"),
        "block_count": page.get("block_count"),
        "avg_confidence": page.get("avg_confidence"),
        "runtime_s": page.get("runtime_s"),
        "failure_code": (page.get("failure") or {}).get("code") if isinstance(page.get("failure"), dict) else None,
        "audit_primary_route": (page.get("audit") or {}).get("primary_route") if isinstance(page.get("audit"), dict) else None,
        "audit_labels": (page.get("audit") or {}).get("labels") if isinstance(page.get("audit"), dict) else None,
        "structured_result_count": structured.get("result_count"),
        "structured_label_counts": structured.get("label_counts"),
    }


def build_aggregate(run_manifest: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_summaries: dict[str, dict[str, Any]] = {}
    artifacts_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for artifact in artifacts:
        artifacts_by_candidate[str(artifact.get("candidate") or "unknown")].append(artifact)

    for candidate, grouped in sorted(artifacts_by_candidate.items()):
        status_counts = Counter(str(artifact.get("status") or "unknown") for artifact in grouped)
        page_status_counts = Counter()
        failure_counts = Counter()
        total_pages = 0
        total_blocks = 0
        total_chars = 0
        confidence_values = []
        runtime_s = 0.0
        by_doc = []
        versions = None
        for artifact in grouped:
            runtime_s += float((artifact.get("provenance") or {}).get("runtime_s") or 0.0)
            versions = versions or (artifact.get("provenance") or {}).get("versions")
            pages = [page for page in artifact.get("pages") or [] if isinstance(page, dict)]
            total_pages += len(pages)
            for page in pages:
                status = str(page.get("status") or "unknown")
                page_status_counts.update([status])
                failure = page.get("failure") if isinstance(page.get("failure"), dict) else None
                if failure and failure.get("code"):
                    failure_counts.update([str(failure["code"])])
                total_blocks += int(page.get("block_count") or 0)
                total_chars += int(page.get("text_chars") or 0)
                confidence = page.get("avg_confidence")
                if isinstance(confidence, (int, float)):
                    confidence_values.append(float(confidence))
            by_doc.append(
                {
                    "csv_row": artifact.get("csv_row"),
                    "subset_rank": artifact.get("subset_rank"),
                    "doc_id": artifact.get("doc_id"),
                    "source_sha256": artifact.get("source_sha256"),
                    "status": artifact.get("status"),
                    "selected_page_count": artifact.get("selected_page_count"),
                    "page_status_counts": dict(Counter(str(page.get("status") or "unknown") for page in pages)),
                    "total_text_chars": sum(int(page.get("text_chars") or 0) for page in pages),
                    "total_blocks": sum(int(page.get("block_count") or 0) for page in pages),
                    "runtime_s": (artifact.get("provenance") or {}).get("runtime_s"),
                    "pages": [summarize_page_for_report(page) for page in pages],
                }
            )
        candidate_summaries[candidate] = {
            "documents": len(grouped),
            "document_status_counts": dict(sorted(status_counts.items())),
            "selected_pages": total_pages,
            "page_status_counts": dict(sorted(page_status_counts.items())),
            "failure_counts": dict(sorted(failure_counts.items())),
            "total_blocks": total_blocks,
            "total_text_chars": total_chars,
            "avg_confidence": round4(sum(confidence_values) / len(confidence_values)) if confidence_values else None,
            "runtime_s": round4(runtime_s),
            "versions": versions,
            "documents_detail": sorted(by_doc, key=lambda item: int(item.get("subset_rank") or 0)),
        }
    return {
        "mode": "route_filtered_candidate_eval",
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "run": run_manifest,
        "summary": {"candidate_summaries": candidate_summaries},
    }


def write_markdown_summary(path: Path, aggregate: dict[str, Any]) -> None:
    run = aggregate.get("run") or {}
    lines = ["# Route-filtered Candidate Eval", ""]
    lines.append(f"- Run ID: `{run.get('run_id', '')}`")
    lines.append(f"- Generated: `{aggregate.get('generated_at_utc')}`")
    lines.append(f"- Page audit: `{run.get('page_audit')}`")
    lines.append(f"- Labels: `{', '.join(run.get('labels') or [])}`")
    lines.append(f"- Primary routes: `{', '.join(run.get('primary_routes') or [])}`")
    lines.append(f"- PaddleOCR Python: `{run.get('paddleocr_python')}`")
    lines.append(f"- Local VLM enabled: `{run.get('enable_local_vlm')}`")
    lines.append(f"- Hosted API enabled: `{run.get('enable_hosted_api')}`")
    lines.append(f"- Hosted API model: `{run.get('paddleocr_api_model')}`")
    lines.append(f"- PaddleOCR access token present: `{run.get('paddleocr_access_token_present')}`")
    lines.append(f"- Dry run: `{run.get('dry_run')}`")
    lines.append("")
    for candidate, summary in (aggregate.get("summary") or {}).get("candidate_summaries", {}).items():
        lines.append(f"## `{candidate}`")
        lines.append("")
        lines.append(f"- Documents: `{summary.get('documents')}`")
        lines.append(f"- Selected pages: `{summary.get('selected_pages')}`")
        lines.append(f"- Page status counts: `{summary.get('page_status_counts')}`")
        lines.append(f"- Total blocks: `{summary.get('total_blocks')}`")
        lines.append(f"- Total text chars: `{summary.get('total_text_chars')}`")
        lines.append(f"- Avg confidence: `{summary.get('avg_confidence')}`")
        lines.append(f"- Runtime seconds: `{summary.get('runtime_s')}`")
        lines.append(f"- Versions: `{summary.get('versions')}`")
        lines.append("")
        lines.append("| csv_row | pages | status | page statuses | chars | blocks | runtime_s |")
        lines.append("|---:|---:|---|---|---:|---:|---:|")
        for doc in summary.get("documents_detail") or []:
            lines.append(
                f"| {doc.get('csv_row')} | {doc.get('selected_page_count')} | {doc.get('status')} | "
                f"`{doc.get('page_status_counts')}` | {doc.get('total_text_chars')} | "
                f"{doc.get('total_blocks')} | {doc.get('runtime_s')} |"
            )
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run candidates on page-audit selected pages.")
    parser.add_argument("--page-audit", required=True, help="Raw page_audit.json from scripts/audit_parser_pages.py.")
    parser.add_argument("--candidates", default="paddleocr_classic", help="Comma-separated candidate names.")
    parser.add_argument("--labels", default=",".join(DEFAULT_LABELS), help="Comma-separated page labels to select.")
    parser.add_argument("--primary-routes", default="", help="Comma-separated primary routes to select.")
    parser.add_argument("--csv-rows", default="", help="Optional comma-separated csv_row filter.")
    parser.add_argument("--max-pages", type=int, default=None, help="Optional global page cap for smoke runs.")
    parser.add_argument("--render-dpi", type=int, default=DEFAULT_RENDER_DPI)
    parser.add_argument("--tesseract-lang", default=DEFAULT_TESSERACT_LANG)
    parser.add_argument(
        "--paddleocr-python",
        default=sys.executable,
        help="Python executable for PaddleOCR subprocess candidates; use an isolated venv to avoid global env changes.",
    )
    parser.add_argument("--enable-local-vlm", action="store_true", help="Permit local PP-StructureV3/PaddleOCR-VL inference.")
    parser.add_argument(
        "--allow-model-download",
        action="store_true",
        help="Allow local PaddleOCR VLM/structure candidates to download missing models.",
    )
    parser.add_argument("--local-vlm-device", default=None, help="Optional PaddleOCR local VLM device, e.g. cpu.")
    parser.add_argument(
        "--paddleocr-vl-pipeline-version",
        default=DEFAULT_PADDLEOCR_VL_PIPELINE_VERSION,
        help="PaddleOCRVL local pipeline_version.",
    )
    parser.add_argument("--enable-hosted-api", action="store_true", help="Permit hosted PaddleOCR official API calls.")
    parser.add_argument(
        "--paddleocr-api-model",
        default=DEFAULT_PADDLEOCR_API_MODEL,
        choices=PADDLEOCR_API_MODEL_CHOICES,
        help="Hosted PaddleOCR document parsing model.",
    )
    parser.add_argument("--paddleocr-api-request-timeout-s", type=float, default=300.0)
    parser.add_argument("--paddleocr-api-poll-timeout-s", type=float, default=600.0)
    parser.add_argument("--paddleocr-api-base-url", default=None)
    parser.add_argument(
        "--page-timeout-s",
        type=float,
        default=120.0,
        help="Per-page subprocess timeout for expensive OCR inference. Use <=0 to disable.",
    )
    parser.add_argument("--page-retries", type=int, default=0, help="Per-page retry count after OCR failure/timeout.")
    parser.add_argument("--run-id", default=None, help="Run id. Defaults to route-candidate-<UTC>.")
    parser.add_argument("--run-dir", default=None, help="Local/private raw output dir.")
    parser.add_argument("--report-dir", default=None, help="Aggregate report output dir.")
    parser.add_argument("--dry-run", action="store_true", help="Select pages and write artifacts without inference.")
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        args.candidates = parse_candidates(args.candidates)
        args.labels = parse_csv_values(args.labels)
        args.primary_routes = parse_csv_values(args.primary_routes)
        csv_rows_values = parse_csv_values(args.csv_rows)
        csv_rows = {int(value) for value in csv_rows_values} if csv_rows_values else None
        if not args.labels and not args.primary_routes:
            raise CandidateEvalError("At least one --labels or --primary-routes value is required")

        run_id = args.run_id or f"route-candidate-{utc_now()}"
        run_dir = Path(args.run_dir) if args.run_dir else run_dir_default(run_id)
        report_dir = Path(args.report_dir) if args.report_dir else report_dir_default(run_id)
        page_audit_path = Path(args.page_audit)
        page_audit_run, documents = load_page_audit(page_audit_path)
        selected = selected_documents(
            documents,
            labels=args.labels,
            primary_routes=args.primary_routes,
            csv_rows=csv_rows,
            max_pages=args.max_pages,
        )
        if not selected:
            raise CandidateEvalError("No pages matched the requested labels/routes")
        run_manifest = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "generated_at_utc": utc_now(),
            "page_audit": str(page_audit_path),
            "page_audit_run_id": page_audit_run.get("run_id"),
            "run_dir": str(run_dir),
            "report_dir": str(report_dir),
            "candidates": args.candidates,
            "labels": args.labels,
            "primary_routes": args.primary_routes,
            "csv_rows": sorted(csv_rows) if csv_rows else None,
            "max_pages": args.max_pages,
            "render_dpi": args.render_dpi,
            "paddleocr_python": args.paddleocr_python,
            "enable_local_vlm": bool(args.enable_local_vlm),
            "allow_model_download": bool(args.allow_model_download),
            "local_vlm_device": args.local_vlm_device,
            "paddleocr_vl_pipeline_version": args.paddleocr_vl_pipeline_version,
            "enable_hosted_api": bool(args.enable_hosted_api),
            "paddleocr_api_model": args.paddleocr_api_model,
            "paddleocr_api_request_timeout_s": args.paddleocr_api_request_timeout_s,
            "paddleocr_api_poll_timeout_s": args.paddleocr_api_poll_timeout_s,
            "paddleocr_api_base_url_present": bool(args.paddleocr_api_base_url),
            "paddleocr_access_token_present": paddleocr_access_token_present(),
            "dry_run": bool(args.dry_run),
            "selected_documents": len(selected),
            "selected_pages": sum(len(doc.get("selected_pages") or []) for doc in selected),
        }
        write_json(run_dir / "run_manifest.json", run_manifest)
        artifacts: list[dict[str, Any]] = []
        for candidate in args.candidates:
            for doc in selected:
                artifact = run_candidate(candidate, doc, args)
                artifacts.append(artifact)
                write_json(artifact_path(run_dir, candidate, int(doc.get("csv_row") or 0)), artifact)
        aggregate = build_aggregate(run_manifest, artifacts)
        write_json(report_dir / "route_candidate_eval.aggregate.json", aggregate)
        write_markdown_summary(report_dir / "route_candidate_eval.md", aggregate)
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "report_dir": str(report_dir),
                    "selected_documents": run_manifest["selected_documents"],
                    "selected_pages": run_manifest["selected_pages"],
                    "candidate_summaries": aggregate["summary"]["candidate_summaries"],
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
