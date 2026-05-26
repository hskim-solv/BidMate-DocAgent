#!/usr/bin/env python3
"""Parallel private real100_v2 index builder.

This is a local-only helper for the real100_v2 benchmark rebuild. It preserves
the existing retrieval/verifier/prompt/chunking/reranker/answer runtime paths:
documents are parsed in parallel, then handed to the existing index payload
builder and writer.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.scorers.chunk_health import compute_chunk_health  # noqa: E402
from ingestion import (  # noqa: E402
    HWP_PDF_ARTIFACT_DIR_ENV,
    IngestionRecord,
    _DuplicateTracker,
    _reset_kordoc_loaders,
    _resolve_row_validation,
    build_ingestion_report,
    load_documents_from_metadata_csv,
    make_record,
    normalize_ingestion_row,
    validate_fieldnames,
)
from rag_core import (  # noqa: E402
    DEFAULT_CHUNK_MAX_CHARS,
    DEFAULT_CHUNK_OVERLAP_SENTENCES,
    EMBEDDINGS_FILENAME,
    build_index_payload_from_documents,
    write_index,
)
from rag_embedding import DEFAULT_EMBEDDING_MODEL  # noqa: E402


CHECKPOINT_SCHEMA_VERSION = 1


def _load_rows(metadata_csv: Path) -> list[dict[str, str]]:
    with metadata_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        validate_fieldnames(reader.fieldnames or [], metadata_csv)
        return list(reader)


def _worker_normalize(row_number: int, row: dict[str, str], files_dir: str) -> tuple[int, dict[str, Any] | None, IngestionRecord]:
    _reset_kordoc_loaders()
    document, record = normalize_ingestion_row(
        row,
        row_number,
        Path(files_dir),
        _DuplicateTracker(),
        on_duplicate_doc_id="fail",
    )
    return row_number, document, record


def _row_fingerprint(row: dict[str, str]) -> str:
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _checkpoint_path(checkpoint_dir: Path, row_number: int) -> Path:
    return checkpoint_dir / f"row_{row_number:06d}.json"


def _record_from_dict(payload: dict[str, Any]) -> IngestionRecord:
    return IngestionRecord(**payload)


def _read_checkpoint(
    checkpoint_dir: Path,
    row_number: int,
    row_fingerprint: str,
) -> tuple[int, dict[str, Any] | None, IngestionRecord] | None:
    path = _checkpoint_path(checkpoint_dir, row_number)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        return None
    if payload.get("row_number") != row_number:
        return None
    if payload.get("row_fingerprint") != row_fingerprint:
        return None
    record_payload = payload.get("record")
    if not isinstance(record_payload, dict):
        return None
    document = payload.get("document")
    if document is not None and not isinstance(document, dict):
        return None
    try:
        record = _record_from_dict(record_payload)
    except TypeError:
        return None
    return row_number, document, record


def _write_checkpoint(
    checkpoint_dir: Path,
    row_number: int,
    row_fingerprint: str,
    document: dict[str, Any] | None,
    record: IngestionRecord,
) -> None:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    path = _checkpoint_path(checkpoint_dir, row_number)
    tmp_path = path.with_suffix(".tmp")
    payload = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "row_number": row_number,
        "row_fingerprint": row_fingerprint,
        "document": document,
        "record": asdict(record),
    }
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def parallel_load_documents_from_metadata_csv(
    metadata_csv: Path,
    files_dir: Path,
    *,
    workers: int,
    checkpoint_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if workers < 1:
        raise ValueError("workers must be >= 1")
    if not metadata_csv.is_file():
        raise ValueError(f"--metadata_csv must be a file: {metadata_csv}")
    if not files_dir.is_dir():
        raise ValueError(f"--files_dir must be a directory: {files_dir}")

    rows = _load_rows(metadata_csv)
    tracker = _DuplicateTracker()
    records_by_row: dict[int, IngestionRecord] = {}
    tasks: list[tuple[int, dict[str, str]]] = []
    row_fingerprints: dict[int, str] = {}
    documents_by_row: dict[int, dict[str, Any]] = {}
    cached = 0

    for row_number, row in enumerate(rows, start=2):
        validation = _resolve_row_validation(row, row_number, files_dir, tracker)
        if validation.failure_reason:
            records_by_row[row_number] = make_record(
                row_number,
                "failed",
                validation.doc_id,
                validation.file_name,
                validation.file_format,
                validation.source_path,
                validation.failure_reason,
                duplicate_resolution=validation.duplicate_resolution,
            )
            continue
        row_fingerprint = _row_fingerprint(row)
        row_fingerprints[row_number] = row_fingerprint
        if checkpoint_dir is not None:
            checkpoint = _read_checkpoint(checkpoint_dir, row_number, row_fingerprint)
            if checkpoint is not None:
                _cached_row_number, document, record = checkpoint
                records_by_row[row_number] = record
                if document is not None:
                    documents_by_row[row_number] = document
                cached += 1
                continue
        tasks.append((row_number, row))

    completed = 0
    started = time.monotonic()
    total_parse_rows = cached + len(tasks)
    if cached:
        print(
            "[PROGRESS] parallel parse:",
            f"cached={cached}",
            f"pending={len(tasks)}",
            f"indexed={sum(1 for record in records_by_row.values() if record.status == 'indexed')}",
            f"failed={sum(1 for record in records_by_row.values() if record.status == 'failed')}",
            flush=True,
        )
    if tasks:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_worker_normalize, row_number, row, str(files_dir)): row_number
                for row_number, row in tasks
            }
            for future in as_completed(futures):
                row_number, document, record = future.result()
                records_by_row[row_number] = record
                if document is not None:
                    documents_by_row[row_number] = document
                if checkpoint_dir is not None:
                    _write_checkpoint(
                        checkpoint_dir,
                        row_number,
                        row_fingerprints[row_number],
                        document,
                        record,
                    )
                completed += 1
                if completed == len(tasks) or completed % max(1, workers) == 0:
                    indexed = sum(1 for record in records_by_row.values() if record.status == "indexed")
                    failed = sum(1 for record in records_by_row.values() if record.status == "failed")
                    elapsed_s = time.monotonic() - started
                    avg_s = elapsed_s / completed if completed else 0.0
                    print(
                        "[PROGRESS] parallel parse:",
                        f"completed={cached + completed}/{total_parse_rows}",
                        f"cached={cached}",
                        f"indexed={indexed}",
                        f"failed={failed}",
                        f"elapsed_s={elapsed_s:.1f}",
                        f"avg_s_per_completed={avg_s:.1f}",
                        flush=True,
                    )

    records = [records_by_row[row_number] for row_number in sorted(records_by_row)]
    documents = [documents_by_row[row_number] for row_number in sorted(documents_by_row)]
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
        on_duplicate_doc_id="fail",
    )
    return documents, report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata_csv", type=Path, required=True)
    parser.add_argument("--files_dir", type=Path, required=True)
    parser.add_argument("--output_dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2) // 2)))
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument(
        "--embedding_backend",
        default="hashing",
        choices=["auto", "sentence-transformers", "hashing", "openai"],
    )
    parser.add_argument("--chunking_strategy", default="fixed", choices=["auto", "section", "fixed"])
    parser.add_argument("--chunk_max_chars", type=int, default=DEFAULT_CHUNK_MAX_CHARS)
    parser.add_argument("--chunk_overlap_sentences", type=int, default=DEFAULT_CHUNK_OVERLAP_SENTENCES)
    parser.add_argument("--hwp_loader", default="pdf_pymupdf4llm", choices=["csv_text", "kordoc", "pdf_pymupdf4llm"])
    parser.add_argument("--pdf_loader", default="pdf_pymupdf4llm", choices=["csv_text", "kordoc", "pdf_pymupdf4llm"])
    parser.add_argument("--hwp_pdf_artifact_dir", type=Path, required=True)
    parser.add_argument(
        "--checkpoint_dir",
        type=Path,
        default=None,
        help="Private raw parse checkpoint directory. Defaults to OUTPUT_DIR/_parse_checkpoints.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        os.environ["BIDMATE_HWP_LOADER"] = args.hwp_loader
        os.environ["BIDMATE_PDF_LOADER"] = args.pdf_loader
        os.environ[HWP_PDF_ARTIFACT_DIR_ENV] = str(args.hwp_pdf_artifact_dir)
        print(
            "[CONFIG] private real100_v2 parallel build:",
            f"workers={args.workers}",
            f"hwp_loader={args.hwp_loader}",
            f"pdf_loader={args.pdf_loader}",
            f"embedding={args.embedding_backend}",
            flush=True,
        )
        checkpoint_dir = args.checkpoint_dir or (args.output_dir / "_parse_checkpoints")
        if args.workers == 1:
            documents, ingestion_report = load_documents_from_metadata_csv(args.metadata_csv, args.files_dir)
        else:
            documents, ingestion_report = parallel_load_documents_from_metadata_csv(
                args.metadata_csv,
                args.files_dir,
                workers=args.workers,
                checkpoint_dir=checkpoint_dir,
            )
        payload = build_index_payload_from_documents(
            documents,
            source_dir=str(args.metadata_csv),
            model_name=args.model,
            embedding_backend=args.embedding_backend,
            chunking_strategy=args.chunking_strategy,
            chunk_max_chars=args.chunk_max_chars,
            chunk_overlap_sentences=args.chunk_overlap_sentences,
            message="Private real100_v2 parallel PyMuPDF4LLM RFP index.",
        )
        chunk_health = compute_chunk_health(payload.get("chunks") or [])
        ingestion_report.setdefault("summary", {})["chunk_health"] = chunk_health
        args.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = write_index(payload, args.output_dir)
        report_path = args.output_dir / "ingestion_report.json"
        report_path.write_text(
            json.dumps(ingestion_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"[ERROR] private real100_v2 parallel build failed: {exc}", file=sys.stderr)
        return 2

    print(
        "[OK] private real100_v2 index written:",
        f"{out_path}",
        f"(+ {EMBEDDINGS_FILENAME})",
        f"docs={payload['build']['num_documents']}",
        f"chunks={payload['build']['num_chunks']}",
        f"report={report_path}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
