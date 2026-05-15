#!/usr/bin/env python3
"""Chunking strategy ablation runner (issue #62).

Builds the public synthetic index three times — once per
`chunking_strategy` (fixed / section / auto) — and runs the
`chunk_boundary` probe queries from `eval/config.yaml` against each.
Prints an aggregate table reviewers can transcribe into the
`docs/retrieval/chunking-diagnostics.md` ablation section.

This is a measurement tool, not a one-shot CI gate. It does not
change defaults; the smoke pipeline still uses the CLI default
(`fixed`, the `naive_baseline` reference per ADR 0001). Run when
chunking strategy or default changes are under consideration.

Usage:
    python3 scripts/run_chunking_ablation.py
    python3 scripts/run_chunking_ablation.py --queries-only

The `--queries-only` flag skips the per-doc chunk-count summary
and prints just the per-probe score table.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rag_core import build_index_payload, run_rag_query  # noqa: E402


@dataclass(frozen=True)
class ProbeCase:
    case_id: str
    query: str
    expected_term: str
    expected_doc_id: str


# Mirror the issue-#73 chunk-boundary cases from `eval/config.yaml`.
# Keeping this list local to the script keeps the ablation runner
# decoupled from the eval YAML loader.
PROBE_CASES = (
    ProbeCase(
        case_id="chunk_probe_external_audit_period",
        query="기관 D 분광기 운영 데이터의 외부 감사 주기는?",
        expected_term="분기별",
        expected_doc_id="rfp-agency-d-spectrometer-probe",
    ),
    ProbeCase(
        case_id="chunk_probe_report_storage",
        query="기관 D 분광기 보고서 보관 기간과 위치는?",
        expected_term="5년",
        expected_doc_id="rfp-agency-d-spectrometer-probe",
    ),
    ProbeCase(
        case_id="chunk_probe_calibration_overlap",
        query="기관 D 분광기 라만 캘리브레이션 주기는?",
        expected_term="매일",
        expected_doc_id="rfp-agency-d-spectrometer-probe",
    ),
)

STRATEGIES = ("fixed", "section", "auto")


def run_for_strategy(strategy: str) -> dict:
    index = build_index_payload(
        Path("data/raw"),
        embedding_backend="hashing",
        chunking_strategy=strategy,
    )
    chunk_counts: dict[str, int] = {}
    for chunk in index["chunks"]:
        chunk_counts[chunk["doc_id"]] = chunk_counts.get(chunk["doc_id"], 0) + 1
    results = []
    for probe in PROBE_CASES:
        result = run_rag_query(index, probe.query)
        evidence = result.get("evidence", [])
        top = evidence[0] if evidence else {}
        text = top.get("text", "")
        results.append(
            {
                "case_id": probe.case_id,
                "top_doc_id": top.get("doc_id"),
                "top_score": top.get("score"),
                "chunk_seq": top.get("chunk_seq_in_section"),
                "total_chunks": top.get("total_chunks_in_section"),
                "term_in_text": probe.expected_term in text,
                "correct": (
                    top.get("doc_id") == probe.expected_doc_id
                    and probe.expected_term in text
                ),
            }
        )
    return {
        "strategy": strategy,
        "total_chunks": len(index["chunks"]),
        "chunks_per_doc": chunk_counts,
        "probe_results": results,
    }


def render(report_per_strategy: dict[str, dict], queries_only: bool) -> None:
    if not queries_only:
        print("=== Chunks per doc, by strategy ===")
        print()
        all_doc_ids = sorted(
            {
                doc_id
                for r in report_per_strategy.values()
                for doc_id in r["chunks_per_doc"]
            }
        )
        header = "doc_id".ljust(45) + " | " + " | ".join(s.center(8) for s in STRATEGIES)
        print(header)
        print("-" * len(header))
        for doc_id in all_doc_ids:
            row = doc_id.ljust(45) + " | " + " | ".join(
                str(report_per_strategy[s]["chunks_per_doc"].get(doc_id, "-")).center(8)
                for s in STRATEGIES
            )
            print(row)
        total_row = "TOTAL".ljust(45) + " | " + " | ".join(
            str(report_per_strategy[s]["total_chunks"]).center(8) for s in STRATEGIES
        )
        print(total_row)
        print()

    print("=== Probe scores per strategy (chunk_boundary slice from issue #73) ===")
    print()
    header = (
        "case_id".ljust(40)
        + " | "
        + " | ".join(s.center(20) for s in STRATEGIES)
    )
    print(header)
    print("-" * len(header))
    for i, probe in enumerate(PROBE_CASES):
        cells = []
        for strategy in STRATEGIES:
            r = report_per_strategy[strategy]["probe_results"][i]
            ok = "✓" if r["correct"] else "✗"
            score = r["top_score"]
            seq = r["chunk_seq"]
            total = r["total_chunks"]
            cells.append(f"{ok} score={score} {seq}/{total}".center(20))
        print(probe.case_id.ljust(40) + " | " + " | ".join(cells))
    print()
    print(
        "Score deltas (relative to fixed):",
        ", ".join(
            f"{strategy}: "
            + str(
                round(
                    sum(
                        (
                            report_per_strategy[strategy]["probe_results"][i]["top_score"]
                            or 0
                        )
                        - (report_per_strategy["fixed"]["probe_results"][i]["top_score"] or 0)
                        for i in range(len(PROBE_CASES))
                    )
                    / len(PROBE_CASES),
                    4,
                )
            )
            for strategy in STRATEGIES
            if strategy != "fixed"
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--queries-only",
        action="store_true",
        help="Skip the per-doc chunk count summary",
    )
    args = parser.parse_args()
    report = {strategy: run_for_strategy(strategy) for strategy in STRATEGIES}
    render(report, queries_only=args.queries_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
