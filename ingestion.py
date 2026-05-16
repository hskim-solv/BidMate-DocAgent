#!/usr/bin/env python3
"""CSV-backed PDF/HWP ingestion for private RFP experiments.

The v1 loader uses the extracted text already present in data_list.csv. It
still validates the referenced PDF/HWP files so missing source data is visible
in the ingestion report.
"""

from __future__ import annotations

import csv
import os
import warnings
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any
import unicodedata

from bidmate_security import redact_pii
from rag_metadata_extraction import extract_rfp_metadata


def _pii_redaction_enabled() -> bool:
    """Issue #455 / ADR 0028: opt-in PII redaction at ingestion time.

    Default off. Enable with ``BIDMATE_INGEST_REDACT_PII=true`` (or
    ``1`` / ``yes``). When enabled, the loader-returned text is passed
    through ``bidmate_security.redact_pii`` before chunking — Korean
    mobile phone, email, and 주민등록번호 are replaced with stable
    tokens (``<phone>``, ``<email>``, ``<rrn>``). ADR 0001 invariant:
    default off keeps ``naive_baseline`` byte-identical.
    """
    return os.environ.get("BIDMATE_INGEST_REDACT_PII", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

# HWPX (.hwpx) is the XML-based successor to HWP (ZIP archive, not OLE binary).
# pyhwp does not support HWPX; a dedicated HwpxLoader is deferred to issue #543.
SUPPORTED_FILE_FORMATS = {"pdf", "hwp"}

REQUIRED_COLUMNS = [
    "공고 번호",
    "사업명",
    "발주 기관",
    "파일형식",
    "파일명",
    "텍스트",
]

# Bumped 2 → 3 in issue #715: summary now carries ``text_source_counts``,
# ``fallback_reasons``, and ``chunk_health`` (the last is filled by
# ``scripts/build_index.py`` after the chunk-building stage). The three keys
# are additive and downstream readers use ``dict.get``, so a v2 reader
# silently ignores them.
#
# Bumped 3 → 4 in issue #902: ``summary.chunk_health`` gains three additive
# kordoc-loss fields (``nested_table_loss_count``,
# ``nested_table_loss_files``, ``nested_table_loss_samples``). v3 readers that
# already use ``dict.get`` on ``chunk_health`` ignore them transparently.
INGESTION_REPORT_SCHEMA_VERSION = 4

# Public, reviewer-facing failure taxonomy for ingestion. Keep keys stable;
# downstream tooling (eval/run_eval.py, docs, dashboards) reads them.
FAILURE_TAXONOMY: dict[str, dict[str, str]] = {
    "missing_file_name": {
        "stage": "row",
        "downstream_risk": "Row cannot be matched to any source file.",
    },
    "missing_doc_id": {
        "stage": "row",
        "downstream_risk": "Row produces no stable identifier; eval cannot reference it.",
    },
    "duplicate_doc_id": {
        "stage": "row",
        "downstream_risk": "Two rows would collide in the index; later row is dropped.",
    },
    "unsupported_file_format": {
        "stage": "row",
        "downstream_risk": "PDF/HWP path is the only supported v1 format.",
    },
    "missing_file": {
        "stage": "filesystem",
        "downstream_risk": "Source file is referenced but not present on disk.",
    },
    "empty_text": {
        "stage": "text",
        "downstream_risk": "CSV has no body text for this row; nothing to chunk or embed.",
    },
}


@dataclass(frozen=True)
class IngestionRecord:
    row_number: int
    status: str
    doc_id: str | None
    file_name: str
    file_format: str
    source_path: str
    reason: str | None = None
    duplicate_resolution: dict[str, Any] | None = None
    messages: tuple[str, ...] = ()
    # Issue #715: per-document loader provenance. ``text_source`` mirrors
    # ``HwpLoader.last_text_source`` ("hwp_native" / "data_list_csv_text"
    # / similar); ``fallback_reason`` mirrors ``HwpLoader.last_fallback_reason``
    # (``"ExceptionName: truncated message"`` or ``None``). Both are populated
    # only after the loader successfully extracted text — failures upstream of
    # the loader keep them at ``None``. Existing readers see no change because
    # both fields default to ``None`` and downstream report consumers use
    # ``dict.get`` (additive bump 2 → 3 of ``INGESTION_REPORT_SCHEMA_VERSION``).
    text_source: str | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    field: str
    message: str
    row_number: int | None = None


@dataclass
class _DuplicateTracker:
    seen: dict[str, int] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)


class CsvTextDocumentLoader:
    file_format = ""

    def load_text(self, row: dict[str, str], source_path: Path) -> str:
        text = normalize_body_text(row.get("텍스트", ""))
        if not text:
            raise ValueError("empty_text")
        return text


class PdfCsvTextLoader(CsvTextDocumentLoader):
    file_format = "pdf"


class HwpCsvTextLoader(CsvTextDocumentLoader):
    file_format = "hwp"


