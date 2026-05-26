#!/usr/bin/env python3
"""Render local HTML reviewer boards for priority eval/governance surfaces.

The boards intentionally read only aggregate-safe JSON and repository docs.
They do not run retrieval, re-score evals, inspect private raw cases, or change
runtime behavior.
"""
from __future__ import annotations

import argparse
import json
import subprocess
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
    "eval_surface_boundary": Path("reports/eval_surface_boundary.html"),
    "rag_pipeline_eda": Path("reports/real100/rag_pipeline_eda.html"),
    "rationality_judge": Path("reports/real100/rationality_judge_agreement.html"),
    "task_queue": Path("reports/task_queue_board.html"),
    "open_pr_merge": Path("reports/open_pr_merge_readiness.html"),
    "private_data_quality": Path("reports/private_data_quality_inventory.html"),
    "hwp_extraction": Path("reports/hwp_extraction_comparison.html"),
    "governance_automation": Path("reports/governance_automation.html"),
    "claim_validator": Path("reports/claim_validator.html"),
}

FLAT_OUTPUT_NAMES = {
    "eval_history": "eval_history_timeline.html",
    "retrieval_decision": "retrieval_decision_board.html",
    "difficulty_profile": "difficulty_profile.html",
    "verifier_overlap": "verifier_overlap.html",
    "parser_readiness": "parser_page_citation_readiness.html",
    "benchmark_validity": "benchmark_validity.html",
    "eval_surface_boundary": "eval_surface_boundary.html",
    "rag_pipeline_eda": "rag_pipeline_eda.html",
    "rationality_judge": "rationality_judge_agreement.html",
    "task_queue": "task_queue_board.html",
    "open_pr_merge": "open_pr_merge_readiness.html",
    "private_data_quality": "private_data_quality_inventory.html",
    "hwp_extraction": "hwp_extraction_comparison.html",
    "governance_automation": "governance_automation.html",
    "claim_validator": "claim_validator.html",
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


def _stat_cell(stats: Any, key: str = "p50") -> str:
    value = _as_mapping(stats).get(key)
    number = _number(value)
    if number is None:
        return "-"
    return f"{number:.2f}"


def _mean_cell(stats: Any) -> str:
    return _stat_cell(stats, "mean")


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


def render_eval_surface_boundary(root: Path) -> str:
    surface_path = root / "docs" / "evaluation" / "surface-map.md"
    adr5_path = root / "docs" / "adr" / "0005-eval-split-public-synthetic-private-local.md"
    checklist_path = root / "docs" / "reviews" / "ai-review-checklists.md"
    pr_template_path = root / ".github" / "pull_request_template.md"
    benchmark_path = root / "reports" / "benchmark_validity.html"
    real_summary_path = root / "reports" / "private_real_eval_summary.redacted.json"
    real_summary = _load_json(real_summary_path)
    claim_readiness = _as_mapping(real_summary.get("claim_readiness"))
    boundary_rows = [
        ["Public fixture smoke", "CI regression and contract sanity", "pass/fail, fixture-only delta", "private/production RFP performance"],
        ["Public synthetic benchmark", "method, contamination, scoring behavior", "synthetic-only benchmark comparison", "real-data quality claim"],
        ["Private real-eval aggregate", "local reviewer evidence", "aggregate trend with caveats", "raw private case disclosure"],
        ["Docs / governance", "claim policy and review checklist", "review requirement and allowed wording", "metric improvement without evidence"],
    ]
    reviewer_rows = [
        ["PR §5", "state eval impact or N/A", _rel(pr_template_path, root)],
        ["PR §5b", "load-bearing real-data delta or explicit no-op", _rel(pr_template_path, root)],
        ["Benchmark auditor", "required for eval/benchmark claims", _rel(checklist_path, root)],
        ["Surface map", "source of claim boundaries", _rel(surface_path, root)],
    ]
    cards = [
        render_status_card("Surface types", 4, detail="claim families", tone="accent"),
        render_status_card("Private claim status", claim_readiness.get("status", "-"), tone="neutral"),
        render_status_card("Raw private payloads", "not allowed", tone="danger"),
        render_status_card("Canonical source", "Markdown", detail="HTML is generated view", tone="ok"),
    ]
    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel("Surface Boundaries", render_table(["Surface", "Purpose", "Allowed", "Disallowed"], boundary_rows)),
            _panel("Reviewer Gates", render_table(["Gate", "What to check", "Source"], reviewer_rows)),
            _source_panel(root, [surface_path, adr5_path, checklist_path, pr_template_path, benchmark_path, real_summary_path]),
        ]
    )
    return render_document(
        title="Eval Surface Boundary Board",
        subtitle="Human review map for keeping smoke, synthetic benchmark, and private real-eval claims separate.",
        body=body,
        footer="Generated from governance docs and redacted aggregate summaries; no eval is run.",
    )


