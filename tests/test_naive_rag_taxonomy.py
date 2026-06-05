from eval.naive_rag.taxonomy import classify_failure, count_failures


def test_classify_failure_prioritizes_retrieval_then_secondary_answer_labels() -> None:
    primary, labels = classify_failure(
        question={"answerable": True},
        gold_chunk_ids=["gold-1"],
        retrieved_chunk_ids=["other-1"],
        cited_chunk_ids=[],
        retrieval_metrics={"recall_at_10": 0.0, "recall_at_5": 0.0},
        answer_metrics={"citation_accuracy": 0.0, "answer_relevancy": 0.0, "hallucination_flag": 1},
    )

    assert primary == "retrieval_failure.gold_evidence_not_in_top_k"
    assert labels == [
        "retrieval_failure.gold_evidence_not_in_top_k",
        "citation_failure.insufficient_citation",
        "answer_failure.partial_answer",
        "answer_failure.hallucinated_requirement",
    ]


def test_classify_failure_labels_failed_abstention_for_unanswerable_case() -> None:
    primary, labels = classify_failure(
        question={"answerable": False},
        gold_chunk_ids=[],
        retrieved_chunk_ids=[],
        cited_chunk_ids=[],
        retrieval_metrics={},
        answer_metrics={"unanswerable_detection_flag": 0},
    )

    assert primary == "answer_failure.failed_to_abstain"
    assert labels == ["answer_failure.failed_to_abstain"]


def test_classify_failure_labels_partial_multi_chunk_retrieval() -> None:
    primary, labels = classify_failure(
        question={"answerable": True},
        gold_chunk_ids=["gold-1", "gold-2"],
        retrieved_chunk_ids=["gold-1"],
        cited_chunk_ids=["gold-1"],
        retrieval_metrics={"recall_at_10": 0.5, "recall_at_5": 0.5},
        answer_metrics={"citation_accuracy": 1.0, "answer_relevancy": 1.0},
    )

    assert primary == "retrieval_failure.multi_chunk_evidence_missing"
    assert labels == ["retrieval_failure.multi_chunk_evidence_missing"]


def test_count_failures_ignores_unknown_and_none_labels() -> None:
    counts = count_failures([
        "retrieval_failure.query_wording_mismatch",
        "retrieval_failure.query_wording_mismatch",
        "unknown.label",
        None,
    ])

    assert counts["retrieval_failure.query_wording_mismatch"] == 2
    assert "unknown.label" not in counts
    assert counts["answer_failure.failed_to_abstain"] == 0
