#!/usr/bin/env python3
"""CLI entrypoint for the trajectory-rationality judge (ADR 0056).

Reads an ``eval_summary.json``, loads each case's trace JSON, scores the
three rationality axes, and writes (a) a gitignored per-case payload
plus (b) a committable aggregate JSON and (c) a Markdown summary.

Example::

    python3 scripts/run_rationality_judge.py \\
        --eval-summary reports/real100/eval_summary.json \\
        --output reports/real100/rationality.local.json \\
        --out-aggregate reports/real100/rationality.aggregate.json \\
        --out-md reports/real100/rationality.md \\
        --backend stub

The backend defaults to ``stub`` (zero cost, deterministic).  Use
``--backend openai_compatible`` with the standard judge env vars
(``BIDMATE_JUDGE_API_KEY`` / ``BIDMATE_JUDGE_MODEL`` /
``BIDMATE_JUDGE_BASE_URL``) for real LLM scoring.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from eval.judges.rationality_judge import (  # noqa: E402
    DEFAULT_CACHE_DIR,
    DEFAULT_TOKEN_BUDGET,
    judge_rationality,
    render_markdown,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--eval-summary",
        required=True,
        help="Path to reports/.../eval_summary.json (input).",
    )
    ap.add_argument(
        "--output",
        required=True,
        help=(
            "Where to write the per-case rationality payload (gitignored "
            "by convention — under reports/real100/* aggregate-allowlist)."
        ),
    )
    ap.add_argument(
        "--out-aggregate",
        required=True,
        help="Where to write the committable aggregate JSON (mean + CI per axis).",
    )
    ap.add_argument(
        "--out-md",
        required=True,
        help="Where to write the Markdown summary (bottom-3 per axis).",
    )
    ap.add_argument(
        "--backend",
        default=os.environ.get("BIDMATE_RATIONALITY_BACKEND", "stub"),
        choices=["stub", "openai_compatible"],
        help="Judge backend (defaults to BIDMATE_RATIONALITY_BACKEND or 'stub').",
    )
    ap.add_argument(
        "--traces-dir",
        default=None,
        help=(
            "Optional override base directory for per-case trace JSON files. "
            "If omitted, the trace_path in each case is resolved relative to "
            "the repo root."
        ),
    )
    ap.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help="Per-case verdict cache directory (gitignored, reserved for LLM backend).",
    )
    ap.add_argument(
        "--token-budget",
        type=int,
        default=int(
            os.environ.get("BIDMATE_RATIONALITY_TOKEN_BUDGET", DEFAULT_TOKEN_BUDGET)
        ),
        help=f"Input-token estimate budget per run (default {DEFAULT_TOKEN_BUDGET}).",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    eval_path = Path(args.eval_summary)
    if not eval_path.exists():
        print(f"[ERROR] Eval summary not found: {eval_path}", file=sys.stderr)
        return 2
    summary = json.loads(eval_path.read_text(encoding="utf-8"))
    try:
        local_payload, aggregate = judge_rationality(
            summary,
            backend=args.backend,
            traces_dir=Path(args.traces_dir) if args.traces_dir else None,
            cache_dir=Path(args.cache_dir),
            token_budget=args.token_budget,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    out_local = Path(args.output)
    out_local.parent.mkdir(parents=True, exist_ok=True)
    out_local.write_text(
        json.dumps(local_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Per-case payload: {out_local}")

    out_agg = Path(args.out_aggregate)
    out_agg.parent.mkdir(parents=True, exist_ok=True)
    out_agg.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] Aggregate: {out_agg}")

    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_markdown(aggregate, local_payload), encoding="utf-8")
    print(f"[OK] Markdown: {out_md}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
