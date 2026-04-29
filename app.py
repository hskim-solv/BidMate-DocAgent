#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys

from rag_core import load_index, run_rag_query


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local RAG QA against a built RFP index.")
    parser.add_argument("--input_dir", default="data/index", help="Directory containing index.json.")
    parser.add_argument("--output_dir", default="outputs", help="Directory to save answer JSON.")
    parser.add_argument("--query", required=True, help="User query string.")
    parser.add_argument("--config", default=None, help="Unused in this command; accepted for CLI consistency.")
    parser.add_argument("--top_k", type=int, default=None, help="Override retrieval top-k.")
    parser.add_argument(
        "--context_entities",
        default="",
        help="Comma-separated entities for follow-up questions, e.g. '기관 A'.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not (Path(args.input_dir) / "index.json").exists():
        raise ValueError(f"RAG index not found in {args.input_dir}. Run scripts/build_index.py first.")
    if not args.query.strip():
        raise ValueError("--query must be a non-empty string.")
    if args.top_k is not None and args.top_k < 1:
        raise ValueError("--top_k must be positive.")


def parse_context_entities(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def main() -> int:
    try:
        args = parse_args()
        validate_args(args)
        index = load_index(Path(args.input_dir))
        answer = run_rag_query(
            index,
            args.query,
            top_k=args.top_k,
            context_entities=parse_context_entities(args.context_entities),
        )
    except Exception as exc:
        print(f"[ERROR] RAG query failed: {exc}", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "answer.json"
    out_path.write_text(json.dumps(answer, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Answer written: {out_path}")

    if args.config:
        print("[INFO] --config is accepted for interface consistency but unused here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
