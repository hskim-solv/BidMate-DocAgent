#!/usr/bin/env python3
"""Safe wrapper for the private Naive RAG real-eval run.

The wrapper validates readiness first, writes all runtime artifacts under the
gitignored private output directory, and delegates execution to the existing
Naive RAG evaluation contract only when the local private inputs are present.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import sys
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "scripts"))

from check_private_real_eval_readiness import assess_readiness  # noqa: E402
from eval.naive_rag.run_eval import run_from_config  # noqa: E402


def _repo_path(value: str | Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT_DIR / path


def _load_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("private real-eval config root must be a mapping")
    return payload


def _default_run_id() -> str:
    return "private_real_eval_naive_rag_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _runtime_contract(config: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": "private_real_eval_naive_rag",
        "description": "Private real-eval Naive RAG runtime config. Raw artifact; keep gitignored.",
        "eval_type": "private_real_eval",
        "benchmark_type": "private_real_eval",
        "baseline_system": "naive_rag",
        "run_id": run_id,
        "index_dir": str(config["index_dir"]),
        "questions_path": str(config["questions_path"]),
        "gold_evidence_path": str(config["gold_evidence_path"]),
        "output_root": str(config["output_dir"]),
        "pipeline": {
            "name": "naive_baseline",
            "top_k": int(config.get("top_k") or 10),
            "retrieval_mode": "flat",
            "retrieval_backend": "dense",
            "metadata_first": False,
            "rerank": False,
            "verifier_retry": False,
            "query_expansion": "identity",
            "prompt_profile": "minimal_grounded_extractive",
            "bm25_tokenizer": "regex",
            "bm25_backend": "okapi",
        },
        "metrics": config.get("metrics") or {},
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="eval/real_config.local.yaml")
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run readiness validation and stop before executing the baseline.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = _repo_path(args.config)
    report = assess_readiness(config_path)
    print(f"Private real-eval readiness verdict: {report.verdict_label}")
    if not report.ready_to_run:
        print("Private Naive RAG baseline was not run. Blockers:")
        for blocker in report.blockers:
            print(f"- {blocker}")
        print("No private raw output was written.")
        return 1
    if args.validate_only:
        print("Readiness passed; validate-only requested, so no private run was executed.")
        return 0

    try:
        config = _load_config(config_path)
        run_id = args.run_id or _default_run_id()
        output_root = _repo_path(str(config["output_dir"]))
        runtime_dir = output_root / "_runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runtime_config = runtime_dir / f"{run_id}.yaml"
        runtime_config.write_text(
            yaml.safe_dump(_runtime_contract(config, run_id), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        run_dir = run_from_config(runtime_config, output_root_override=output_root, run_id_override=run_id)
    except Exception as exc:
        print(f"[ERROR] private Naive RAG eval failed before completion: {exc}", file=sys.stderr)
        return 2

    marker = run_dir / "PRIVATE_REAL_EVAL_README.txt"
    marker.write_text(
        "\n".join(
            [
                "private_real_eval / naive_rag",
                "This directory may contain raw private questions, answers, evidence, and retrieved chunks.",
                "Keep it gitignored. Export only redacted aggregate summaries.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print("Private real-eval / naive_rag run completed.")
    print("Raw artifacts were written under the configured gitignored output_dir.")
    print("No performance-improvement claim is implied by this run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

