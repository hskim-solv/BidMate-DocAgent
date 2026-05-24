from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.naive_rag.metrics import ndcg_at_k, recall_at_k, retrieval_metrics
from eval.naive_rag.run_eval import (
    REQUIRED_OUTPUTS,
    load_contract_config,
    load_gold_evidence,
    load_questions,
    run_from_config,
)
from eval.naive_rag.taxonomy import ALL_FAILURE_TYPES


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "eval" / "rag_quality_v1.yaml"


def test_contract_config_pins_naive_dense_only_top10() -> None:
    config = load_contract_config(CONFIG)
    pipeline = config["pipeline"]

    assert pipeline["name"] == "naive_baseline"
    assert pipeline["top_k"] == 10
    assert pipeline["retrieval_backend"] == "dense"
    assert pipeline["metadata_first"] is False
    assert pipeline["rerank"] is False
    assert pipeline["verifier_retry"] is False
    assert pipeline["query_expansion"] == "identity"


def test_sample_eval_data_has_required_answerable_and_unanswerable_counts() -> None:
    config = load_contract_config(CONFIG)
    questions = load_questions(ROOT / config["questions_path"])
    gold = load_gold_evidence(ROOT / config["gold_evidence_path"])

    assert sum(1 for row in questions if row["answerable"]) >= 10
    assert sum(1 for row in questions if not row["answerable"]) >= 3
    for question in questions:
        if question["answerable"]:
            assert gold[question["question_id"]]


def test_retrieval_metric_primitives_cover_requested_metrics() -> None:
    metrics = retrieval_metrics(["c0", "c1", "c2", "c3", "c4", "c5"], ["c5"])

    assert metrics["recall_at_5"] == 0.0
    assert metrics["recall_at_10"] == 1.0
    assert metrics["mrr_at_5"] == 0.0
    assert metrics["ndcg_at_5"] == 0.0
    assert recall_at_k(["c1"], [], 5) is None
    assert ndcg_at_k(["c1"], [], 5) is None


@pytest.mark.parametrize(
    "failure_type",
    [
        "retrieval_failure.gold_evidence_not_in_top_k",
        "retrieval_failure.gold_evidence_ranked_too_low",
        "retrieval_failure.wrong_similar_clause",
        "retrieval_failure.chunk_boundary_split",
        "retrieval_failure.query_wording_mismatch",
        "retrieval_failure.multi_chunk_evidence_missing",
        "parsing_failure.table_content_lost",
        "parsing_failure.figure_content_ignored",
        "parsing_failure.page_metadata_missing",
        "parsing_failure.header_footer_noise",
        "parsing_failure.korean_english_mixed_text_issue",
        "citation_failure.correct_answer_wrong_citation",
        "citation_failure.insufficient_citation",
        "citation_failure.missing_page_number",
        "citation_failure.citation_does_not_support_claim",
        "citation_failure.vague_citation_for_multiple_claims",
        "answer_failure.hallucinated_requirement",
        "answer_failure.partial_answer",
        "answer_failure.overconfident_weak_evidence",
        "answer_failure.wrong_synthesis",
        "answer_failure.failed_to_abstain",
        "evaluation_failure.no_gold_evidence",
        "evaluation_failure.metric_missing",
        "evaluation_failure.failure_case_not_saved",
    ],
)
def test_failure_taxonomy_contains_required_labels(failure_type: str) -> None:
    assert failure_type in ALL_FAILURE_TYPES


def test_runner_writes_contract_artifacts(tmp_path: Path) -> None:
    output_dir = run_from_config(
        CONFIG,
        output_root_override=tmp_path,
        run_id_override="pytest-naive-rag",
    )

    for name in REQUIRED_OUTPUTS:
        assert (output_dir / name).is_file(), name

    metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    assert set(metrics["retrieval_metrics"]) >= {"recall_at_5", "recall_at_10", "mrr_at_5", "ndcg_at_5"}
    assert set(metrics["answer_metrics"]) >= {
        "rule_based_groundedness",
        "term_coverage_accuracy",
        "citation_chunk_accuracy",
        "generator_hallucination_flag",
        "failed_abstention_flag",
        "unsupported_answer_flag",
        "unanswerable_detection_flag",
    }
    assert metrics["evaluation_type"] == "public_fixture_smoke_regression"
    assert metrics["valid_for_performance_claims"] is False
    assert metrics["dataset"]["answerable_count"] >= 10
    assert metrics["dataset"]["unanswerable_count"] >= 3
    assert metrics["pipeline"]["name"] == "naive_baseline"
    assert metrics["pipeline"]["top_k"] == 10
    assert metrics["pipeline"]["retrieval_backend"] == "dense"

    failure_lines = [
        json.loads(line)
        for line in (output_dir / "failure_cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for row in failure_lines:
        assert row["failure_type"] in ALL_FAILURE_TYPES
        assert row["question_id"]
        assert "metrics" in row
        assert "gold_evidence" in row
        assert "retrieved_chunks" in row
        assert "answer" in row