def _rag_axis_rows(label: str, data: Mapping[str, Any]) -> list[list[Any]]:
    axis1 = _as_mapping(data.get("axis1_retrieval_efficiency"))
    axis3 = _as_mapping(data.get("axis3_verification_retry"))
    axis4 = _as_mapping(data.get("axis4_stage_latency"))
    axis5 = _as_mapping(data.get("axis5_answer_synthesis"))
    axis6 = _as_mapping(data.get("axis6_evidence_quality"))
    return [
        [label, "retrieval cases", axis1.get("n_cases"), "gold chunk cases", axis1.get("n_cases_with_gold_chunks")],
        [label, "recall@10 mean", _metric_mean(_metric_from_nested(axis1, "recall", "at_10")), "mrr mean", _metric_mean(axis1.get("mrr"))],
        [label, "verify rate", _pct(axis3.get("verify_rate")), "attempts", _as_mapping(axis3.get("attempts_distribution"))],
        [label, "e2e p50 ms", _stat_cell(axis4.get("e2e_latency_ms")), "e2e p95 ms", _stat_cell(axis4.get("e2e_latency_ms"), "p95")],
        [label, "format compliance", _pct(axis5.get("answer_format_compliance_mean")), "status mix", _as_mapping(axis5.get("answer_status_distribution"))],
        [label, "paired evidence cases", axis6.get("n_paired_cases"), "recall/citation corr", axis6.get("pearson_recall_at_10_vs_citation_precision")],
    ]


def render_rag_pipeline_eda(root: Path) -> str:
    public_path = root / "reports" / "rag_pipeline.aggregate.json"
    real_path = root / "reports" / "real100" / "rag_pipeline.aggregate.json"
    public_data = _load_json(public_path)
    real_data = _load_json(real_path)
    real_axis1 = _as_mapping(real_data.get("axis1_retrieval_efficiency"))
    real_axis3 = _as_mapping(real_data.get("axis3_verification_retry"))
    real_axis4 = _as_mapping(real_data.get("axis4_stage_latency"))
    real_axis5 = _as_mapping(real_data.get("axis5_answer_synthesis"))
    stage_rows = [
        [stage, _mean_cell(stats), _stat_cell(stats), _stat_cell(stats, "p95"), _pct(_as_mapping(stats).get("share_of_e2e"))]
        for stage, stats in _as_mapping(real_axis4.get("per_stage")).items()
    ]
    answer_rows = _top_counter_rows(_as_mapping(real_axis5.get("answer_status_distribution")), limit=20)
    cards = [
        render_status_card("Real pipeline cases", real_axis1.get("n_cases", "-"), tone="accent"),
        render_status_card("Verify rate", _pct(real_axis3.get("verify_rate")), tone="ok"),
        render_status_card("E2E p50 ms", _stat_cell(real_axis4.get("e2e_latency_ms")), tone="neutral"),
        render_status_card("Format compliance", _pct(real_axis5.get("answer_format_compliance_mean")), tone="warn"),
    ]
    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel(
                "Pipeline Axis Summary",
                render_table(["Surface", "Metric", "Value", "Secondary", "Secondary value"], _rag_axis_rows("public fixture", public_data) + _rag_axis_rows("real100 aggregate", real_data)),
                "This board orients bottleneck triage; source Markdown/JSON remain canonical.",
            ),
            _panel("Real100 Stage Latency", render_table(["Stage", "Mean", "P50", "P95", "Share of E2E"], stage_rows)),
            _panel("Real100 Answer Status", render_table(["Status", "Count"], answer_rows)),
            _source_panel(root, [public_path, real_path, root / "reports" / "rag_pipeline.md", root / "reports" / "real100" / "rag_pipeline.md"]),
        ]
    )
    return render_document(
        title="RAG Pipeline EDA Board",
        subtitle="Human-readable bottleneck map over existing RAG pipeline aggregate reports.",
        body=body,
        footer="Generated from committed aggregate reports; no query or eval execution occurs.",
    )