class _KordocLoader(CsvTextDocumentLoader):
    """Base loader that shells out to kordoc (npm) to produce Markdown.

    Replaces the legacy pyhwp/hwp5 backend (ADR 0036) and the
    cover/TOC-only ``PdfCsvTextLoader`` path — see ADR 0049 for
    rationale. kordoc preserves table structure (``<table>`` with
    ``rowspan``/``colspan``), headings, and form-document layout that
    paragraph-only pyhwp extraction and CSV-text PDF extraction discard.

    On any subprocess failure (Node missing, npx error, empty output)
    falls back to the CSV ``텍스트`` column so ADR 0001's naive baseline
    invariant holds offline. The fallback path is identical to the
    pre-kordoc contract — `csv_text` is now load-bearing for offline
    correctness, not just for ADR 0001 comparison.

    Diagnostics: ``last_text_source`` records ``"kordoc"`` or
    ``"data_list_csv_text"``; ``last_fallback_reason`` records
    ``"ExceptionName: truncated message"`` when fallback fires
    (``None`` otherwise). ``reports/eval_summary.json::text_source_counts``
    keeps working with a key rename only (``hwp_native`` → ``kordoc``).

    Batch optimization: callers (``load_documents_from_metadata_csv``)
    call ``prime_batch(source_paths)`` once to invoke kordoc on the full
    file list in one subprocess and cache the resulting Markdown. Per-row
    ``load_text`` then reads from cache, avoiding N separate ``npx``
    invocations. Subclasses set ``file_format`` to ``"hwp"`` / ``"pdf"``.
    """

    file_format = ""

    def __init__(self) -> None:
        self.last_text_source = "data_list_csv_text"
        self.last_fallback_reason: str | None = None
        self._batch_cache: dict[str, str] = {}

    def prime_batch(self, source_paths: list[Path]) -> None:
        """Pre-convert all source paths in a single kordoc subprocess.

        On Node-missing / subprocess error / empty output, leaves the
        cache empty so per-row ``load_text`` records ``last_fallback_reason``
        and falls back to CSV. Errors are visible via ``last_fallback_reason``
        on the first ``load_text`` call.
        """
        if not source_paths:
            return
        unique = list({str(p): p for p in source_paths}.values())
        try:
            markdown_by_stem = _kordoc_convert_batch(unique)
        except _KordocFallback as exc:
            self.last_fallback_reason = f"{type(exc.__cause__).__name__ if exc.__cause__ else 'KordocError'}: {str(exc)[:120]}"
            warnings.warn(
                f"{type(self).__name__} batch fallback to CSV text: {self.last_fallback_reason}",
                RuntimeWarning,
                stacklevel=2,
            )
            return
        for path in unique:
            text = markdown_by_stem.get(_kordoc_output_stem(path))
            if text:
                self._batch_cache[str(path)] = text

    def load_text(self, row: dict[str, str], source_path: Path) -> str:
        self.last_text_source = "data_list_csv_text"
        cached = self._batch_cache.get(str(source_path))
        if cached:
            self.last_text_source = "kordoc"
            return cached
        text = normalize_body_text(row.get("텍스트", ""))
        if not text:
            raise ValueError("empty_text")
        return text


class HwpKordocLoader(_KordocLoader):
    file_format = "hwp"


class PdfKordocLoader(_KordocLoader):
    file_format = "pdf"


class _KordocFallback(RuntimeError):
    """Internal marker raised by ``_kordoc_convert_batch`` to trigger CSV fallback.

    Wraps the underlying cause (``FileNotFoundError`` for missing Node,
    ``subprocess.CalledProcessError`` for npx non-zero exit, ``ValueError``
    for empty output) so the caller can record one unified
    ``last_fallback_reason`` without exposing subprocess internals.
    """


_KORDOC_VERSION_FILE = Path(__file__).resolve().parent / ".kordoc-version"


def _read_kordoc_version_spec() -> str:
    """Read the pinned kordoc npm spec from ``.kordoc-version``.

    Returns ``"kordoc@<version>"`` when the file holds a valid version
    string, or ``"kordoc"`` (unpinned) when the file is absent or
    unreadable. Drift detection lives in
    ``tests/test_ingestion_kordoc_regression.py``.
    """
    try:
        version = _KORDOC_VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "kordoc"
    if not version or any(c in version for c in {" ", "\n", ";", "&", "|"}):
        return "kordoc"
    return f"kordoc@{version}"


def _kordoc_output_stem(source_path: Path) -> str:
    """NFC-normalize the stem so Korean filenames round-trip across macOS / Linux.

    macOS HFS+ stores filenames in NFD; kordoc writes the output filename
    using the input filename verbatim. Without normalization, the dict key
    `_batch_cache.get(str(source_path))` and the file we found on disk
    can disagree purely on Unicode normalization form.
    """
    return unicodedata.normalize("NFC", source_path.stem)


