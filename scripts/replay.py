#!/usr/bin/env python3
"""Replay a saved RAG trace for a single eval case (or every case in a run).

Reads a ``.trace.json`` produced by ``eval/run_eval.py:write_prediction_trace``
and prints a human-readable summary of the agent's decisions and stage
latencies. Use this when you want to understand why a particular case
landed where it did without re-running the eval.

Usage:
    python3 scripts/replay.py reports/traces/<run>/<case>.trace.json
    python3 scripts/replay.py reports/traces/<run>/      # all cases in a run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _fmt_int_kv(d: dict[str, Any] | None) -> str:
    if not d:
        return "{}"
    return ", ".join(f"{k}={v}" for k, v in d.items())


def _ms(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _print_summary(path: Path, payload: dict[str, Any]) -> None:
    case_id = payload.get("case_id") or path.stem
    run = payload.get("run")
    pipeline = payload.get("pipeline")
    slice_name = payload.get("slice")
    query = payload.get("query", "")
    status = payload.get("answer_status")
    trace = payload.get("trace") or {}

    print(f"\nCASE {case_id}  [run={run}  pipeline={pipeline}  slice={slice_name}]")
    print(f"QUERY:  {query}")
    print(f"STATUS: {status}")

    rewrite = trace.get("query_rewrite") or {}
    if rewrite:
        conf = rewrite.get("context_resolution_confidence")
        conf_s = f"{float(conf):.2f}" if conf is not None else "n/a"
        print("\nQUERY REWRITE")
        print(f"  type={rewrite.get('rewrite_type')!r}  rewritten={rewrite.get('rewritten')}")
        print(
            "  context: "
            f"source={rewrite.get('context_source')!r}  "
            f"status={rewrite.get('context_status')!r}  "
            f"conf={conf_s}"
        )

    planner = trace.get("planner") or {}
    if planner:
        print("\nPLANNER")
        print(
            "  query_type="
            f"{planner.get('query_type')!r}  "
            f"retrieval_mode={planner.get('retrieval_mode')!r}"
        )
        print(
            "  metadata_first="
            f"{planner.get('metadata_first')}  "
            f"rerank={planner.get('rerank')}  "
            f"verifier_retry={planner.get('verifier_retry')}"
        )
        print(
            "  stage_sequence="
            f"{planner.get('stage_sequence')}  "
            f"selected_stage={planner.get('selected_stage')!r}  "
            f"top_k={planner.get('selected_top_k')}"
        )

        cov = planner.get("comparison_coverage") or {}
        if cov:
            print(
                "  comparison_coverage: "
                f"after={{{_fmt_int_kv(cov.get('after'))}}}  "
                f"balanced={cov.get('balanced')}  "
                f"min_per_target={cov.get('min_per_target')}"
            )

        lat = planner.get("stage_latencies_ms") or {}
        if lat:
            print("\nSTAGE LATENCIES (ms)")
            for k, v in lat.items():
                print(f"  {k}={_ms(v)}")

        attempts = planner.get("attempts") or []
        if attempts:
            print(f"\nATTEMPTS ({len(attempts)}):")
            for i, attempt in enumerate(attempts, start=1):
                reasons = attempt.get("verification_reasons") or []
                print(
                    f"  [{i}] stage={attempt.get('stage')!r}  "
                    f"top_k={attempt.get('top_k')}  "
                    f"verified={attempt.get('verified')}  "
                    f"reasons={reasons}"
                )


def _collect_files(target: Path) -> list[Path]:
    if target.is_dir():
        return sorted(target.rglob("*.trace.json"))
    if target.is_file():
        return [target]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pretty-print saved RAG trace(s) for offline replay."
    )
    parser.add_argument(
        "target",
        help="Path to a .trace.json file OR a directory containing them",
    )
    args = parser.parse_args(argv)

    target = Path(args.target)
    files = _collect_files(target)
    if not files:
        print(f"No .trace.json found at: {target}", file=sys.stderr)
        return 1

    for file in files:
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[skip] {file}: {exc}", file=sys.stderr)
            continue
        _print_summary(file, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
