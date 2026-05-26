#!/usr/bin/env python3
"""Render a local HTML board for chunking and multi-chunk diagnostics.

This is a reviewer-facing view over existing aggregate or aggregate-derived
artifacts. It does not change retrieval, verifier, prompt, chunking, reranker,
answer, or eval runtime behavior.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.html_report import render_document, render_status_card, render_table

DEFAULT_PHASE2_DIR = ROOT / "reports" / "retrieval" / "phase2_chunking_20260518-0740"
DEFAULT_EDA = ROOT / "reports" / "real100" / "eda.aggregate.json"
DEFAULT_MULTI_CHUNK = (
    ROOT / "reports" / "real100" / "multi_chunk_evidence_failures.aggregate.json"
)
DEFAULT_OUT_HTML = ROOT / "reports" / "retrieval" / "chunking_diagnostics.html"

METRICS: tuple[str, ...] = ("chunk_recall@5", "chunk_recall@10", "mrr", "ndcg@10")


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _fmt(value: Any, digits: int = 3) -> str:
    num = _num(value)
    if num is None:
        return "-"
    return f"{num:.{digits}f}"


def _pct(value: Any) -> str:
    num = _num(value)
    if num is None:
        return "-"
    return f"{100.0 * num:.1f}%"


def _rate(numerator: Any, denominator: Any) -> float | None:
    num = _num(numerator)
    den = _num(denominator)
    if num is None or den is None or den <= 0:
        return None
    return num / den


def _metric_mean(per_case: list[dict[str, Any]], metric: str) -> tuple[float | None, int]:
    values = [_num(case.get(metric)) for case in per_case]
    clean = [value for value in values if value is not None]
    if not clean:
        return None, 0
    return sum(clean) / len(clean), len(clean)


def _significance(delta: dict[str, Any]) -> str:
    lo = _num(delta.get("ci_lo"))
    hi = _num(delta.get("ci_hi"))
    if lo is None or hi is None:
        return "n/a"
    if lo > 0:
        return "positive"
    if hi < 0:
        return "negative"
    return "not significant"


def build_board(
    *,
    specs: list[dict[str, Any]],
    raw_results: dict[str, Any],
    deltas: dict[str, Any],
    eda: dict[str, Any],
    multi_chunk: dict[str, Any],
) -> dict[str, Any]:
    """Build an aggregate-only payload for HTML rendering."""
    variants: list[dict[str, Any]] = []
    for spec in specs:
        name = str(spec.get("name") or "")
        raw = _mapping(raw_results.get(name))
        per_case = _rows(raw.get("per_case"))
        metric_summary = {
            metric: {
                "mean": mean,
                "n": n,
            }
            for metric in METRICS
            for mean, n in [_metric_mean(per_case, metric)]
        }
        variants.append(
            {
                "name": name,
                "chunking_strategy": str(spec.get("chunking_strategy") or ""),
                "chunk_max_chars": spec.get("chunk_max_chars"),
                "chunk_overlap_sentences": spec.get("chunk_overlap_sentences"),
                "num_documents": spec.get("num_documents"),
                "num_chunks": spec.get("num_chunks"),
                "section_detection_rate": spec.get("section_detection_rate"),
                "heuristic_engagement_rate": spec.get("heuristic_engagement_rate"),
                "latency_ms": _mapping(raw.get("latency_ms")),
                "metrics": metric_summary,
            }
        )

    current = next((item for item in variants if item["name"] == "current"), None)
    recall10_ranked = sorted(
        variants,
        key=lambda item: (
            _num(_mapping(item.get("metrics")).get("chunk_recall@10", {}).get("mean"))
            or -1.0
        ),
        reverse=True,
    )
    best_recall10 = recall10_ranked[0] if recall10_ranked else None
    recall10_deltas = {
        name: _mapping(_mapping(payload).get("chunk_recall@10"))
        for name, payload in deltas.items()
    }
    chunk_health = _mapping(
        _mapping(_mapping(eda.get("axis2_chunk_health")).get("corpus_chunk_health"))
    )
    per_doc_chunk_count = _mapping(
        _mapping(eda.get("axis2_chunk_health")).get("per_doc_chunk_count")
    )
    population = _mapping(multi_chunk.get("population"))
    return {
        "schema_version": 1,
        "variants": variants,
        "current": current,
        "best_recall10": best_recall10,
        "recall10_deltas": recall10_deltas,
        "chunk_health": chunk_health,
        "per_doc_chunk_count": per_doc_chunk_count,
        "multi_chunk": {
            "population": population,
            "retrieval_outcome_by_k": _mapping(multi_chunk.get("retrieval_outcome_by_k")),
            "evidence_split": _mapping(multi_chunk.get("evidence_split")),
            "expected_impact": _mapping(multi_chunk.get("expected_impact")),
            "candidate_pool_expansion": _mapping(
                multi_chunk.get("candidate_pool_expansion")
            ),
            "top10_failure_rate": _rate(
                population.get("multi_chunk_top10_evidence_failures"),
                population.get("multi_chunk_gold_cases"),
            ),
        },
    }


def render_html(board: dict[str, Any]) -> str:
    variants = _rows(board.get("variants"))
    current = _mapping(board.get("current"))
    best = _mapping(board.get("best_recall10"))
    chunk_health = _mapping(board.get("chunk_health"))
    multi = _mapping(board.get("multi_chunk"))
    population = _mapping(multi.get("population"))

    best_name = best.get("name") or "-"
    best_recall = _mapping(_mapping(best.get("metrics")).get("chunk_recall@10")).get(
        "mean"
    )
    current_chunks = current.get("num_chunks")
    top10_failure_rate = multi.get("top10_failure_rate")

    cards = [
        render_status_card(
            "Current chunks",
            current_chunks if current_chunks is not None else "-",
            detail=f"{current.get('chunking_strategy', '-')} / max {current.get('chunk_max_chars', '-')}",
            tone="accent",
        ),
        render_status_card(
            "Best recall@10",
            f"{best_name} {_fmt(best_recall)}",
            detail="phase2 chunking ablation, overall mean",
            tone="warn",
        ),
        render_status_card(
            "Mid-sentence cuts",
            _pct(chunk_health.get("mid_sentence_cut_ratio")),
            detail="EDA snapshot, aggregate only",
            tone="warn",
        ),
        render_status_card(
            "Multi-chunk top10 failures",
            _pct(top10_failure_rate),
            detail=(
                f"{population.get('multi_chunk_top10_evidence_failures', '-')} / "
                f"{population.get('multi_chunk_gold_cases', '-')} gold cases"
            ),
            tone="danger",
        ),
    ]

    variant_rows = []
    for item in variants:
        metrics = _mapping(item.get("metrics"))
        latency = _mapping(item.get("latency_ms"))
        variant_rows.append(
            [
                item.get("name"),
                item.get("chunking_strategy"),
                item.get("chunk_max_chars"),
                item.get("num_chunks"),
                _pct(item.get("section_detection_rate")),
                _fmt(_mapping(metrics.get("chunk_recall@10")).get("mean")),
                _fmt(_mapping(metrics.get("mrr")).get("mean")),
                _fmt(_mapping(metrics.get("ndcg@10")).get("mean")),
                _fmt(latency.get("p50")),
                _fmt(latency.get("p95")),
            ]
        )

    delta_rows = []
    for name, delta in _mapping(board.get("recall10_deltas")).items():
        delta_rows.append(
            [
                name,
                _fmt(delta.get("mean_current")),
                _fmt(delta.get("mean_other")),
                _fmt(delta.get("mean_diff")),
                f"{_fmt(delta.get('ci_lo'))} to {_fmt(delta.get('ci_hi'))}",
                _significance(delta),
            ]
        )

    health_rows = [
        ["total_chunks", chunk_health.get("total_chunks")],
        ["empty_chunks", chunk_health.get("empty_chunks")],
        ["near_empty_chunks", chunk_health.get("near_empty_chunks")],
        ["mean_length", _fmt(_mapping(chunk_health.get("length_chars")).get("mean"))],
        ["p95_length", _fmt(_mapping(chunk_health.get("length_chars")).get("p95"))],
        ["mid_sentence_cut_ratio", _pct(chunk_health.get("mid_sentence_cut_ratio"))],
        ["chunks_per_doc_mean", _fmt(_mapping(board.get("per_doc_chunk_count")).get("mean"))],
        ["chunks_per_doc_p95", _fmt(_mapping(board.get("per_doc_chunk_count")).get("p95"))],
    ]

    outcome_rows = []
    for k, outcomes in sorted(_mapping(multi.get("retrieval_outcome_by_k")).items()):
        mapped = _mapping(outcomes)
        outcome_rows.append(
            [
                f"top{k}",
                mapped.get("all_gold_retrieved", 0),
                mapped.get("partial_gold_retrieved", 0),
                mapped.get("no_gold_retrieved", 0),
                mapped.get("not_observable", 0),
            ]
        )

    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            '<section class="panel"><h2>Chunking Variants</h2>'
            '<p class="note">Metrics are aggregate means over eligible cases; no per-case id or text is emitted.</p>'
            + render_table(
                [
                    "Variant",
                    "Strategy",
                    "Max chars",
                    "Chunks",
                    "Section detect",
                    "Recall@10",
                    "MRR",
                    "nDCG@10",
                    "p50 ms",
                    "p95 ms",
                ],
                variant_rows,
            )
            + "</section>",
            '<section class="panel"><h2>Recall@10 Delta vs Current</h2>'
            '<p class="note">Positive means the variant improved over current. CI crossing zero is not claim-ready.</p>'
            + render_table(
                ["Variant", "Current", "Variant", "Delta", "95% CI", "Signal"],
                delta_rows,
            )
            + "</section>",
            '<section class="panel"><h2>Chunk Health Snapshot</h2>'
            + render_table(["Metric", "Value"], health_rows)
            + "</section>",
            '<section class="panel"><h2>Multi-chunk Evidence Retrieval</h2>'
            '<p class="note">Counts come from multi_chunk_evidence_failures.aggregate.json.</p>'
            + render_table(
                [
                    "K",
                    "All gold",
                    "Partial gold",
                    "No gold",
                    "Not observable",
                ],
                outcome_rows,
            )
            + "</section>",
        ]
    )
    return render_document(
        title="Chunking Diagnostics Board",
        subtitle=(
            "Local aggregate-only view of Phase 2 chunking ablation, corpus chunk "
            "health, and multi-chunk evidence failure diagnostics."
        ),
        body=body,
        footer=(
            "Local workflow artifact. This board does not claim a chunking winner "
            "or any RAG quality improvement."
        ),
    )


def load_board(phase2_dir: Path, eda_path: Path, multi_chunk_path: Path) -> dict[str, Any]:
    return build_board(
        specs=_rows(_load_json(phase2_dir / "chunking_specs.json")),
        raw_results=_mapping(_load_json(phase2_dir / "raw_results.json")),
        deltas=_mapping(_load_json(phase2_dir / "deltas.json")),
        eda=_mapping(_load_json(eda_path)),
        multi_chunk=_mapping(_load_json(multi_chunk_path)),
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase2-dir", type=Path, default=DEFAULT_PHASE2_DIR)
    parser.add_argument("--eda", type=Path, default=DEFAULT_EDA)
    parser.add_argument("--multi-chunk", type=Path, default=DEFAULT_MULTI_CHUNK)
    parser.add_argument("--out-html", type=Path, default=DEFAULT_OUT_HTML)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        board = load_board(args.phase2_dir, args.eda, args.multi_chunk)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Failed to build chunking diagnostics board: {exc}", file=sys.stderr)
        return 1
    args.out_html.parent.mkdir(parents=True, exist_ok=True)
    args.out_html.write_text(render_html(board), encoding="utf-8")
    print(f"[OK] Wrote {args.out_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
