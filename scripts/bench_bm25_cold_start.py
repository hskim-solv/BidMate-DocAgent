#!/usr/bin/env python3
"""Micro-bench: BM25 lazy-build cost on a prebuilt index (issue #153).

ADR 0007 hybrid retrieval lazy-builds ``BM25Okapi`` over the full chunk
corpus on the first hybrid query (see ``rag_core.get_or_build_bm25``).
This script isolates that build cost so the issue-#153 decision gate
can be applied with real numbers:

  cond 1: bm25 build_ms.p50 ≥ 50 ms (vs dense cold-start)
  cond 2: (dense retrieve_ms.p95 + bm25 build_ms.p50) / total_p95 ≥ 20%

If both pass on a real-data 100-doc corpus, the issue proceeds to a
disk-cached BM25 IDF state. Otherwise it closes.

The script loads ``index.json`` once, then for each rep pops the
BM25 caches (``_bm25_by_profile`` / ``_bm25`` / ``_bm25_chunk_ids``)
and times one fresh ``get_or_build_bm25`` call. A subsequent
``bm25_scores_for_index`` call is timed separately to capture any
``BM25Okapi.get_scores`` one-time overhead beyond construction.

Output JSON is written to the path provided by ``--output`` and a
short human summary is printed to stdout. Output paths under
``reports/real100/`` stay private per ADR 0005.

Usage:
  python scripts/bench_bm25_cold_start.py \
      --index-dir data/index/real100 \
      --reps 10 \
      --output reports/real100/bm25_cold_start_bench.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rag_core import (  # noqa: E402
    bm25_scores_for_index,
    get_or_build_bm25,
    load_index,
    tokenize,
)


DEFAULT_QUERY = "사업 공고 기관 코드"
BM25_CACHE_KEYS = ("_bm25_by_profile", "_bm25", "_bm25_chunk_ids")


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    rank = q * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "p50": 0.0, "p95": 0.0, "mean": 0.0, "max": 0.0}
    return {
        "min": round(min(values), 3),
        "p50": round(_percentile(values, 0.50), 3),
        "p95": round(_percentile(values, 0.95), 3),
        "mean": round(statistics.fmean(values), 3),
        "max": round(max(values), 3),
    }


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT),
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8").strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _clear_bm25_cache(index: dict[str, Any]) -> None:
    for key in BM25_CACHE_KEYS:
        index.pop(key, None)


def run_bench(
    index: dict[str, Any],
    query_tokens: list[str],
    stopword_profile: str,
    reps: int,
) -> tuple[list[float], list[float]]:
    build_ms: list[float] = []
    score_ms: list[float] = []
    for _ in range(reps):
        _clear_bm25_cache(index)
        t0 = time.perf_counter()
        get_or_build_bm25(index, stopword_profile=stopword_profile)
        build_ms.append((time.perf_counter() - t0) * 1000.0)
        t1 = time.perf_counter()
        bm25_scores_for_index(index, query_tokens, stopword_profile=stopword_profile)
        score_ms.append((time.perf_counter() - t1) * 1000.0)
    return build_ms, score_ms


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--index-dir",
        required=True,
        type=Path,
        help="Directory containing index.json + sidecar.",
    )
    ap.add_argument(
        "--reps",
        type=int,
        default=10,
        help="Number of build/score reps (default: 10).",
    )
    ap.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write the JSON summary.",
    )
    ap.add_argument(
        "--stopword-profile",
        default="shared",
        help="BM25 stopword profile (shared | bm25_extra). Default: shared.",
    )
    ap.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help=f"Probe query string for first-score timing (default: {DEFAULT_QUERY!r}).",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if args.reps < 1:
        print("ERROR: --reps must be >= 1", file=sys.stderr)
        return 2
    try:
        index = load_index(args.index_dir)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    query_tokens = tokenize(args.query)
    if not query_tokens:
        print(
            f"ERROR: query {args.query!r} tokenized to empty list",
            file=sys.stderr,
        )
        return 2

    build_ms, score_ms = run_bench(
        index, query_tokens, args.stopword_profile, args.reps
    )

    payload = {
        "index_dir": str(args.index_dir),
        "num_chunks": len(index.get("chunks") or []),
        "num_documents": int((index.get("build") or {}).get("num_documents") or 0),
        "embedding_backend": (index.get("embedding") or {}).get("backend"),
        "stopword_profile": args.stopword_profile,
        "reps": args.reps,
        "query": args.query,
        "query_tokens": query_tokens,
        "build_ms": _summary(build_ms),
        "first_query_score_ms": _summary(score_ms),
        "git_sha": _git_sha(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"BM25 cold-start bench ({payload['num_chunks']} chunks, "
        f"{payload['num_documents']} docs, reps={args.reps})"
    )
    print(
        f"  build_ms:            min={payload['build_ms']['min']:.2f} "
        f"p50={payload['build_ms']['p50']:.2f} "
        f"p95={payload['build_ms']['p95']:.2f} "
        f"mean={payload['build_ms']['mean']:.2f}"
    )
    print(
        f"  first_query_score:   min={payload['first_query_score_ms']['min']:.2f} "
        f"p50={payload['first_query_score_ms']['p50']:.2f} "
        f"p95={payload['first_query_score_ms']['p95']:.2f} "
        f"mean={payload['first_query_score_ms']['mean']:.2f}"
    )
    print(f"  wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
