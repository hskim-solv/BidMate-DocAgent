#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys

SAMPLE_DOCS = [
    {"id": "doc-1", "title": "기관 A RFP", "text": "기관 A는 AI 품질관리와 보안 통제를 요구합니다."},
    {"id": "doc-2", "title": "기관 B RFP", "text": "기관 B는 데이터 거버넌스와 MLOps 자동화를 강조합니다."},
    {"id": "doc-3", "title": "공통 제출조건", "text": "두 기관 모두 일정 준수와 산출물 표준을 요구합니다."},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build sample index artifacts for the public repository snapshot."
    )
    parser.add_argument("--input_dir", required=True, help="Path to raw input documents directory.")
    parser.add_argument("--output_dir", required=True, help="Path to write built index.")
    parser.add_argument("--query", default=None, help="Unused in this command; accepted for CLI consistency.")
    parser.add_argument("--config", default=None, help="Unused in this command; accepted for CLI consistency.")
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
    except Exception as exc:
        print(f"[ERROR] Argument parsing/validation failed: {exc}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    index_payload = {
        "mode": "sample",
        "message": "현재 공개 레포에서는 샘플 모드만 지원",
        "documents": SAMPLE_DOCS,
    }
    out_path = output_dir / "index.json"
    out_path.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Sample index written: {out_path}")

    if args.query or args.config:
        print("[INFO] --query/--config are accepted for interface consistency but unused here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
