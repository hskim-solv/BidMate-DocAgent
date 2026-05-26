#!/usr/bin/env python3
"""Render local HTML reviewer boards for priority eval/governance surfaces.

The boards intentionally read only aggregate-safe JSON and repository docs.
They do not run retrieval, re-score evals, inspect private raw cases, or change
runtime behavior.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.html_report import render_document, render_status_card, render_table

DEFAULT_OUTPUTS = {
    "eval_history": Path("reports/real100/eval_history_timeline.html"),
    "retrieval_decision": Path("reports/retrieval/retrieval_decision_board.html"),
    "difficulty_profile": Path("reports/real100/difficulty_profile.html"),
    "verifier_overlap": Path("reports/real100/verifier_overlap.html"),
    "parser_readiness": Path("reports/parser_page_citation_readiness.html"),
    "benchmark_validity": Path("reports/benchmark_validity.html"),
}

FLAT_OUTPUT_NAMES = {
    "eval_history": "eval_history_timeline.html",
    "retrieval_decision": "retrieval_decision_board.html",
    "difficulty_profile": "difficulty_profile.html",
    "verifier_overlap": "verifier_overlap.html",
    "parser_readiness": "parser_page_citation_readiness.html",
    "benchmark_validity": "benchmark_validity.html",
}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _pct(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    return f"{number * 100:.1f}%"


def _pct_already(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    return f"{number:.1f}%"


def _metric_mean(metric: Any) -> str:
    metric_map = _as_mapping(metric)
    if "mean" in metric_map:
        return _pct(metric_map.get("mean"))
    return _pct(metric)


def _delta(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    if abs(number) < 1 and "e" not in str(value).lower():
        return f"{number:+.3f}"
    return f"{number:+.2f}"


def _top_counter_rows(counter: Mapping[str, Any], *, limit: int = 10) -> list[list[Any]]:
    rows = sorted(counter.items(), key=lambda item: _number(item[1]) or 0, reverse=True)
    return [[key, value] for key, value in rows[:limit]]


def _panel(title: str, content: str, note: str = "") -> str:
    note_html = f'<p class="note">{note}</p>' if note else ""
    return f'<section class="panel"><h2>{title}</h2>{note_html}{content}</section>'


def _source_panel(root: Path, paths: Sequence[Path]) -> str:
    rows = [[_rel(path, root), "present" if path.exists() else "missing"] for path in paths]
    return _panel(
        "Sources",
        render_table(["Artifact", "Status"], rows),
        "All source paths are repository-relative; private raw case payloads are not read.",
    )


def _history_entries(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    history_dir = root / "reports" / "real100" / "history"
    return [(path, _load_json(path)) for path in sorted(history_dir.glob("*.aggregate.json"))]


def render_eval_history(root: Path) -> str:
    entries = _history_entries(root)
    rows: list[list[Any]] = []
    for path, data in entries:
        stem_parts = path.stem.replace(".aggregate", "").split("_", 1)
        run_id = stem_parts[0]
        commit = stem_parts[1] if len(stem_parts) > 1 else "-"
        failure_counts = _as_mapping(data.get("failure_category_counts"))
        top_failure = "-"
        if failure_counts:
            top_key, top_value = max(failure_counts.items(), key=lambda item: _number(item[1]) or 0)
            top_failure = f"{top_key}: {top_value}"
        rows.append(
            [
                run_id,
                commit,
                data.get("pipeline"),
                data.get("num_predictions"),
                _pct(data.get("accuracy")),
                _pct(data.get("abstention")),
                _pct(data.get("citation_precision")),
                _pct(data.get("groundedness")),
                top_failure,
            ]
        )

    latest = entries[-1][1] if entries else {}
    cards = [
        render_status_card("History runs", len(entries), detail="aggregate snapshots", tone="accent"),
        render_status_card("Latest accuracy", _pct(latest.get("accuracy")), tone="neutral"),
        render_status_card("Latest abstention", _pct(latest.get("abstention")), tone="warn"),
        render_status_card("Latest N", latest.get("num_predictions", "-"), tone="neutral"),
    ]
    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel(
                "Timeline",
                render_table(
                    [
                        "Run",
                        "Commit",
                        "Pipeline",
                        "N",
                        "Accuracy",
                        "Abstention",
                        "Citation precision",
                        "Groundedness",
                        "Top failure",
                    ],
                    rows,
                    empty_message="No history aggregate files found",
                ),
                "Use this to spot run-to-run drift before reading individual reports.",
            ),
            _source_panel(root, [path for path, _ in entries]),
        ]
    )
    return render_document(
        title="Real100 Eval History Timeline",
        subtitle="Chronological, aggregate-only view of private real-eval snapshots.",
        body=body,
        footer="Generated from reports/real100/history/*.aggregate.json only.",
    )


def _metric_from_nested(data: Mapping[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        current = _as_mapping(current).get(key)
    return current


def render_retrieval_decision(root: Path) -> str:
    hybrid_path = root / "reports" / "retrieval" / "hybrid_sweep_summary.aggregate.json"
    embedding_path = root / "reports" / "real100" / "embedding_ablation_retrieval.aggregate.json"
    phase3_path = root / "reports" / "retrieval" / "phase3_mode_20260518T032404Z" / "deltas.json"
    coverage_path = root / "reports" / "retrieval" / "phase4_metadata_20260520T032829Z_kordoc" / "coverage.json"
    hybrid = _load_json(hybrid_path)
    embedding = _load_json(embedding_path)
    phase3 = _load_json(phase3_path)
    coverage = _load_json(coverage_path)

    decision = _as_mapping(hybrid.get("decision"))
    baseline = _as_mapping(hybrid.get("baseline"))
    baseline_metrics = _as_mapping(baseline.get("metrics"))
    variants = _as_sequence(hybrid.get("variants"))
    variant_rows = []
    for variant in variants[:12]:
        variant_map = _as_mapping(variant)
        deltas = _as_mapping(variant_map.get("deltas_vs_dense"))
        variant_rows.append(
            [
                variant_map.get("name"),
                variant_map.get("primary_classification"),
                _delta(deltas.get("recall_at_10")),
                _delta(deltas.get("recall_at_5")),
                _delta(deltas.get("mrr_at_5")),
                _delta(deltas.get("ndcg_at_5")),
                _delta(deltas.get("latency_p50_ms")),
                _delta(deltas.get("latency_p95_ms")),
            ]
        )

    model_rows = []
    for model_name, model_info in _as_mapping(embedding.get("models")).items():
        full = _as_mapping(_metric_from_nested(_as_mapping(model_info), "ablations", "full"))
        model_rows.append(
            [
                model_name,
                _as_mapping(model_info).get("hf_id"),
                _metric_mean(full.get("chunk_recall_at_10")),
                _metric_mean(full.get("chunk_recall_at_5")),
                _metric_mean(full.get("chunk_mrr")),
                _metric_mean(full.get("chunk_ndcg_at_10")),
            ]
        )

    phase3_rows = [
        [
            name,
            _delta(_as_mapping(metrics).get("chunk_recall@10")),
            _delta(_as_mapping(metrics).get("chunk_recall@5")),
            _delta(_as_mapping(metrics).get("mrr")),
            _delta(_as_mapping(metrics).get("ndcg@10")),
        ]
        for name, metrics in phase3.items()
    ]
    coverage_rows = [
        [
            bucket,
            stats.get("n"),
            _pct_already(stats.get("pct")),
            stats.get("gold_present"),
            stats.get("gold_size_median"),
        ]
        for bucket, stats in _as_mapping(_as_mapping(coverage.get("stats")).get("buckets")).items()
        if isinstance(stats, Mapping)
    ]

    cards = [
        render_status_card("Hybrid decision", decision.get("final", "-"), detail="current sweep outcome", tone="warn"),
        render_status_card("Winner found", _cell(decision.get("winner_found")), tone="danger" if not decision.get("winner_found") else "ok"),
        render_status_card("Candidates", decision.get("candidate_count", "-"), detail="hybrid variants", tone="neutral"),
        render_status_card("Dense recall@10", _pct(baseline_metrics.get("recall_at_10")), detail=baseline.get("name", ""), tone="accent"),
    ]
    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel(
                "Hybrid Sweep Candidates",
                render_table(
                    ["Variant", "Classification", "dRecall@10", "dRecall@5", "dMRR@5", "dNDCG@5", "dP50 ms", "dP95 ms"],
                    variant_rows,
                    empty_message="No hybrid variants found",
                ),
                "Deltas are versus the dense baseline in the aggregate sweep summary.",
            ),
            _panel(
                "Embedding Ablation Full Retrieval Rows",
                render_table(
                    ["Model", "HF id", "Recall@10", "Recall@5", "MRR", "NDCG@10"],
                    model_rows,
                    empty_message="No embedding ablation aggregate found",
                ),
            ),
            _panel(
                "Mode Deltas",
                render_table(["Variant", "dRecall@10", "dRecall@5", "dMRR", "dNDCG@10"], phase3_rows),
                "Phase 3 mode deltas help separate backend choice from query/page metadata work.",
            ),
            _panel(
                "Query Metadata Coverage",
                render_table(["Bucket", "N", "Share", "Gold present", "Gold size median"], coverage_rows),
            ),
            _source_panel(root, [hybrid_path, embedding_path, phase3_path, coverage_path]),
        ]
    )
    return render_document(
        title="Retrieval Decision Board",
        subtitle="One-page aggregate view for dense, hybrid, embedding, mode, and metadata retrieval decisions.",
        body=body,
        footer="Generated from aggregate retrieval artifacts only; no retrieval run is executed.",
    )


def render_difficulty_profile(root: Path) -> str:
    path = root / "reports" / "real100" / "difficulty_profile.aggregate.json"
    data = _load_json(path)
    population = _as_mapping(data.get("population"))
    outcomes = _as_mapping(data.get("overall_outcomes"))
    conclusions = _as_mapping(data.get("conclusions"))
    next_improvement = _as_mapping(conclusions.get("next_improvement"))
    cards = [
        render_status_card("Cases", population.get("num_cases", "-"), detail="profile population", tone="accent"),
        render_status_card("Answerable", population.get("answerable_count", "-"), tone="neutral"),
        render_status_card("Failure rate", _pct(outcomes.get("failure_rate")), detail=f"{outcomes.get('failed_count', '-')} failed", tone="warn"),
        render_status_card("Next lever", next_improvement.get("recommended_next", "-"), tone="accent"),
    ]

    dominant_rows = [
        [item.get("axis"), item.get("bucket"), item.get("failed_count"), _pct(item.get("share_of_all_failures"))]
        for item in _as_sequence(conclusions.get("dominant_failure_slices"))
        if isinstance(item, Mapping)
    ]
    lever_rows = [
        [item.get("lever"), item.get("signal_count")]
        for item in _as_sequence(next_improvement.get("ranked_signals"))
        if isinstance(item, Mapping)
    ]
    axis_rows = []
    for axis, buckets in _as_mapping(data.get("difficulty_axes")).items():
        for bucket, stats in _as_mapping(buckets).items():
            metrics = _as_mapping(_as_mapping(stats).get("metrics"))
            axis_rows.append(
                [
                    axis,
                    bucket,
                    _as_mapping(stats).get("n"),
                    _as_mapping(stats).get("failed_count"),
                    _pct(_as_mapping(stats).get("failure_rate")),
                    _metric_mean(metrics.get("recall_at_10")),
                    _metric_mean(metrics.get("citation_precision")),
                ]
            )

    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel(
                "Dominant Failure Slices",
                render_table(["Axis", "Bucket", "Failed count", "Share of failures"], dominant_rows),
                _cell(conclusions.get("interpretation")),
            ),
            _panel("Ranked Improvement Levers", render_table(["Lever", "Signal count"], lever_rows)),
            _panel(
                "Difficulty Axis Detail",
                render_table(
                    ["Axis", "Bucket", "N", "Failed", "Failure rate", "Recall@10", "Citation precision"],
                    axis_rows,
                ),
            ),
            _source_panel(root, [path]),
        ]
    )
    return render_document(
        title="Difficulty Profile Board",
        subtitle="Private real-eval difficulty slices as aggregate counts and rates.",
        body=body,
        footer="Generated from reports/real100/difficulty_profile.aggregate.json only.",
    )


def render_verifier_overlap(root: Path) -> str:
    path = root / "reports" / "real100" / "verifier_false_negative_overlap.aggregate.json"
    data = _load_json(path)
    vfn = _as_mapping(data.get("verifier_false_negative"))
    inputs = _as_mapping(vfn.get("decision_inputs"))
    overlap = _as_mapping(vfn.get("overlap"))
    slices = _as_mapping(vfn.get("slices"))
    cards = [
        render_status_card("VFN total", vfn.get("total", "-"), detail=f"N={data.get('num_predictions', '-')}", tone="accent"),
        render_status_card("Decision", vfn.get("decision", "-"), tone="warn"),
        render_status_card("Retrieval fault signal", _pct(inputs.get("retrieval_fault_signal_rate")), tone="danger"),
        render_status_card("Citation missing", _pct(inputs.get("citation_missing_rate")), tone="danger"),
    ]
    overlap_rows = []
    for name, value in overlap.items():
        value_map = _as_mapping(value)
        if value_map:
            count = value_map.get("count")
            detail = ", ".join(f"{key}={val}" for key, val in _as_mapping(value_map.get("components")).items())
            if not detail:
                detail = ", ".join(f"{key}={val}" for key, val in _as_mapping(value_map.get("buckets")).items())
            overlap_rows.append([name, count, detail or "-"])
    pair_rows = _top_counter_rows(_as_mapping(_as_mapping(overlap.get("pairwise_intersections")).copy()), limit=20)
    slice_rows = []
    for slice_name, bucket_counts in slices.items():
        for bucket, count in _as_mapping(bucket_counts).items():
            slice_rows.append([slice_name, bucket, count])

    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel("Overlap Components", render_table(["Component", "Count", "Detail"], overlap_rows)),
            _panel("Pairwise Intersections", render_table(["Intersection", "Count"], pair_rows)),
            _panel("VFN Slices", render_table(["Slice", "Bucket", "Count"], slice_rows)),
            _source_panel(root, [path]),
        ]
    )
    return render_document(
        title="Verifier / VFN Overlap Board",
        subtitle="Aggregate overlap view for verifier false negatives and retrieval/citation fault signals.",
        body=body,
        footer="Generated from verifier_false_negative_overlap.aggregate.json only.",
    )


def render_parser_readiness(root: Path) -> str:
    summary_path = root / "reports" / "private_real_eval_summary.redacted.json"
    contract_path = root / "docs" / "evaluation" / "page_aware_parser_contract.md"
    recovery_path = root / "docs" / "evaluation" / "page_metadata_recovery_plan.md"
    hwp_path = root / "docs" / "hwp" / "hwp-eval-closure.md"
    adr_path = root / "docs" / "adr" / "0078-pymupdf4llm-canonical-page-citation.md"
    fixture_dir = root / "eval" / "fixtures" / "page_aware_parser_contract"
    fixtures = sorted(fixture_dir.glob("*.json"))
    summary = _load_json(summary_path)
    failures = _as_mapping(summary.get("failure_type_counts"))
    parser_failure_rows = [
        [key, failures.get(key)]
        for key in sorted(failures)
        if key.startswith("parsing_failure.") or key.startswith("citation_failure.")
    ]
    readiness_rows = [
        ["Page-aware parser contract", _cell(bool(_read_text(contract_path))), _rel(contract_path, root)],
        ["Page metadata recovery plan", _cell(bool(_read_text(recovery_path))), _rel(recovery_path, root)],
        ["HWP eval closure note", _cell(bool(_read_text(hwp_path))), _rel(hwp_path, root)],
        ["Canonical page citation ADR", _cell(bool(_read_text(adr_path))), _rel(adr_path, root)],
        ["Parser contract fixtures", len(fixtures), _rel(fixture_dir, root)],
    ]
    cards = [
        render_status_card("Contract fixtures", len(fixtures), tone="accent"),
        render_status_card("page_metadata_missing", failures.get("parsing_failure.page_metadata_missing", "-"), tone="neutral"),
        render_status_card("missing_page_number", failures.get("citation_failure.missing_page_number", "-"), tone="neutral"),
        render_status_card("Raw private cases read", "0", detail="redacted aggregate only", tone="ok"),
    ]
    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel(
                "Readiness Checklist",
                render_table(["Surface", "Current signal", "Source"], readiness_rows),
                "This is a readiness board, not a fresh parser evaluation.",
            ),
            _panel(
                "Redacted Parser / Citation Failure Counters",
                render_table(["Counter", "Count"], parser_failure_rows),
            ),
            _source_panel(root, [summary_path, contract_path, recovery_path, hwp_path, adr_path] + fixtures),
        ]
    )
    return render_document(
        title="Parser / Page Citation Readiness Board",
        subtitle="Contract and redacted-counter view for page-aware parser and citation readiness.",
        body=body,
        footer="Generated without reading private raw documents or per-case payloads.",
    )


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def render_benchmark_validity(root: Path) -> str:
    surface_path = root / "docs" / "evaluation" / "surface-map.md"
    synthetic_path = root / "docs" / "evaluation" / "synthetic_benchmark_v1_design.md"
    results_path = root / "docs" / "evaluation" / "naive_rag_benchmark_v1_results.md"
    registry_path = root / "benchmarks" / "registry.json"
    difficulty_path = root / "reports" / "real100" / "difficulty_profile.aggregate.json"
    summary_path = root / "reports" / "private_real_eval_summary.redacted.json"
    question_path = root / "data" / "eval" / "benchmark" / "rag_questions_v1.jsonl"
    corpus_dir = root / "data" / "eval" / "benchmark" / "corpus"

    difficulty = _load_json(difficulty_path)
    summary = _load_json(summary_path)
    conclusions = _as_mapping(difficulty.get("conclusions"))
    claim_readiness = _as_mapping(summary.get("claim_readiness"))
    synthetic_docs = sorted(corpus_dir.glob("*.json"))
    cards = [
        render_status_card("Private claim status", claim_readiness.get("status", "-"), tone="accent"),
        render_status_card("Benchmark validity", conclusions.get("benchmark_validity", "-"), tone="ok"),
        render_status_card("Invalid signal rate", _pct(conclusions.get("invalid_signal_rate")), tone="ok"),
        render_status_card("Synthetic questions", _count_jsonl(question_path), detail=f"{len(synthetic_docs)} corpus docs", tone="neutral"),
    ]
    claim_rows = [
        [
            "Public fixture smoke",
            "CI/regression sanity",
            "pass/fail and contract regression",
            "real-world RFP quality claim",
        ],
        [
            "Public synthetic benchmark",
            "benchmark method and contamination checks",
            "synthetic-only score comparison",
            "private real-eval or production performance claim",
        ],
        [
            "Private real-eval aggregate",
            "aggregate local reviewer evidence",
            "aggregate trend/caveated claim readiness",
            "raw private document or per-case disclosure",
        ],
    ]
    limitation_rows = [[item] for item in _as_sequence(summary.get("known_limitations"))]
    if not limitation_rows:
        limitation_rows = [["No known_limitations list in redacted summary"]]
    source_rows = [
        ["Surface map", _cell(bool(_read_text(surface_path))), _rel(surface_path, root)],
        ["Synthetic benchmark design", _cell(bool(_read_text(synthetic_path))), _rel(synthetic_path, root)],
        ["Synthetic benchmark results", _cell(bool(_read_text(results_path))), _rel(results_path, root)],
        ["Benchmark registry", _cell(registry_path.exists()), _rel(registry_path, root)],
        ["Private redacted summary", _cell(summary_path.exists()), _rel(summary_path, root)],
        ["Difficulty profile aggregate", _cell(difficulty_path.exists()), _rel(difficulty_path, root)],
    ]
    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel(
                "Claim Surface Boundaries",
                render_table(["Surface", "Purpose", "Allowed claim", "Disallowed claim"], claim_rows),
                "This board makes over-claiming visible before PR review.",
            ),
            _panel("Known Limitations", render_table(["Limitation"], limitation_rows)),
            _panel("Validity Source Inventory", render_table(["Source", "Present", "Path"], source_rows)),
            _source_panel(root, [surface_path, synthetic_path, results_path, registry_path, difficulty_path, summary_path, question_path]),
        ]
    )
    return render_document(
        title="Benchmark Validity Board",
        subtitle="Reviewer map for benchmark surfaces, allowed claims, and aggregate validity signals.",
        body=body,
        footer="Generated from docs, public synthetic benchmark files, and redacted/aggregate reports.",
    )


def output_paths(root: Path, out_dir: Path | None) -> dict[str, Path]:
    if out_dir is not None:
        return {key: out_dir / name for key, name in FLAT_OUTPUT_NAMES.items()}
    return {key: root / rel_path for key, rel_path in DEFAULT_OUTPUTS.items()}


def render_all(root: Path, out_dir: Path | None = None) -> dict[Path, str]:
    paths = output_paths(root, out_dir)
    return {
        paths["eval_history"]: render_eval_history(root),
        paths["retrieval_decision"]: render_retrieval_decision(root),
        paths["difficulty_profile"]: render_difficulty_profile(root),
        paths["verifier_overlap"]: render_verifier_overlap(root),
        paths["parser_readiness"]: render_parser_readiness(root),
        paths["benchmark_validity"]: render_benchmark_validity(root),
    }


def write_all(root: Path, out_dir: Path | None = None) -> list[Path]:
    written: list[Path] = []
    for path, html in render_all(root, out_dir).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        written.append(path)
    return written


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="optional flat output directory for all six HTML boards",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = args.root.resolve()
    out_dir = args.out_dir.resolve() if args.out_dir else None
    written = write_all(root, out_dir)
    for path in written:
        print(f"[OK] Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
