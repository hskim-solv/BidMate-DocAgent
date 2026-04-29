#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag_core import DEFAULT_EMBEDDING_MODEL, build_index_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local dense RAG index from public synthetic RFP documents."
    )
    parser.add_argument("--input_dir", required=True, help="Path to raw JSON/Markdown/Text documents.")
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
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        raise ValueError(f"--input_dir does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise ValueError(f"--input_dir must be a directory: {input_dir}")


def main() -> int:
    try:
        args = parse_args()
        validate_args(args)
        payload = build_index_payload(
            Path(args.input_dir),
            model_name=args.model,
            embedding_backend=args.embedding_backend,
        )
    except Exception as exc:
        print(f"[ERROR] Index build failed: {exc}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "index.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "[OK] RAG index written: "
        f"{out_path} ({payload['build']['num_documents']} docs, "
        f"{payload['build']['num_chunks']} chunks, "
        f"embedding={payload['embedding']['backend']})"
    )

    if args.query or args.config:
        print("[INFO] --query/--config are accepted for interface consistency but unused here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
