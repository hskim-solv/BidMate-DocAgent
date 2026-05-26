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
    _write_json(
        root / "reports/real100/rag_pipeline.aggregate.json",
        {
            "axis1_retrieval_efficiency": {"n_cases": 2, "n_cases_with_gold_chunks": 1, "recall": {"at_10": {"mean": 0.5}}, "mrr": {"mean": 0.4}},
            "axis3_verification_retry": {"verify_rate": 0.75, "attempts_distribution": {"1": 1}},
            "axis4_stage_latency": {"e2e_latency_ms": {"p50": 12.3, "p95": 45.6}, "per_stage": {"retrieve_ms": {"mean": 1.2, "p50": 1.0, "p95": 2.0, "share_of_e2e": 0.1}}},
            "axis5_answer_synthesis": {"answer_format_compliance_mean": 0.8, "answer_status_distribution": {"supported": 1}},
            "axis6_evidence_quality": {"n_paired_cases": 1, "pearson_recall_at_10_vs_citation_precision": 0.2},
        },
    )
    _write_json(root / "reports/rag_pipeline.aggregate.json", json.loads((root / "reports/real100/rag_pipeline.aggregate.json").read_text()))
    _write_text(root / "reports/rag_pipeline.md", "pipeline")
    _write_text(root / "reports/real100/rag_pipeline.md", "pipeline")
    _write_json(
        root / "reports/real100/rationality.aggregate.json",
        {
            "n": 2,
            "cases_with_synthesis_llm_call": 1,
            "skipped_no_trace": 0,
            "axis_means": {"planner_decomposition": 0.5},
            "axis_cis": {"planner_decomposition": {"n": 2, "ci_lo": 0.25, "ci_hi": 0.75}},
        },
    )
    agreement = {
        "local": {"axis_1": {"axis": "context", "operator_verdict": "supported", "judge_verdict": "partial"}},
        "aggregate": {"backend": "stub", "agreement": {"n": 1, "passes": False, "threshold": 0.6, "cohens_kappa": 0.0}},
    }
    _write_json(root / "reports/self_review_agreement/Q2-2026.json", agreement)
    _write_json(root / "reports/self_review_agreement/Q2-openai-vs-stub.json", agreement)
    _write_text(root / "docs/audits/rationality-llm-judge-comparison.md", "judge")
    _write_text(root / "tasks/queue.md", "| Order | ID | Status | Owner role | Why ready / not ready |\n|---:|---|---|---|---|\n| 1 | `T-1` | `review` | Implementer | ready |\n")
    _write_text(root / "docs/operations/ai-engineering-operating-system.md", "ops")
    _write_text(root / "docs/engineering-governance.md", "governance")
    _write_text(root / "docs/reviews/ai-review-checklists.md", "checks")
    _write_text(root / ".github/pull_request_template.md", "template")
    _write_text(root / "CLAUDE.md", "rules")
    _write_text(root / "scripts/claude-hooks/_ship_review_gate.py", "gate")
    _write_text(root / "docs/evaluation/private_data_quality_audit.md", "audit")
    _write_text(root / "scripts/audit_private_parse_quality.py", "parse")
    _write_text(root / "scripts/audit_private_eval_dataset.py", "eval")
    _write_text(root / "scripts/check_private_real_eval_readiness.py", "ready")
    _write_text(root / "docs/hwp/hwp-extraction-comparison.md", "hwp")
    _write_text(root / "docs/hwp/hwp-native-spike.md", "native")
    _write_text(root / "scripts/compare_hwp_extraction.py", "compare")
    _write_text(root / "docs/adr/0001-preserve-naive-baseline.md", "adr1")
    _write_text(root / "docs/adr/0003-structured-answer-citation-contract.md", "adr3")
    _write_text(root / "docs/adr/0005-eval-split-public-synthetic-private-local.md", "adr5")
    _write_text(root / "docs/adr/0049-kordoc-replaces-pyhwp-backend.md", "adr49")
    _write_text(root / "scripts/_governance.py", "load-bearing")
    _write_text(root / "scripts/sync_desktop_main.py", "sync")
    _write_text(root / "scripts/check_doc_links.py", "links")
    _write_text(root / ".github/workflows/pr-eval.yml", "name: pr")
    _write_text(root / ".github/workflows/branch-and-issue-check.yml", "name: branch")


def test_render_all_returns_all_escaped_documents(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)

    docs = render_all(tmp_path, tmp_path / "out")

    assert len(docs) == 15
    joined = "\n".join(docs.values())
    assert "Real100 Eval History Timeline" in joined
    assert "Retrieval Decision Board" in joined
    assert "Difficulty Profile Board" in joined
    assert "Verifier / VFN Overlap Board" in joined
    assert "Parser / Page Citation Readiness Board" in joined
    assert "Benchmark Validity Board" in joined
    assert "Eval Surface Boundary Board" in joined
    assert "RAG Pipeline EDA Board" in joined
    assert "Rationality / Judge Agreement Board" in joined
    assert "Plan / Task Queue Board" in joined
    assert "Open PR Merge Readiness Board" in joined
    assert "Data Quality / Private Inventory Board" in joined
    assert "HWP Extraction Comparison Board" in joined
    assert "Governance Automation Board" in joined
    assert "Claim Validator Board" in joined
    assert "<script>" not in joined
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in joined


def test_eval_history_does_not_expose_absolute_root_path(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)

    html = render_eval_history(tmp_path)

    assert str(tmp_path) not in html
    assert "reports/real100/history/20260101T000000Z_deadbeef.aggregate.json" in html


def test_cli_writes_all_flat_html_files(tmp_path: Path) -> None:
    _fixture_repo(tmp_path)
    out_dir = tmp_path / "html"

    rc = main(["--root", str(tmp_path), "--out-dir", str(out_dir)])

    assert rc == 0
    outputs = sorted(out_dir.glob("*.html"))
    assert len(outputs) == 15
    assert any("Benchmark Validity Board" in path.read_text(encoding="utf-8") for path in outputs)
    assert any("Claim Validator Board" in path.read_text(encoding="utf-8") for path in outputs)