def _agreement_rows(path: Path, root: Path) -> list[list[Any]]:
    data = _load_json(path)
    aggregate = _as_mapping(data.get("aggregate"))
    agreement = _as_mapping(aggregate.get("agreement"))
    rows = [
        [_rel(path, root), "backend", aggregate.get("backend"), "passes", _cell(agreement.get("passes"))],
        [_rel(path, root), "n", agreement.get("n"), "threshold", agreement.get("threshold")],
        [_rel(path, root), "cohens_kappa", agreement.get("cohens_kappa"), "spearman_rho", agreement.get("spearman_rho")],
        [_rel(path, root), "weighted_kappa_linear", agreement.get("weighted_kappa_linear"), "weighted_kappa_quadratic", agreement.get("weighted_kappa_quadratic")],
    ]
    for axis, values in _as_mapping(data.get("local")).items():
        value_map = _as_mapping(values)
        rows.append([axis, value_map.get("axis"), value_map.get("operator_verdict"), "judge", value_map.get("judge_verdict")])
    return rows


def render_rationality_judge(root: Path) -> str:
    rationality_path = root / "reports" / "real100" / "rationality.aggregate.json"
    q2_stub_path = root / "reports" / "self_review_agreement" / "Q2-2026.json"
    q2_openai_path = root / "reports" / "self_review_agreement" / "Q2-openai-vs-stub.json"
    rationality = _load_json(rationality_path)
    axis_rows = []
    for axis, mean in _as_mapping(rationality.get("axis_means")).items():
        ci = _as_mapping(_as_mapping(rationality.get("axis_cis")).get(axis))
        axis_rows.append([axis, _pct(mean), ci.get("n"), _pct(ci.get("ci_lo")), _pct(ci.get("ci_hi"))])
    agreement_rows = _agreement_rows(q2_stub_path, root) + _agreement_rows(q2_openai_path, root)
    cards = [
        render_status_card("Rationality N", rationality.get("n", "-"), tone="accent"),
        render_status_card("Synthesis calls", rationality.get("cases_with_synthesis_llm_call", "-"), tone="neutral"),
        render_status_card("Skipped traces", rationality.get("skipped_no_trace", "-"), tone="ok"),
        render_status_card("Agreement reports", sum(path.exists() for path in [q2_stub_path, q2_openai_path]), tone="neutral"),
    ]
    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel("Rationality Axes", render_table(["Axis", "Mean", "N", "CI low", "CI high"], axis_rows)),
            _panel("Judge Agreement Reports", render_table(["Source / Axis", "Metric / Label", "Value", "Secondary", "Secondary value"], agreement_rows)),
            _source_panel(root, [rationality_path, q2_stub_path, q2_openai_path, root / "docs" / "audits" / "rationality-llm-judge-comparison.md"]),
        ]
    )
    return render_document(
        title="Rationality / Judge Agreement Board",
        subtitle="Aggregate view for rationality judge scores and self-review agreement checks.",
        body=body,
        footer="Generated from aggregate reports only; judge output details remain in source artifacts.",
    )


def _queue_rows(markdown: str) -> list[list[str]]:
    rows: list[list[str]] = []
    in_table = False
    for line in markdown.splitlines():
        if line.startswith("| Order | ID | Status |"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and not line.startswith("|"):
            break
        if in_table:
            cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
            if len(cells) >= 5:
                rows.append(cells[:5])
    return rows


def render_task_queue(root: Path) -> str:
    queue_path = root / "tasks" / "queue.md"
    plan_dir = root / "docs" / "plans"
    queue_md = _read_text(queue_path)
    rows = _queue_rows(queue_md)
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row[2]] = status_counts.get(row[2], 0) + 1
    plan_count = len(list(plan_dir.glob("T-*.md"))) if plan_dir.exists() else 0
    cards = [
        render_status_card("Ready-order rows", len(rows), tone="accent"),
        render_status_card("Review tasks", status_counts.get("review", 0), tone="warn"),
        render_status_card("Done tasks", status_counts.get("done", 0), tone="ok"),
        render_status_card("Plan docs", plan_count, tone="neutral"),
    ]
    status_rows = [[status, count] for status, count in sorted(status_counts.items())]
    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel("Ready Order", render_table(["Order", "ID", "Status", "Owner role", "Why ready / not ready"], rows)),
            _panel("Status Mix", render_table(["Status", "Count"], status_rows)),
            _source_panel(root, [queue_path, plan_dir, root / "docs" / "operations" / "ai-engineering-operating-system.md"]),
        ]
    )
    return render_document(
        title="Plan / Task Queue Board",
        subtitle="Human scan view over the Markdown task queue and plan inventory.",
        body=body,
        footer="Markdown queue and plan files remain the AI source-of-truth.",
    )


