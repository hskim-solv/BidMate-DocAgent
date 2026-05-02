#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ingestion import load_documents_from_metadata_csv
from rag_core import (
    DEFAULT_CHUNK_MAX_CHARS,
    DEFAULT_CHUNK_OVERLAP_SENTENCES,
    DEFAULT_EMBEDDING_MODEL,
    build_index_payload,
    build_index_payload_from_documents,
)
from visual_ingestion import (
    load_visual_documents_from_dir,
    load_visual_documents_from_metadata_csv,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local dense RAG index from synthetic or CSV-backed PDF/HWP RFP documents."
    )
    parser.add_argument("--input_dir", default=None, help="Path to raw JSON/Markdown/Text documents.")
    parser.add_argument(
        "--visual_input_dir",
        default=None,
        help="Path to original PDF/image documents for visual parsing v2.",
    )
    parser.add_argument(
        "--metadata_csv",
        default=None,
        help="Path to data_list.csv for PDF/HWP ingestion. Uses the CSV text column in v1.",
    )
    parser.add_argument(
        "--files_dir",
        default=None,
        help="Directory containing PDF/HWP files referenced by --metadata_csv.",
    )
    parser.add_argument(
        "--ingestion_mode",
        default="csv-text",
        choices=["csv-text", "visual"],
        help="Use CSV text v1 or visual parsing v2 when --metadata_csv is provided.",
    )
    parser.add_argument(
        "--visual_artifact_dir",
        default=None,
        help="Directory to write visual parsing v2 artifacts. Defaults to <output_dir>/visual_artifacts.",
    )
    parser.add_argument("--output_dir", required=True, help="Path to write index.json.")
    parser.add_argument("--query", default=None, help="Unused in this command; accepted for CLI consistency.")
    parser.add_argument("--config", default=None, help="Unused in this command; accepted for CLI consistency.")
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL, help="SentenceTransformer model name.")
    parser.add_argument(
        "--embedding_backend",
        default="auto",
        choices=["auto", "sentence-transformers", "hashing"],
        help="Use cached sentence-transformers in auto mode; otherwise fall back to deterministic hashing.",
    )
    parser.add_argument(
        "--chunking_strategy",
        default="auto",
        choices=["auto", "section", "fixed"],
        help="Chunk by detected sections in auto mode; use fixed fallback when structure is weak.",
    )
    parser.add_argument(
        "--chunk_max_chars",
        type=int,
        default=DEFAULT_CHUNK_MAX_CHARS,
        help="Maximum characters per child chunk.",
    )
    parser.add_argument(
        "--chunk_overlap_sentences",
        type=int,
        default=DEFAULT_CHUNK_OVERLAP_SENTENCES,
        help="Number of trailing sentences to overlap between adjacent chunks.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    using_raw_dir = bool(args.input_dir)
    using_visual_dir = bool(args.visual_input_dir)
    using_metadata_csv = bool(args.metadata_csv)
    if sum([using_raw_dir, using_visual_dir, using_metadata_csv]) != 1:
        raise ValueError("Provide exactly one of --input_dir, --visual_input_dir, or --metadata_csv.")

    if using_raw_dir:
        input_dir = Path(args.input_dir)
        if not input_dir.exists():
            raise ValueError(f"--input_dir does not exist: {input_dir}")
        if not input_dir.is_dir():
            raise ValueError(f"--input_dir must be a directory: {input_dir}")

    if using_visual_dir:
        visual_input_dir = Path(args.visual_input_dir)
        if not visual_input_dir.exists():
            raise ValueError(f"--visual_input_dir does not exist: {visual_input_dir}")
        if not visual_input_dir.is_dir():
            raise ValueError(f"--visual_input_dir must be a directory: {visual_input_dir}")

    if using_metadata_csv and not args.files_dir:
        raise ValueError("--files_dir is required when --metadata_csv is provided.")
    if not using_metadata_csv and args.ingestion_mode != "csv-text":
        raise ValueError("--ingestion_mode is only used with --metadata_csv.")
    if args.visual_artifact_dir and not (
        using_visual_dir or (using_metadata_csv and args.ingestion_mode == "visual")
    ):
        raise ValueError("--visual_artifact_dir is only used with visual ingestion.")
    if args.chunk_max_chars < 1:
        raise ValueError("--chunk_max_chars must be positive.")
    if args.chunk_overlap_sentences < 0:
        raise ValueError("--chunk_overlap_sentences must be zero or positive.")


def main() -> int:
    ingestion_report = None
    try:
        args = parse_args()
        validate_args(args)
        output_dir = Path(args.output_dir)
        visual_artifact_dir = (
            Path(args.visual_artifact_dir)
            if args.visual_artifact_dir
            else output_dir / "visual_artifacts"
        )
        if args.metadata_csv:
            if args.ingestion_mode == "visual":
                documents, ingestion_report = load_visual_documents_from_metadata_csv(
                    Path(args.metadata_csv),
                    Path(args.files_dir),
                    visual_artifact_dir,
                )
                message = (
                    "PDF/image visual parsing v2 index with HWP CSV-text fallback "
                    "and page/region metadata."
                )
            else:
                documents, ingestion_report = load_documents_from_metadata_csv(
                    Path(args.metadata_csv),
                    Path(args.files_dir),
                )
                message = "PDF/HWP RFP index built from data_list.csv text and joined metadata."
            payload = build_index_payload_from_documents(
                documents,
                source_dir=str(Path(args.metadata_csv)),
                model_name=args.model,
                embedding_backend=args.embedding_backend,
                chunking_strategy=args.chunking_strategy,
                chunk_max_chars=args.chunk_max_chars,
                chunk_overlap_sentences=args.chunk_overlap_sentences,
                message=message,
            )
        elif args.visual_input_dir:
            documents, ingestion_report = load_visual_documents_from_dir(
                Path(args.visual_input_dir),
                visual_artifact_dir,
            )
            payload = build_index_payload_from_documents(
                documents,
                source_dir=str(Path(args.visual_input_dir)),
                model_name=args.model,
                embedding_backend=args.embedding_backend,
                chunking_strategy=args.chunking_strategy,
                chunk_max_chars=args.chunk_max_chars,
                chunk_overlap_sentences=args.chunk_overlap_sentences,
                message="PDF/image visual parsing v2 index with page/region metadata.",
            )
        else:
            payload = build_index_payload(
                Path(args.input_dir),
                model_name=args.model,
                embedding_backend=args.embedding_backend,
                chunking_strategy=args.chunking_strategy,
                chunk_max_chars=args.chunk_max_chars,
                chunk_overlap_sentences=args.chunk_overlap_sentences,
            )
    except Exception as exc:
        print(f"[ERROR] Index build failed: {exc}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "index.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if ingestion_report is not None:
        report_path = output_dir / "ingestion_report.json"
        report_path.write_text(
            json.dumps(ingestion_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(
        "[OK] RAG index written: "
        f"{out_path} ({payload['build']['num_documents']} docs, "
        f"{payload['build']['num_chunks']} chunks, "
        f"embedding={payload['embedding']['backend']})"
    )
    if ingestion_report is not None:
        print(f"[OK] Ingestion report written: {report_path}")

    if args.query or args.config:
        print("[INFO] --query/--config are accepted for interface consistency but unused here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
