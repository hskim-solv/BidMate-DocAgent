#!/usr/bin/env python3
"""Regenerate (or --check) the naive_baseline ranking golden (ADR 0001).

``tests/data/naive_baseline_top_k.json`` pins the top-K ``(chunk_id, score)``
for a fixed query set, built from ``data/raw/`` through the ``naive_baseline``
pipeline with the deterministic hashing backend + fixed chunking. It drifts
whenever the ``data/raw/`` corpus changes (e.g. PR #648 HWP fixtures, PR #914
H/I/J/K corpus), and until now each drift was repaired by hand with tribal
``EMBEDDING_BACKEND=hashing chunking_strategy=fixed`` commands.

Write mode (default): rebuild and overwrite the golden in place, preserving the
committed query set and each query's top-K length. To add/remove a query, edit
the golden's keys first (a deliberate act), then regenerate to fill the values.

``--check`` mode: rebuild and exit 1 if the committed golden is stale (used by
the pre-push reminder and ``make check-golden``).

This module is the single source of truth for *how* the golden is built;
``tests/test_naive_baseline_ranking_invariance.py`` imports ``build_golden`` so
the test and the regenerator can never drift apart. ADR 0001: this only
refreshes the snapshot — the ``naive_baseline`` pipeline code is never touched
here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rag_core import build_index_payload, run_rag_query  # noqa: E402

GOLDEN_PATH = REPO_ROOT / "tests" / "data" / "naive_baseline_top_k.json"
CORPUS_DIR = REPO_ROOT / "data" / "raw"

# Hashing backend + fixed chunking = deterministic across machines and across
# the Phase 3 stack (see the invariance test docstring). These must stay in
# lockstep with what the test reproduces.
EMBEDDING_BACKEND = "hashing"
CHUNKING_STRATEGY = "fixed"


def build_golden(reference: dict[str, list]) -> dict[str, list]:
    """Rebuild the naive_baseline top-K snapshot for ``reference``'s query set.

    Each query is re-run through the ``naive_baseline`` pipeline; the result is
    truncated to the same length the query has in ``reference``, so the curated
    query set + per-query K are preserved. Adding/removing a query is therefore
    a deliberate edit to the golden, never a side effect of regeneration.
    """
    index = build_index_payload(
        CORPUS_DIR,
        embedding_backend=EMBEDDING_BACKEND,
        chunking_strategy=CHUNKING_STRATEGY,
    )
    rebuilt: dict[str, list] = {}
    for query, golden_top in reference.items():
        result = run_rag_query(index, query, pipeline="naive_baseline")
        citations = result.get("citations") or result.get("evidence") or []
        rebuilt[query] = [
            [c.get("chunk_id"), c.get("score")] for c in citations[: len(golden_top)]
        ]
    return rebuilt


def _serialize(golden: dict[str, list]) -> str:
    # 2-space indent + ensure_ascii=False + trailing newline = byte-identical to
    # the committed golden, so a no-op regeneration is a clean (empty) git diff.
    return json.dumps(golden, ensure_ascii=False, indent=2) + "\n"


def run(check: bool, golden_path: Path = GOLDEN_PATH) -> int:
    committed = json.loads(golden_path.read_text(encoding="utf-8"))
    rebuilt = build_golden(committed)

    if check:
        if rebuilt != committed:
            drifted = sorted(q for q in committed if committed[q] != rebuilt.get(q))
            print(
                f"[FAIL] naive_baseline golden is stale ({golden_path}).\n"
                f"       Drifted queries: {drifted}\n"
                f"       Regenerate with: make regen-golden",
                file=sys.stderr,
            )
            return 1
        print(f"[OK] naive_baseline golden is up-to-date ({golden_path})")
        return 0

    golden_path.write_text(_serialize(rebuilt), encoding="utf-8")
    print(f"[OK] Regenerated {golden_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate (or --check) the naive_baseline ranking golden (ADR 0001)."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if the committed golden is stale instead of rewriting it.",
    )
    args = parser.parse_args(argv)
    return run(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
