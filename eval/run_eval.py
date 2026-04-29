#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run sample evaluation.")
    parser.add_argument("--input_dir", default="outputs", help="Directory containing answer.json.")
    parser.add_argument("--output_dir", default="reports", help="Directory to save eval summary.")
    parser.add_argument("--query", default=None, help="Unused in this command; accepted for CLI consistency.")
    parser.add_argument("--config", required=True, help="Path to eval config JSON/YAML-like file.")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    config_path = Path(args.config)
    if not config_path.exists():
        raise ValueError(f"--config does not exist: {config_path}")

    answer_path = Path(args.input_dir) / "answer.json"
    if not answer_path.exists():
        raise ValueError(f"Input answer file not found: {answer_path}. Run app.py first.")


def main() -> int:
    try:
        args = parse_args()
        validate_args(args)
    except Exception as exc:
        print(f"[ERROR] Argument parsing/validation failed: {exc}", file=sys.stderr)
        return 2

    answer_path = Path(args.input_dir) / "answer.json"
    answer = json.loads(answer_path.read_text(encoding="utf-8"))

    if answer.get("mode") != "sample":
        raise NotImplementedError("현재 공개 레포에서는 샘플 모드만 지원")

    summary = {
        "mode": "sample",
        "config": args.config,
        "num_predictions": 1,
        "accuracy": None,
        "groundedness": None,
        "abstention": None,
        "latency": {"p50": None, "p95": None},
        "retry": None,
        "missing_key_policy": "필수 키 누락 시 null로 채움",
        "note": "현재 공개 레포에서는 샘플 모드만 지원",
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "eval_summary.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Eval summary written: {out_path}")

    if args.query:
        print("[INFO] --query is accepted for interface consistency but unused here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
