from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from eval.naive_rag.validate_benchmark_dataset import (
    QUESTION_TYPE_MINIMUMS,
    jsonl_rows,
    repo_path,
    validate_dataset,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "eval" / "benchmark_naive_rag_v1.yaml"


def _summary() -> dict:
    summary = validate_dataset(CONFIG)
    assert summary["errors"] == []
    return summary


def _questions() -> list[dict]:
    return jsonl_rows(ROOT / "data" / "eval" / "benchmark" / "rag_questions_v1.jsonl")


def _gold() -> list[dict]:
    return jsonl_rows(ROOT / "data" / "eval" / "benchmark" / "gold_evidence_v1.jsonl")


def test_benchmark_dataset_validator_passes() -> None:
    summary = _summary()

    dataset = summary["dataset_summary"]
    assert dataset["num_docs"] == 6
    assert dataset["num_chunks"] == 72
    assert dataset["num_questions"] >= 50
    assert dataset["answerable_count"] >= 35
    assert dataset["unanswerable_count"] >= 15
    assert dataset["chunk_count_top_k_ratio"] >= 3.0


def test_question_distribution_satisfies_required_counts() -> None:
    distribution = _summary()["question_type_distribution"]

    for question_type, minimum in QUESTION_TYPE_MINIMUMS.items():
        assert distribution[question_type] >= minimum


def test_answerable_questions_have_explicit_gold_and_unanswerable_do_not() -> None:
    questions = _questions()
    gold_by_question: dict[str, list[dict]] = defaultdict(list)
    for item in _gold():
        gold_by_question[item["question_id"]].append(item)

    for question in questions:
        qid = question["question_id"]
        if question["answerable"]:
            assert question["expected_terms"], qid
            assert question["expected_evidence_ids"], qid
            assert gold_by_question[qid], qid
            assert set(question["expected_evidence_ids"]) == {
                item["evidence_id"] for item in gold_by_question[qid]
            }
        else:
            assert question["expected_terms"] == [], qid
            assert question["expected_evidence_ids"] == [], qid
            assert gold_by_question[qid] == [], qid


def test_gold_evidence_is_not_expected_terms_derived() -> None:
    forbidden = {"expected_terms", "required_terms", "derived_from_expected_terms"}

    for item in _gold():
        assert forbidden.isdisjoint(item)


def test_distractor_sensitive_question_count_is_sufficient() -> None:
    questions = _questions()

    count = sum(
        1
        for question in questions
        if question.get("distractor_sensitive")
        or question.get("question_type") == "similar_clause_disambiguation"
    )
    assert count >= 8
    assert any(question["difficulty"] == "hard" for question in questions)


def test_multi_chunk_questions_have_multiple_required_evidence_items() -> None:
    questions = {row["question_id"]: row for row in _questions()}
    gold_by_question: dict[str, list[dict]] = defaultdict(list)
    for item in _gold():
        gold_by_question[item["question_id"]].append(item)

    multi_questions = [
        row for row in questions.values() if row["question_type"] == "multi_chunk_synthesis"
    ]
    assert len(multi_questions) >= 7
    for question in multi_questions:
        required = [item for item in gold_by_question[question["question_id"]] if item["required"]]
        assert len(required) > 1, question["question_id"]
        assert {item["support_type"] for item in required} == {"multi_chunk"}


def test_table_and_mixed_language_coverage_is_sufficient() -> None:
    questions = _questions()
    table_questions = [row for row in questions if row["question_type"] == "table_structured_data"]
    mixed_questions = [row for row in questions if row["question_type"] == "mixed_language"]

    assert len(table_questions) >= 5
    assert len(mixed_questions) >= 5
    for question in mixed_questions:
        combined = question["question"] + " " + question["expected_answer"]
        assert any("가" <= char <= "힣" for char in combined)
        assert any(("A" <= char <= "Z") or ("a" <= char <= "z") for char in combined)


def test_gold_support_text_is_present_in_configured_chunks() -> None:
    summary = _summary()
    assert summary["gold_evidence_summary"]["num_evidence_records"] == 47
    assert summary["coverage_summary"]["page_metadata_gold_coverage"] == 1.0

    config_path = repo_path("configs/eval/benchmark_naive_rag_v1.yaml")
    assert config_path == CONFIG