def _kordoc_convert_batch(source_paths: list[Path]) -> dict[str, str]:
    """Invoke ``npx kordoc`` on the file list, return ``{stem: markdown}``.

    Raises ``_KordocFallback`` on:

    * ``FileNotFoundError`` — ``node`` / ``npx`` missing on PATH.
    * ``subprocess.CalledProcessError`` — npx exit code != 0 (e.g.
      offline / network blocked, kordoc parse error on all files).
    * ``ValueError`` — subprocess succeeded but produced no output files.

    On success returns a dict mapping ``Path.stem`` (NFC-normalized) to
    the Markdown text content of the corresponding output file.
    """
    import subprocess  # noqa: PLC0415 — local import keeps module load fast for non-HWP paths
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    if shutil.which("node") is None or shutil.which("npx") is None:
        raise _KordocFallback("node/npx not on PATH") from FileNotFoundError(
            "node/npx not found"
        )

    kordoc_spec = _read_kordoc_version_spec()

    with tempfile.TemporaryDirectory(prefix="bidmate_kordoc_") as tmpdir:
        out_dir = Path(tmpdir)
        cmd = [
            "npx",
            "-y",
            "-p",
            kordoc_spec,
            "-p",
            "pdfjs-dist",
            "kordoc",
            *[str(p) for p in source_paths],
            "-d",
            str(out_dir),
            "--silent",
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.CalledProcessError as exc:
            stderr_tail = (exc.stderr or "")[-200:].strip()
            raise _KordocFallback(f"npx exit {exc.returncode}: {stderr_tail}") from exc
        except subprocess.TimeoutExpired as exc:
            raise _KordocFallback(f"npx timeout after {exc.timeout}s") from exc

        markdown_by_stem: dict[str, str] = {}
        for md_path in out_dir.glob("*.md"):
            try:
                content = md_path.read_text(encoding="utf-8")
            except OSError:
                continue
            stem = unicodedata.normalize("NFC", md_path.stem)
            normalized = normalize_body_text(content)
            if normalized:
                markdown_by_stem[stem] = normalized
        if not markdown_by_stem:
            raise _KordocFallback("kordoc produced no readable output")
        return markdown_by_stem


def build_sections_with_native_tables(
    body_text: str,
    native_tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the per-document ``sections`` list. Kordoc-era stub: tables now
    arrive inline as HTML inside ``body_text``, so ``native_tables`` is
    always empty and this returns exactly ``[{"heading": "본문", "text": body_text}]``.

    Kept as a function (rather than inlined at the call site) because
    several test fixtures construct documents via this helper. The
    ``native_tables`` parameter is retained for signature compatibility
    but is asserted empty — ADR 0049 supersedes the per-table-section
    surface ADR 0036 introduced.
    """
    return [{"heading": "본문", "text": body_text}]


LOADERS: dict[str, CsvTextDocumentLoader] = {
    "pdf": PdfCsvTextLoader(),
    "hwp": HwpCsvTextLoader(),
}


_HWP_KORDOC_LOADER: HwpKordocLoader | None = None
_PDF_KORDOC_LOADER: PdfKordocLoader | None = None


def _reset_kordoc_loaders() -> None:
    """Drop the module-level kordoc loader singletons (HWP + PDF).

    Called at the start of ``load_documents_from_metadata_csv`` so each
    ingestion run gets a fresh batch cache and resets
    ``last_text_source`` / ``last_fallback_reason``. Tests use this to
    isolate runs.
    """
    global _HWP_KORDOC_LOADER, _PDF_KORDOC_LOADER
    _HWP_KORDOC_LOADER = None
    _PDF_KORDOC_LOADER = None


_reset_hwp_kordoc_loader = _reset_kordoc_loaders


def _resolve_loader(file_format: str) -> CsvTextDocumentLoader:
    """Pick the loader for ``file_format``.

    For HWP and PDF, env-var precedence (ADR 0049, highest to lowest):

    * ``BIDMATE_HWP_LOADER=csv_text`` / ``BIDMATE_PDF_LOADER=csv_text`` —
      explicit opt-out; use the CSV-text loader for that format.
    * *(unset)* or ``=kordoc`` — default to the kordoc-backed loader.
      Auto-degrades to CSV at runtime when ``node`` / ``npx`` is missing or
      the subprocess fails (telemetry-visible via ``last_fallback_reason``).

    Legacy HWP values ``csv`` / ``native`` / ``native_tables`` from ADR 0036
    are aliased to ``csv_text`` (CSV fallback); the two deprecated names
    fire a one-shot ``DeprecationWarning`` so existing deploy scripts keep
    working without immediate breakage.

    Each kordoc loader instance is cached at module level so a single
    ``prime_batch`` (called once from ``load_documents_from_metadata_csv``)
    populates the cache the per-row ``_resolve_loader`` calls then read from.
    """
    global _HWP_KORDOC_LOADER, _PDF_KORDOC_LOADER
    if file_format == "hwp":
        opt_in = os.environ.get("BIDMATE_HWP_LOADER", "").strip().lower()
        if opt_in in {"native", "native_tables"}:
            warnings.warn(
                f"BIDMATE_HWP_LOADER={opt_in!r} is deprecated (ADR 0036 superseded by 0049); "
                "kordoc is now the default. Set BIDMATE_HWP_LOADER=csv_text to force CSV fallback.",
                DeprecationWarning,
                stacklevel=2,
            )
            return LOADERS[file_format]
        if opt_in in {"csv", "csv_text"}:
            return LOADERS[file_format]
        if _HWP_KORDOC_LOADER is None:
            _HWP_KORDOC_LOADER = HwpKordocLoader()
        return _HWP_KORDOC_LOADER
    if file_format == "pdf":
        opt_in = os.environ.get("BIDMATE_PDF_LOADER", "").strip().lower()
        if opt_in in {"csv", "csv_text"}:
            return LOADERS[file_format]
        if _PDF_KORDOC_LOADER is None:
            _PDF_KORDOC_LOADER = PdfKordocLoader()
        return _PDF_KORDOC_LOADER
    return LOADERS[file_format]


def _prime_kordoc_batches(
    rows: list[dict[str, str]], files_dir: Path
) -> None:
    """Pre-convert every HWP + PDF source in one kordoc subprocess.

    Combines both formats into a single ``npx kordoc`` invocation so the
    npm fetch + spin-up cost is paid once per ingestion run. Routes the
    resulting Markdown into each loader's cache by file extension.

    No-op for any format whose resolver returns the CSV-text loader
    (env opt-out) or whose row list is empty. Per-row ``_resolve_loader``
    calls then read the primed cache; misses (Node-down / subprocess
    error / NFC mismatch) fall through to ``data_list_csv_text``.
    """
    paths_by_format: dict[str, list[Path]] = {"hwp": [], "pdf": []}
    for row in rows:
        file_name = clean_cell(row.get("파일명"))
        if not file_name:
            continue
        file_format = normalize_file_format(row.get("파일형식"), file_name)
        if file_format not in paths_by_format:
            continue
        source_path = find_source_file(files_dir, file_name)
        if source_path.exists() and source_path.is_file():
            paths_by_format[file_format].append(source_path)

    loaders: dict[str, _KordocLoader] = {}
    for fmt, paths in paths_by_format.items():
        if not paths:
            continue
        loader = _resolve_loader(fmt)
        if isinstance(loader, _KordocLoader):
            loaders[fmt] = loader

    if not loaders:
        return

    combined: list[Path] = []
    for fmt in loaders:
        combined.extend(paths_by_format[fmt])

    try:
        markdown_by_stem = _kordoc_convert_batch(combined)
    except _KordocFallback as exc:
        reason = (
            f"{type(exc.__cause__).__name__ if exc.__cause__ else 'KordocError'}: "
            f"{str(exc)[:120]}"
        )
        for loader in loaders.values():
            loader.last_fallback_reason = reason
            warnings.warn(
                f"{type(loader).__name__} batch fallback to CSV text: {reason}",
                RuntimeWarning,
                stacklevel=2,
            )
        return

    for fmt, loader in loaders.items():
        for path in paths_by_format[fmt]:
            text = markdown_by_stem.get(_kordoc_output_stem(path))
            if text:
                loader._batch_cache[str(path)] = text


_prime_hwp_kordoc_batch = _prime_kordoc_batches


def load_documents_from_metadata_csv(
    metadata_csv: Path,
    files_dir: Path,
    *,
    on_duplicate_doc_id: str = "fail",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if on_duplicate_doc_id not in {"fail", "suffix"}:
        raise ValueError(
            "on_duplicate_doc_id must be 'fail' or 'suffix'; got: "
            f"{on_duplicate_doc_id}"
        )
    if not metadata_csv.exists():
        raise ValueError(f"--metadata_csv does not exist: {metadata_csv}")
    if not metadata_csv.is_file():
        raise ValueError(f"--metadata_csv must be a file: {metadata_csv}")
    if not files_dir.exists():
        raise ValueError(f"--files_dir does not exist: {files_dir}")
    if not files_dir.is_dir():
        raise ValueError(f"--files_dir must be a directory: {files_dir}")

    documents: list[dict[str, Any]] = []
    records: list[IngestionRecord] = []
    tracker = _DuplicateTracker()

    _reset_kordoc_loaders()

    with metadata_csv.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        validate_fieldnames(reader.fieldnames or [], metadata_csv)
        rows = list(reader)

    _prime_kordoc_batches(rows, files_dir)

    for row_number, row in enumerate(rows, start=2):
        document, record = normalize_ingestion_row(
            row,
            row_number,
            files_dir,
            tracker,
            on_duplicate_doc_id=on_duplicate_doc_id,
        )
        records.append(record)
        if document is not None:
            documents.append(document)

    if not documents:
        failure_reasons = sorted({record.reason or record.status for record in records})
        raise ValueError(
            "No PDF/HWP documents could be ingested from "
            f"{metadata_csv}. Failure reasons: {', '.join(failure_reasons) or 'none'}"
        )

    report = build_ingestion_report(
        metadata_csv=metadata_csv,
        files_dir=files_dir,
        records=records,
        indexed_count=len(documents),
        on_duplicate_doc_id=on_duplicate_doc_id,
    )
    return documents, report


def validate_fieldnames(fieldnames: list[str], metadata_csv: Path) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(
            f"{metadata_csv} is missing required columns: {', '.join(missing)}"
        )


@dataclass
class _RowValidation:
    """Row-level resolution result shared by ingestion + audit paths."""

    file_name: str
    file_format: str
    source_path: Path
    doc_id: str
    base_doc_id: str
    failure_reason: str | None
    duplicate_resolution: dict[str, Any] | None
    # True when this row reserved a fresh slot in the tracker (no
    # duplicate collision and validation passed up to that point).
    # Callers use this to gate post-resolution checks like ``empty_text``.
    tracker_registered: bool


def _resolve_row_validation(
    row: dict[str, str],
    row_number: int,
    files_dir: Path,
    tracker: _DuplicateTracker,
    *,
    on_duplicate_doc_id: str = "fail",
) -> _RowValidation:
    """Run the shared row-identity + duplicate-resolution validation chain.

    Used by ``normalize_ingestion_row`` (which then loads the body text)
    and ``audit_metadata_row`` (which then checks for blank body text).
    Mutates ``tracker`` in place: a fresh row is recorded; a suffix
    collision reserves the next unique id.
    """
    notice_id = clean_cell(row.get("공고 번호"))
    notice_round = clean_cell(row.get("공고 차수"))
    file_name = clean_cell(row.get("파일명"))
    file_format = normalize_file_format(row.get("파일형식"), file_name)
    source_path = find_source_file(files_dir, file_name) if file_name else files_dir
    base_doc_id = canonical_doc_id(notice_id, notice_round, file_name)

    duplicate_resolution: dict[str, Any] | None = None
    failure_reason: str | None = None
    doc_id = base_doc_id
    tracker_registered = False

    if not file_name:
        failure_reason = "missing_file_name"
    elif not doc_id:
        failure_reason = "missing_doc_id"
    elif file_format not in SUPPORTED_FILE_FORMATS:
        failure_reason = "unsupported_file_format"
    elif not source_path.exists() or not source_path.is_file():
        failure_reason = "missing_file"
    else:
        existing_row = tracker.seen.get(base_doc_id)
        if existing_row is not None:
            if on_duplicate_doc_id == "suffix":
                suggested = reserve_next_unique_doc_id(base_doc_id, tracker)
                doc_id = suggested
                duplicate_resolution = {
                    "policy": "suffix",
                    "base_doc_id": base_doc_id,
                    "first_seen_row": existing_row,
                    "assigned_doc_id": suggested,
                }
            else:
                # Read-only peek: do not reserve the suggested id, otherwise
                # a later row whose canonical doc_id is legitimately
                # <base>-N would be falsely flagged as a duplicate.
                suggested = peek_next_unique_doc_id(base_doc_id, tracker)
                failure_reason = "duplicate_doc_id"
                duplicate_resolution = {
                    "policy": "fail",
                    "base_doc_id": base_doc_id,
                    "first_seen_row": existing_row,
                    "suggested_doc_id": suggested,
                }
        else:
            tracker.seen[base_doc_id] = row_number
            tracker.counts[base_doc_id] = 1
            tracker_registered = True

    return _RowValidation(
        file_name=file_name,
        file_format=file_format,
        source_path=source_path,
        doc_id=doc_id,
        base_doc_id=base_doc_id,
        failure_reason=failure_reason,
        duplicate_resolution=duplicate_resolution,
        tracker_registered=tracker_registered,
    )


def normalize_ingestion_row(
    row: dict[str, str],
    row_number: int,
    files_dir: Path,
    tracker: _DuplicateTracker,
    *,
    on_duplicate_doc_id: str = "fail",
) -> tuple[dict[str, Any] | None, IngestionRecord]:
    validation = _resolve_row_validation(
        row, row_number, files_dir, tracker, on_duplicate_doc_id=on_duplicate_doc_id
    )

    if validation.failure_reason:
        return None, make_record(
            row_number,
            "failed",
            validation.doc_id,
            validation.file_name,
            validation.file_format,
            validation.source_path,
            validation.failure_reason,
            duplicate_resolution=validation.duplicate_resolution,
        )

    loader = _resolve_loader(validation.file_format)
    try:
        text = loader.load_text(row, validation.source_path)
    except ValueError as exc:
        # Issue #715: surface loader provenance even on failure — the HWP
        # native loader may have raised mid-parse (e.g. InvalidHwp5FileError)
        # after stashing the exception on ``last_fallback_reason``. The CSV
        # text loader has neither attribute, so getattr defaults keep the
        # plain PDF / CSV failure paths backward-compatible.
        return None, make_record(
            row_number,
            "failed",
            validation.doc_id,
            validation.file_name,
            validation.file_format,
            validation.source_path,
            str(exc),
            duplicate_resolution=validation.duplicate_resolution,
            text_source=getattr(loader, "last_text_source", None),
            fallback_reason=getattr(loader, "last_fallback_reason", None),
        )
    # Issue #455 / ADR 0028: opt-in PII redaction. Default off keeps
    # ADR 0001 naive_baseline byte-identical; the env-var gate is the
    # single switch operators flip in deployment.
    if _pii_redaction_enabled():
        text = redact_pii(text)

    text_source = getattr(loader, "last_text_source", "data_list_csv_text")
    fallback_reason = getattr(loader, "last_fallback_reason", None)
    metadata = normalize_metadata(
        row, validation.file_format, validation.file_name, text_source=text_source
    )
    metadata["doc_id"] = validation.doc_id
    if validation.duplicate_resolution and on_duplicate_doc_id == "suffix":
        metadata["doc_id_resolution"] = validation.duplicate_resolution["policy"]
        metadata["doc_id_base"] = validation.duplicate_resolution["base_doc_id"]

    sections = build_sections_with_native_tables(text, [])

    document = {
        "doc_id": validation.doc_id,
        "title": clean_cell(row.get("사업명")) or Path(validation.file_name).stem,
        "agency": clean_cell(row.get("발주 기관")),
        "project": clean_cell(row.get("사업명")),
        "metadata": metadata,
        "sections": sections,
        "source_path": str(validation.source_path),
    }
    # Issue #180 wire-up: write the eight-field structured extraction
    # into ``metadata["extracted"]`` as an *additive* sidecar. The
    # regex backend is the default (ADR 0001 invariant), so this stays
    # deterministic and offline unless ``BIDMATE_METADATA_BACKEND`` is
    # flipped to ``anthropic_tool_use`` / ``openai_function_call``.
    # Top-level ``agency`` / ``project`` are intentionally untouched —
    # downstream chunk metadata propagation in rag_core.py and the
    # answer/citation contract (ADR 0003) read those fields.
    document["metadata"]["extracted"] = extract_rfp_metadata(document).as_dict()
    return document, make_record(
        row_number,
        "indexed",
        validation.doc_id,
        validation.file_name,
        validation.file_format,
        validation.source_path,
        duplicate_resolution=validation.duplicate_resolution,
        text_source=text_source,
        fallback_reason=fallback_reason,
    )


def make_record(
    row_number: int,
    status: str,
    doc_id: str | None,
    file_name: str,
    file_format: str,
    source_path: Path,
    reason: str | None = None,
    *,
    duplicate_resolution: dict[str, Any] | None = None,
    messages: tuple[str, ...] = (),
    text_source: str | None = None,
    fallback_reason: str | None = None,
) -> IngestionRecord:
    return IngestionRecord(
        row_number=row_number,
        status=status,
        doc_id=doc_id,
        file_name=file_name,
        file_format=file_format,
        source_path=str(source_path),
        reason=reason,
        duplicate_resolution=duplicate_resolution,
        messages=messages,
        text_source=text_source,
        fallback_reason=fallback_reason,
    )


def normalize_metadata(
    row: dict[str, str],
    file_format: str,
    file_name: str,
    *,
    text_source: str = "data_list_csv_text",
) -> dict[str, Any]:
    return {
        "notice_id": clean_cell(row.get("공고 번호")),
        "notice_round": clean_cell(row.get("공고 차수")),
        "project": clean_cell(row.get("사업명")),
        "budget": parse_budget(row.get("사업 금액")),
        "agency": clean_cell(row.get("발주 기관")),
        "published_at": clean_cell(row.get("공개 일자")),
        "bid_start_at": clean_cell(row.get("입찰 참여 시작일")),
        "bid_deadline_at": clean_cell(row.get("입찰 참여 마감일")),
        "summary": clean_cell(row.get("사업 요약")),
        "file_format": file_format,
        "file_name": file_name,
        "doc_id_source": "notice_id" if clean_cell(row.get("공고 번호")) else "file_name",
        "document_type": "private_pdf_hwp_csv_text",
        "text_source": text_source,
    }


def normalize_file_format(value: str | None, file_name: str) -> str:
    raw_format = clean_cell(value).lower().lstrip(".")
    if raw_format:
        return raw_format
    return Path(file_name).suffix.lower().lstrip(".")


def find_source_file(files_dir: Path, file_name: str) -> Path:
    candidate = files_dir / file_name
    if candidate.exists():
        return candidate

    normalized_name = unicodedata.normalize("NFC", file_name)
    for path in files_dir.iterdir():
        if unicodedata.normalize("NFC", path.name) == normalized_name:
            return path
    return candidate


def canonical_doc_id(
    notice_id: str | None,
    notice_round: str | None,
    file_name: str | None,
) -> str | None:
    """Single canonical doc_id rule used across ingestion paths.

    Priority:
      1. ``notice_id`` (+ optional ``notice_round``) if non-empty.
      2. File-name stem fallback.
    Both branches NFC-normalize, casefold, and collapse whitespace so the
    same source row produces the same id across runs and platforms.
    """
    notice = clean_cell(notice_id)
    if notice:
        return make_doc_id(notice, clean_cell(notice_round))
    return make_doc_id_from_file_name(clean_cell(file_name or ""))


def make_doc_id(notice_id: str, notice_round: str) -> str:
    parts = [notice_id]
    if notice_round:
        parts.append(notice_round)
    slugged = [slug_part(part) for part in parts if slug_part(part)]
    return "-".join(slugged)


def make_doc_id_from_file_name(file_name: str) -> str | None:
    if not file_name:
        return None
    stem = Path(file_name).stem
    slug = slug_part(stem)
    return slug or None


def slug_part(value: str) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFC", value).strip()
    normalized = re.sub(r"\s+", "-", normalized)
    return normalized


def _compute_next_unique_doc_id(
    base_doc_id: str,
    tracker: _DuplicateTracker,
) -> tuple[str, int]:
    count = tracker.counts.get(base_doc_id, 1) + 1
    candidate = f"{base_doc_id}-{count}"
    while candidate in tracker.seen:
        count += 1
        candidate = f"{base_doc_id}-{count}"
    return candidate, count


def peek_next_unique_doc_id(base_doc_id: str, tracker: _DuplicateTracker) -> str:
    """Compute the next available ``<base>-N`` id without mutating ``tracker``.

    Used when ``on_duplicate_doc_id="fail"`` so the failure record can carry a
    ``suggested_doc_id`` for diagnostics without reserving an id that no row
    will ever take. A later row whose canonical doc_id is legitimately
    ``<base>-N`` must remain free to claim it.
    """
    candidate, _ = _compute_next_unique_doc_id(base_doc_id, tracker)
    return candidate


def reserve_next_unique_doc_id(base_doc_id: str, tracker: _DuplicateTracker) -> str:
    """Compute and reserve the next ``<base>-N`` id; mutates ``tracker``.

    Used when ``on_duplicate_doc_id="suffix"`` to actually take the id for the
    duplicate row.
    """
    candidate, count = _compute_next_unique_doc_id(base_doc_id, tracker)
    tracker.seen[candidate] = tracker.seen.get(base_doc_id, 0)
    tracker.counts[base_doc_id] = count
    return candidate


def parse_budget(value: str | None) -> int | float | str | None:
    cleaned = clean_cell(value).replace(",", "")
    if not cleaned:
        return None
    try:
        parsed = float(cleaned)
    except ValueError:
        return clean_cell(value)
    if parsed.is_integer():
        return int(parsed)
    return parsed


def clean_cell(value: str | None) -> str:
    return str(value or "").strip()


def normalize_body_text(value: str | None) -> str:
    return clean_cell(value).replace("\r\n", "\n").replace("\r", "\n")


def build_ingestion_report(
    *,
    metadata_csv: Path,
    files_dir: Path,
    records: list[IngestionRecord],
    indexed_count: int,
    on_duplicate_doc_id: str,
) -> dict[str, Any]:
    """Build the canonical ingestion_report.json payload."""
    (
        failure_reasons,
        failure_examples,
        file_formats,
        duplicate_groups,
        text_source_counts,
        fallback_reasons,
    ) = _collect_record_buckets(records)
    doc_id_sources: dict[str, int] = OrderedDict()
    for record in records:
        if record.status == "indexed":
            source = "notice_id" if _looks_like_notice_id_doc(record) else "file_name"
            doc_id_sources[source] = doc_id_sources.get(source, 0) + 1

    summary = {
        "schema_version": INGESTION_REPORT_SCHEMA_VERSION,
        "total_rows": len(records),
        "indexed_documents": indexed_count,
        "failed_rows": sum(1 for record in records if record.status == "failed"),
        "failure_reasons": dict(failure_reasons),
        "failure_examples": {k: v for k, v in failure_examples.items()},
        "doc_id_sources": dict(doc_id_sources),
        "file_formats": dict(file_formats),
        "duplicate_doc_ids": {k: sorted(set(v)) for k, v in duplicate_groups.items()},
        "on_duplicate_doc_id": on_duplicate_doc_id,
        # Issue #715 — see ``_collect_record_buckets`` docstring. These two
        # keys are additive (v3 schema bump); v2 readers ignore them via
        # ``dict.get``.
        "text_source_counts": {fmt: dict(sources) for fmt, sources in text_source_counts.items()},
        "fallback_reasons": dict(fallback_reasons),
    }
    return {
        "metadata_csv": str(metadata_csv),
        "files_dir": str(files_dir),
        "summary": summary,
        "failure_taxonomy": FAILURE_TAXONOMY,
        "records": [_record_to_dict(record) for record in records],
    }


def _collect_record_buckets(
    records: list[IngestionRecord],
) -> tuple[
    dict[str, int],
    dict[str, list[dict[str, Any]]],
    dict[str, int],
    dict[str, list[int]],
    dict[str, dict[str, int]],
    dict[str, int],
]:
    """Accumulate the six shared report-building buckets over ``records``.

    Returns ``(failure_reasons, failure_examples, file_formats, duplicate_groups,
    text_source_counts, fallback_reasons)``. Both :func:`build_ingestion_report`
    and :func:`_build_validation_report` call this helper so the identical
    accumulation logic lives in one place.

    The last two buckets were added in issue #715:

    - ``text_source_counts``: ``{file_format: {text_source: count}}`` — answers
      "for HWP rows, how many went through the native pyhwp loader versus the
      CSV-text fallback?". Records whose loader never ran (row-validation
      failures upstream of ``loader.load_text``) contribute ``None`` under
      ``text_source``; we drop those so the histogram only counts rows that
      actually reached a loader.
    - ``fallback_reasons``: ``{reason_string: count}`` — frequency table of
      ``HwpLoader.last_fallback_reason`` values. ``None`` is dropped.
    """
    failure_reasons: dict[str, int] = OrderedDict()
    failure_examples: dict[str, list[dict[str, Any]]] = OrderedDict()
    file_formats: dict[str, int] = OrderedDict()
    duplicate_groups: dict[str, list[int]] = OrderedDict()
    text_source_counts: dict[str, dict[str, int]] = OrderedDict()
    fallback_reasons: dict[str, int] = OrderedDict()

    for record in records:
        if record.reason:
            failure_reasons[record.reason] = failure_reasons.get(record.reason, 0) + 1
            examples = failure_examples.setdefault(record.reason, [])
            if len(examples) < 3:
                examples.append(
                    {
                        "row_number": record.row_number,
                        "doc_id": record.doc_id,
                        "file_name": record.file_name,
                        "file_format": record.file_format,
                    }
                )
        fmt = record.file_format or "unknown"
        file_formats[fmt] = file_formats.get(fmt, 0) + 1
        _accumulate_duplicate_group(duplicate_groups, record)
        if record.text_source:
            per_format = text_source_counts.setdefault(fmt, OrderedDict())
            per_format[record.text_source] = per_format.get(record.text_source, 0) + 1
        if record.fallback_reason:
            fallback_reasons[record.fallback_reason] = (
                fallback_reasons.get(record.fallback_reason, 0) + 1
            )

    return (
        failure_reasons,
        failure_examples,
        file_formats,
        duplicate_groups,
        text_source_counts,
        fallback_reasons,
    )


def _accumulate_duplicate_group(
    duplicate_groups: dict[str, list[int]],
    record: IngestionRecord,
) -> None:
    """Add a record to ``duplicate_groups`` keyed by base_doc_id when applicable."""
    if not record.duplicate_resolution:
        return
    base = str(record.duplicate_resolution.get("base_doc_id") or record.doc_id or "")
    if not base:
        return
    duplicate_groups.setdefault(base, [])
    duplicate_groups[base].append(record.row_number)
    first_seen = record.duplicate_resolution.get("first_seen_row")
    if isinstance(first_seen, int) and first_seen not in duplicate_groups[base]:
        duplicate_groups[base].append(first_seen)


def _looks_like_notice_id_doc(record: IngestionRecord) -> bool:
    if not record.doc_id or not record.file_name:
        return True
    stem_slug = slug_part(Path(record.file_name).stem)
    return record.doc_id != stem_slug


def _record_to_dict(record: IngestionRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["messages"] = list(record.messages)
    if record.duplicate_resolution is None:
        payload.pop("duplicate_resolution", None)
    return payload


def validate_data_list_csv(
    metadata_csv: Path,
    files_dir: Path,
    *,
    on_duplicate_doc_id: str = "fail",
) -> dict[str, Any]:
    """Lightweight schema/audit pass over data_list.csv.

    Mirrors the per-row checks of :func:`load_documents_from_metadata_csv`
    but does not load body text or build documents. Returns a report
    structurally compatible with ``ingestion_report.json``.
    """
    if on_duplicate_doc_id not in {"fail", "suffix"}:
        raise ValueError(
            "on_duplicate_doc_id must be 'fail' or 'suffix'; got: "
            f"{on_duplicate_doc_id}"
        )
    if not metadata_csv.exists():
        raise ValueError(f"metadata_csv does not exist: {metadata_csv}")
    if not metadata_csv.is_file():
        raise ValueError(f"metadata_csv must be a file: {metadata_csv}")
    if not files_dir.exists():
        raise ValueError(f"files_dir does not exist: {files_dir}")
    if not files_dir.is_dir():
        raise ValueError(f"files_dir must be a directory: {files_dir}")

    schema_issues: list[ValidationIssue] = []
    records: list[IngestionRecord] = []
    tracker = _DuplicateTracker()

    with metadata_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        for column in missing:
            schema_issues.append(
                ValidationIssue(
                    code="missing_required_column",
                    field=column,
                    message=f"required column missing: {column}",
                )
            )
        if missing:
            return _build_validation_report(
                metadata_csv=metadata_csv,
                files_dir=files_dir,
                records=records,
                schema_issues=schema_issues,
                on_duplicate_doc_id=on_duplicate_doc_id,
            )
        for row_number, row in enumerate(reader, start=2):
            record = audit_metadata_row(
                row,
                row_number,
                files_dir,
                tracker,
                on_duplicate_doc_id=on_duplicate_doc_id,
            )
            records.append(record)

    return _build_validation_report(
        metadata_csv=metadata_csv,
        files_dir=files_dir,
        records=records,
        schema_issues=schema_issues,
        on_duplicate_doc_id=on_duplicate_doc_id,
    )


def audit_metadata_row(
    row: dict[str, str],
    row_number: int,
    files_dir: Path,
    tracker: _DuplicateTracker,
    *,
    on_duplicate_doc_id: str = "fail",
) -> IngestionRecord:
    # Track non-fatal warnings on fields ingestion accepts but downstream
    # eval often relies on. Blank body text is NOT a warning: the ingestion
    # path raises ``empty_text`` for that row, and the validator must
    # report the same failure so a clean validator exit code can be trusted.
    messages: list[str] = []
    if not clean_cell(row.get("발주 기관")):
        messages.append("blank_agency")
    if not clean_cell(row.get("사업명")):
        messages.append("blank_project")

    validation = _resolve_row_validation(
        row, row_number, files_dir, tracker, on_duplicate_doc_id=on_duplicate_doc_id
    )

    # audit-only: after a clean tracker registration, a blank body text
    # surfaces as ``empty_text`` so a clean validator exit code mirrors
    # the ingestion path's runtime failure for the same row.
    if (
        validation.tracker_registered
        and validation.failure_reason is None
        and not clean_cell(row.get("텍스트"))
    ):
        validation.failure_reason = "empty_text"

    return make_record(
        row_number,
        "failed" if validation.failure_reason else "ok",
        validation.doc_id,
        validation.file_name,
        validation.file_format,
        validation.source_path,
        validation.failure_reason,
        duplicate_resolution=validation.duplicate_resolution,
        messages=tuple(messages),
    )


def _build_validation_report(
    *,
    metadata_csv: Path,
    files_dir: Path,
    records: list[IngestionRecord],
    schema_issues: list[ValidationIssue],
    on_duplicate_doc_id: str,
) -> dict[str, Any]:
    (
        failure_reasons,
        failure_examples,
        file_formats,
        duplicate_groups,
        text_source_counts,
        fallback_reasons,
    ) = _collect_record_buckets(records)
    blank_field_counts: dict[str, int] = OrderedDict()
    for record in records:
        for message in record.messages:
            blank_field_counts[message] = blank_field_counts.get(message, 0) + 1

    ok_count = sum(1 for record in records if record.status == "ok")
    failed_count = sum(1 for record in records if record.status == "failed")
    schema_ok = not schema_issues
    summary = {
        "schema_version": INGESTION_REPORT_SCHEMA_VERSION,
        "schema_ok": schema_ok,
        "total_rows": len(records),
        "ok_rows": ok_count,
        "failed_rows": failed_count,
        "failure_reasons": dict(failure_reasons),
        "failure_examples": {k: v for k, v in failure_examples.items()},
        "blank_field_warnings": dict(blank_field_counts),
        "file_formats": dict(file_formats),
        "duplicate_doc_ids": {k: sorted(set(v)) for k, v in duplicate_groups.items()},
        "on_duplicate_doc_id": on_duplicate_doc_id,
        # Issue #715 — text source + fallback histograms (validation mode
        # never actually calls a loader, so both buckets stay empty in
        # practice; we still expose the keys for schema parity with
        # ``build_ingestion_report``).
        "text_source_counts": {fmt: dict(sources) for fmt, sources in text_source_counts.items()},
        "fallback_reasons": dict(fallback_reasons),
    }
    return {
        "mode": "validation",
        "metadata_csv": str(metadata_csv),
        "files_dir": str(files_dir),
        "summary": summary,
        "schema_issues": [asdict(issue) for issue in schema_issues],
        "failure_taxonomy": FAILURE_TAXONOMY,
        "records": [_record_to_dict(record) for record in records],
    }
