#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run sample QA against sample index.")
    parser.add_argument("--input_dir", default="data/index", help="Directory containing index.json.")
    parser.add_argument("--output_dir", default="outputs", help="Directory to save answer JSON.")
    parser.add_argument("--query", required=True, help="User query string.")
    parser.add_argument("--config", default=None, help="Unused in this command; accepted for CLI consistency.")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    index_path = Path(args.input_dir) / "index.json"
    if not index_path.exists():
        raise ValueError(
            f"Sample index not found: {index_path}. Run scripts/build_index.py first."
        )
    if not args.query.strip():
        raise ValueError("--query must be a non-empty string.")


def sample_answer(query: str, docs: list[dict]) -> dict:
    evidence = [{"id": d["id"], "title": d["title"]} for d in docs[:2]]
    return {
        "mode": "sample",
        "query": query,
        "answer": "현재 공개 레포에서는 샘플 모드만 지원하며, 더미 근거 기반 응답입니다.",
        "evidence": evidence,
    }


def main() -> int:
    try:
        args = parse_args()
        validate_args(args)
    except Exception as exc:
        print(f"[ERROR] Argument parsing/validation failed: {exc}", file=sys.stderr)
        return 2

    index_path = Path(args.input_dir) / "index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))

    if payload.get("mode") != "sample":
        raise NotImplementedError("현재 공개 레포에서는 샘플 모드만 지원")

    answer = sample_answer(args.query, payload.get("documents", []))
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