def _live_pr_rows(root: Path) -> tuple[list[list[Any]], str]:
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--json",
                "number,title,isDraft,mergeStateStatus,reviewDecision,headRefName,baseRefName,updatedAt",
                "--limit",
                "50",
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"live PR snapshot unavailable: {exc}"
    if result.returncode != 0:
        return [], "live PR snapshot unavailable; gh pr list failed"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], "live PR snapshot unavailable; gh output was not JSON"
    rows = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, Mapping):
            continue
        if item.get("isDraft"):
            readiness = "draft"
        elif item.get("mergeStateStatus") not in {"CLEAN", "HAS_HOOKS"}:
            readiness = f"hold: {item.get('mergeStateStatus') or 'unknown'}"
        elif item.get("reviewDecision") == "CHANGES_REQUESTED":
            readiness = "hold: changes requested"
        else:
            readiness = "candidate"
        rows.append(
            [
                f"#{item.get('number')}",
                item.get("title"),
                item.get("headRefName"),
                item.get("baseRefName"),
                _cell(item.get("isDraft")),
                item.get("mergeStateStatus"),
                item.get("reviewDecision") or "-",
                readiness,
            ]
        )
    return rows, "live snapshot via gh pr list"


def render_open_pr_merge(root: Path) -> str:
    rows, note = _live_pr_rows(root)
    checklist_rows = [
        ["Draft", "do not merge", "mark ready only after validation evidence exists"],
        ["UNSTABLE / DIRTY", "hold", "inspect CI, dirty worktree, or base branch drift"],
        ["CHANGES_REQUESTED", "hold", "run review gate and address blockers"],
        ["Stacked base", "protect", "check open dependents before branch deletion"],
        ["Merged", "cleanup", "sync Desktop main and delete remote branch after dependent check"],
    ]
    cards = [
        render_status_card("Open PRs", len(rows), detail=note, tone="accent" if rows else "neutral"),
        render_status_card("Merge candidates", sum(1 for row in rows if row[-1] == "candidate"), tone="ok"),
        render_status_card("Drafts", sum(1 for row in rows if row[4] == "yes"), tone="warn"),
        render_status_card("Holds", sum(1 for row in rows if str(row[-1]).startswith("hold")), tone="danger"),
    ]
    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel(
                "Open PR Snapshot",
                render_table(["PR", "Title", "Head", "Base", "Draft", "Merge state", "Review", "Readiness"], rows, empty_message=note),
                "This is a live local snapshot when gh is available; GitHub remains authoritative.",
            ),
            _panel("Merge Readiness Rules", render_table(["Signal", "Classification", "Action"], checklist_rows)),
            _source_panel(root, [root / "CLAUDE.md", root / "docs" / "engineering-governance.md", root / "scripts" / "claude-hooks" / "_ship_review_gate.py"]),
        ]
    )
    return render_document(
        title="Open PR Merge Readiness Board",
        subtitle="Human scan view for draft/hold/candidate PR states and merge cleanup rules.",
        body=body,
        footer="Live PR rows are convenience snapshots; rerun the renderer before acting.",
    )


def render_private_data_quality(root: Path) -> str:
    summary_path = root / "reports" / "private_real_eval_summary.redacted.json"
    audit_doc_path = root / "docs" / "evaluation" / "private_data_quality_audit.md"
    parse_script = root / "scripts" / "audit_private_parse_quality.py"
    eval_script = root / "scripts" / "audit_private_eval_dataset.py"
    readiness_script = root / "scripts" / "check_private_real_eval_readiness.py"
    summary = _load_json(summary_path)
    dataset = _as_mapping(summary.get("dataset"))
    failures = _as_mapping(summary.get("failure_type_counts"))
    grouped: dict[str, int] = {}
    for key, value in failures.items():
        group = str(key).split(".", 1)[0]
        grouped[group] = grouped.get(group, 0) + int(_number(value) or 0)
    cards = [
        render_status_card("Documents", dataset.get("num_documents", "-"), tone="accent"),
        render_status_card("Chunks", dataset.get("num_chunks", "-"), tone="neutral"),
        render_status_card("Questions", dataset.get("num_questions", "-"), tone="neutral"),
        render_status_card("Raw payloads", "not committed", tone="ok"),
    ]
    workflow_rows = [
        ["1", "Parse audit", "aggregate parse quality only", f"`{_rel(parse_script, root)}`"],
        ["2", "Eval dataset audit", "label/reference integrity", f"`{_rel(eval_script, root)}`"],
        ["3", "Validate-only", "config/data readiness", f"`{_rel(readiness_script, root)}`"],
        ["4", "Private real-eval run", "local only", "redacted aggregate review"],
        ["5", "Redacted summary", "commit candidate", _rel(summary_path, root)],
    ]
    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel("Private Dataset Snapshot", render_table(["Field", "Value"], [[key, value] for key, value in dataset.items()])),
            _panel("Failure Counter Groups", render_table(["Group", "Count"], _top_counter_rows(grouped, limit=20))),
            _panel("Audit Workflow", render_table(["Order", "Step", "What it proves", "Source"], workflow_rows)),
            _source_panel(root, [summary_path, audit_doc_path, parse_script, eval_script, readiness_script]),
        ]
    )
    return render_document(
        title="Data Quality / Private Inventory Board",
        subtitle="Redacted, aggregate-only view of private corpus and private eval readiness workflow.",
        body=body,
        footer="Generated without reading private raw documents, labels, paths, or per-case payloads.",
    )


