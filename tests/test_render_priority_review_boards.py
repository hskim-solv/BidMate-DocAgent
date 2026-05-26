"""Regression guards for the priority local HTML review boards."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.render_priority_review_boards import main, render_all, render_eval_history


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture_repo(root: Path) -> None:
    _write_json(
        root / "reports/real100/history/20260101T000000Z_deadbeef.aggregate.json",
        {
            "pipeline": "agentic_full",
            "num_predictions": 2,
            "accuracy": 0.5,
            "abstention": 0.25,
            "citation_precision": 0.75,
            "groundedness": 1.0,
            "failure_category_counts": {"retrieval_miss": 1},
        },
    )
    _write_json(
        root / "reports/retrieval/hybrid_sweep_summary.aggregate.json",
        {
            "baseline": {"name": "dense", "metrics": {"recall_at_10": 0.2}},
            "decision": {
                "final": "keep dense <script>alert(1)</script>",
                "winner_found": False,
                "candidate_count": 1,
            },
            "variants": [
                {
                    "name": "hybrid",
                    "primary_classification": "ranking_regression",
                    "deltas_vs_dense": {
                        "recall_at_10": -0.1,
                        "recall_at_5": 0.0,
                        "mrr_at_5": -0.2,
                        "ndcg_at_5": -0.3,
                        "latency_p50_ms": 10,
                        "latency_p95_ms": 20,
                    },
                }
            ],
        },
    )
    _write_json(
        root / "reports/real100/embedding_ablation_retrieval.aggregate.json",
        {
            "models": {
                "MiniLM": {
                    "hf_id": "model",
                    "ablations": {
                        "full": {
                            "chunk_recall_at_10": {"mean": 0.2},
                            "chunk_recall_at_5": {"mean": 0.1},
                            "chunk_mrr": {"mean": 0.3},
                            "chunk_ndcg_at_10": {"mean": 0.4},
                        }
                    },
                }
            }
        },
    )
    _write_json(root / "reports/retrieval/phase3_mode_20260518T032404Z/deltas.json", {"hybrid": {"chunk_recall@10": 0.1}})
    _write_json(
        root / "reports/retrieval/phase4_metadata_20260520T032829Z_kordoc/coverage.json",
        {"stats": {"buckets": {"content_query": {"n": 2, "pct": 50.0, "gold_present": 1, "gold_size_median": 3}}}},
    )
    _write_json(
        root / "reports/real100/difficulty_profile.aggregate.json",
        {
            "population": {"num_cases": 2, "answerable_count": 1},
            "overall_outcomes": {"failure_rate": 0.5, "failed_count": 1},
            "conclusions": {
                "interpretation": "hard benchmark",
                "benchmark_validity": "hard_benchmark_not_invalid",
                "invalid_signal_rate": 0.0,
                "dominant_failure_slices": [{"axis": "answerability", "bucket": "answerable", "failed_count": 1}],
                "next_improvement": {"recommended_next": "page_metadata_recovery", "ranked_signals": [{"lever": "page", "signal_count": 2}]},
            },
            "difficulty_axes": {
                "answerability": {
                    "answerable": {
                        "n": 1,
                        "failed_count": 1,
                        "failure_rate": 1.0,
                        "metrics": {"recall_at_10": {"mean": 0.2}},
                    }
                }
            },
        },
    )
    _write_json(
        root / "reports/real100/verifier_false_negative_overlap.aggregate.json",
        {
            "num_predictions": 2,
            "verifier_false_negative": {
                "total": 1,
                "decision": "mixed",
                "decision_inputs": {"retrieval_fault_signal_rate": 0.5, "citation_missing_rate": 1.0},
                "overlap": {
                    "retrieval_fault_signal": {"count": 1, "components": {"expected_doc_missing": 1}},
                    "pairwise_intersections": {"retrieval_fault_signal+citation_missing": 1},
                },
                "slices": {"query_type": {"abstention": 1}},
            },
        },
    )
    _write_json(
        root / "reports/private_real_eval_summary.redacted.json",
        {
            "claim_readiness": {"status": "claim-ready"},
            "known_limitations": ["aggregate only"],
            "failure_type_counts": {
                "parsing_failure.page_metadata_missing": 0,
                "citation_failure.missing_page_number": 0,
            },
        },
    )
    _write_text(root / "docs/evaluation/page_aware_parser_contract.md", "contract")
    _write_text(root / "docs/evaluation/page_metadata_recovery_plan.md", "plan")
    _write_text(root / "docs/hwp/hwp-eval-closure.md", "closure")
    _write_text(root / "docs/adr/0078-pymupdf4llm-canonical-page-citation.md", "adr")
    _write_text(root / "docs/evaluation/surface-map.md", "surface")
    _write_text(root / "docs/evaluation/synthetic_benchmark_v1_design.md", "synthetic")
    _write_text(root / "docs/evaluation/naive_rag_benchmark_v1_results.md", "results")
    _write_json(root / "benchmarks/registry.json", {"suites": []})
    _write_text(root / "data/eval/benchmark/rag_questions_v1.jsonl", "{}\n{}\n")
    _write_json(root / "data/eval/benchmark/corpus/doc.json", {"doc": "public synthetic"})
    _write_json(root / "eval/fixtures/page_aware_parser_contract/valid_sections.json", {"ok": True})


def test_render_all_returns_six_escaped_documents(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)

    docs = render_all(tmp_path, tmp_path / "out")

    assert len(docs) == 6
    joined = "\n".join(docs.values())
    assert "Real100 Eval History Timeline" in joined
    assert "Retrieval Decision Board" in joined
    assert "Difficulty Profile Board" in joined
    assert "Verifier / VFN Overlap Board" in joined
    assert "Parser / Page Citation Readiness Board" in joined
    assert "Benchmark Validity Board" in joined
    assert "<script>" not in joined
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in joined


def test_eval_history_does_not_expose_absolute_root_path(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)

    html = render_eval_history(tmp_path)

    assert str(tmp_path) not in html
    assert "reports/real100/history/20260101T000000Z_deadbeef.aggregate.json" in html


def test_cli_writes_six_flat_html_files(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    out_dir = tmp_path / "html"

    rc = main(["--root", str(tmp_path), "--out-dir", str(out_dir)])

    assert rc == 0
    outputs = sorted(out_dir.glob("*.html"))
    assert len(outputs) == 6
    assert any("Benchmark Validity Board" in path.read_text(encoding="utf-8") for path in outputs)