def render_hwp_extraction(root: Path) -> str:
    comparison_path = root / "docs" / "hwp" / "hwp-extraction-comparison.md"
    closure_path = root / "docs" / "hwp" / "hwp-eval-closure.md"
    native_path = root / "docs" / "hwp" / "hwp-native-spike.md"
    compare_script = root / "scripts" / "compare_hwp_extraction.py"
    kordoc_adr = root / "docs" / "adr" / "0049-kordoc-replaces-pyhwp-backend.md"
    page_adr = root / "docs" / "adr" / "0078-pymupdf4llm-canonical-page-citation.md"
    rows = [
        ["hwp5txt", "text-only", "table structure lost", "local experiment documented"],
        ["libreoffice -> visual-v2", "layout/table target", "HWP filter missing in measured environment", "documented as failed path"],
        ["pyhwp native tables", "table cell extraction", "opt-in historical path", "documented follow-up"],
        ["kordoc", "current backend", "Node subprocess dependency", "ADR 0049"],
        ["PyMuPDF4LLM page citation", "canonical page-aware PDF path", "page metadata contract required", "ADR 0078"],
    ]
    source_rows = [
        ["Comparison doc", _cell(bool(_read_text(comparison_path))), _rel(comparison_path, root)],
        ["Closure doc", _cell(bool(_read_text(closure_path))), _rel(closure_path, root)],
        ["Native spike", _cell(bool(_read_text(native_path))), _rel(native_path, root)],
        ["Comparison script", _cell(compare_script.exists()), _rel(compare_script, root)],
    ]
    cards = [
        render_status_card("Comparison paths", len(rows), tone="accent"),
        render_status_card("Raw HWP samples", "not read", tone="ok"),
        render_status_card("Current backend ADR", "0049", tone="neutral"),
        render_status_card("Page citation ADR", "0078", tone="neutral"),
    ]
    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel("Extraction Path Matrix", render_table(["Path", "Strength", "Main risk", "Status"], rows)),
            _panel("Source Inventory", render_table(["Source", "Present", "Path"], source_rows)),
            _source_panel(root, [comparison_path, closure_path, native_path, compare_script, kordoc_adr, page_adr]),
        ]
    )
    return render_document(
        title="HWP Extraction Comparison Board",
        subtitle="Human review board for HWP extraction path decisions and documented trade-offs.",
        body=body,
        footer="Generated from committed docs/scripts only; no private HWP sample is read.",
    )


def render_governance_automation(root: Path) -> str:
    workflow_dir = root / ".github" / "workflows"
    workflow_paths = sorted(workflow_dir.glob("*.yml")) if workflow_dir.exists() else []
    automation_rows = [
        ["Branch & issue convention", "hard CI gate", ".github/workflows/branch-and-issue-check.yml"],
        ["PR eval delta", "pytest shards + eval scope/provenance", ".github/workflows/pr-eval.yml"],
        ["Codex adversarial review", "informational review", ".github/workflows/codex-adversarial-review.yml"],
        ["Load-bearing awareness", "pre-tool reminder", "scripts/claude-hooks/pretooluse-loadbearing.sh"],
        ["Ship review gate", "requested changes / unresolved blocker check", "make ship-review-gate"],
        ["Desktop main sync", "post-merge canonical checkout sync", "scripts/sync_desktop_main.py"],
        ["Doc links", "markdown link/ADR reference validation", "scripts/check_doc_links.py"],
    ]
    source_rows = [[_rel(path, root), "present"] for path in workflow_paths]
    cards = [
        render_status_card("Workflow files", len(workflow_paths), tone="accent"),
        render_status_card("Automation checks", len(automation_rows), tone="neutral"),
        render_status_card("Load-bearing SSoT", "scripts/_governance.py", tone="ok"),
        render_status_card("Human override risk", "reviewer-owned", tone="warn"),
    ]
    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel("Automation Map", render_table(["Surface", "Guarantee", "Entry point"], automation_rows)),
            _panel("Workflow Inventory", render_table(["Workflow", "Status"], source_rows)),
            _source_panel(root, [root / "CLAUDE.md", root / "docs" / "engineering-governance.md", root / "scripts" / "_governance.py"] + workflow_paths),
        ]
    )
    return render_document(
        title="Governance Automation Board",
        subtitle="Human scan view of what automation enforces versus what reviewers still own.",
        body=body,
        footer="Generated from committed governance docs, scripts, and workflow files.",
    )


def render_claim_validator(root: Path) -> str:
    pr_template = root / ".github" / "pull_request_template.md"
    surface_map = root / "docs" / "evaluation" / "surface-map.md"
    checklist = root / "docs" / "reviews" / "ai-review-checklists.md"
    adr1 = root / "docs" / "adr" / "0001-preserve-naive-baseline.md"
    adr3 = root / "docs" / "adr" / "0003-structured-answer-citation-contract.md"
    adr5 = root / "docs" / "adr" / "0005-eval-split-public-synthetic-private-local.md"
    validation_rows = [
        ["Performance improved", "Needs matching eval surface + command + aggregate", "Reject if only smoke/synthetic supports real claim"],
        ["No behavior change", "Needs affected files consistent with claim", "Reject if load-bearing path changed without §5b escape"],
        ["Private real-eval claim", "Needs redacted aggregate + caveat", "Reject raw case/path disclosure"],
        ["Answer contract unchanged", "Needs ADR 0003/schema_version review", "Reject shadow contract/model drift"],
        ["Naive baseline preserved", "Needs ADR 0001 no-op or explicit eval proof", "Reject default baseline removal"],
        ["Reviewer HTML", "Markdown canonical + generated HTML view", "Reject HTML-only source-of-truth"],
    ]
    source_rows = [
        ["PR template", _cell(pr_template.exists()), _rel(pr_template, root)],
        ["Surface map", _cell(surface_map.exists()), _rel(surface_map, root)],
        ["Review checklists", _cell(checklist.exists()), _rel(checklist, root)],
        ["ADR 0001", _cell(adr1.exists()), _rel(adr1, root)],
        ["ADR 0003", _cell(adr3.exists()), _rel(adr3, root)],
        ["ADR 0005", _cell(adr5.exists()), _rel(adr5, root)],
    ]
    cards = [
        render_status_card("Claim checks", len(validation_rows), tone="accent"),
        render_status_card("Required PR sections", "1-7 + 5b", tone="warn"),
        render_status_card("Canonical claim policy", "surface-map.md", tone="ok"),
        render_status_card("HTML role", "human view only", tone="neutral"),
    ]
    body = "\n".join(
        [
            f'<section class="grid">{"".join(cards)}</section>',
            _panel("Claim Validation Rules", render_table(["Claim pattern", "Required evidence", "Reject when"], validation_rows)),
            _panel("Source Inventory", render_table(["Source", "Present", "Path"], source_rows)),
            _source_panel(root, [pr_template, surface_map, checklist, adr1, adr3, adr5]),
        ]
    )
    return render_document(
        title="Claim Validator Board",
        subtitle="Human review board for matching PR/report claims to required evidence surfaces.",
        body=body,
        footer="Generated from claim policy docs; it does not validate a specific PR body automatically.",
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
        paths["eval_surface_boundary"]: render_eval_surface_boundary(root),
        paths["rag_pipeline_eda"]: render_rag_pipeline_eda(root),
        paths["rationality_judge"]: render_rationality_judge(root),
        paths["task_queue"]: render_task_queue(root),
        paths["open_pr_merge"]: render_open_pr_merge(root),
        paths["private_data_quality"]: render_private_data_quality(root),
        paths["hwp_extraction"]: render_hwp_extraction(root),
        paths["governance_automation"]: render_governance_automation(root),
        paths["claim_validator"]: render_claim_validator(root),
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
        help="optional flat output directory for all HTML boards",
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
