"""Failure taxonomy for the naive RAG evaluation contract."""
from __future__ import annotations

from collections import Counter
from typing import Any


RETRIEVAL_FAILURES = (
    "retrieval_failure.gold_evidence_not_in_top_k",
    "retrieval_failure.gold_evidence_ranked_too_low",
    "retrieval_failure.wrong_similar_clause",
    "retrieval_failure.chunk_boundary_split",
    "retrieval_failure.query_wording_mismatch",
    "retrieval_failure.multi_chunk_evidence_missing",
)

PARSING_FAILURES = (
    "parsing_failure.table_content_lost",
    "parsing_failure.figure_content_ignored",
    "parsing_failure.page_metadata_missing",
    "parsing_failure.header_footer_noise",
    "parsing_failure.korean_english_mixed_text_issue",
)

CITATION_FAILURES = (
    "citation_failure.correct_answer_wrong_citation",
    "citation_failure.insufficient_citation",
    "citation_failure.missing_page_number",
    "citation_failure.citation_does_not_support_claim",
    "citation_failure.vague_citation_for_multiple_claims",
)

ANSWER_FAILURES = (
    "answer_failure.hallucinated_requirement",
    "answer_failure.partial_answer",
    "answer_failure.overconfident_weak_evidence",
    "answer_failure.wrong_synthesis",
    "answer_failure.failed_to_abstain",
)

EVALUATION_FAILURES = (
    "evaluation_failure.no_gold_evidence",
    "evaluation_failure.metric_missing",
    "evaluation_failure.failure_case_not_saved",
)

ALL_FAILURE_TYPES = (
    *RETRIEVAL_FAILURES,
    *PARSING_FAILURES,
    *CITATION_FAILURES,
    *ANSWER_FAILURES,
    *EVALUATION_FAILURES,
)


def classify_failure(
    *,
    question: dict[str, Any],
    gold_chunk_ids: list[str],
    retrieved_chunk_ids: list[str],
    cited_chunk_ids: list[str],
    retrieval_metrics: dict[str, float | None],
    answer_metrics: dict[str, float | int | None],
) -> tuple[str | None, list[str]]:
    """Return the primary failure type plus additional deterministic labels.

    The classifier is intentionally simple. It labels observable failures in
    the current naive baseline without suggesting a retrieval improvement.
    """
    answerable = bool(question.get("answerable", True))
    labels: list[str] = []

    if answerable and not gold_chunk_ids:
        labels.append("evaluation_failure.no_gold_evidence")

    if answerable and gold_chunk_ids:
        recall10 = retrieval_metrics.get("recall_at_10")
        recall5 = retrieval_metrics.get("recall_at_5")
        if recall10 == 0.0:
            labels.append("retrieval_failure.gold_evidence_not_in_top_k")
        elif (
            isinstance(recall5, (int, float))
            and isinstance(recall10, (int, float))
            and recall5 < recall10
        ):
            labels.append("retrieval_failure.gold_evidence_ranked_too_low")
        elif len(gold_chunk_ids) > 1 and isinstance(recall10, (int, float)) and recall10 < 1.0:
            labels.append("retrieval_failure.multi_chunk_evidence_missing")

    if answerable:
        citation_accuracy = answer_metrics.get("citation_accuracy")
        if not cited_chunk_ids:
            labels.append("citation_failure.insufficient_citation")
        elif citation_accuracy == 0.0:
            if set(gold_chunk_ids) & set(retrieved_chunk_ids):
                labels.append("citation_failure.citation_does_not_support_claim")
            else:
                labels.append("citation_failure.correct_answer_wrong_citation")

        relevancy = answer_metrics.get("answer_relevancy")
        if relevancy == 0.0:
            labels.append("answer_failure.partial_answer")
        if answer_metrics.get("hallucination_flag") == 1:
            labels.append("answer_failure.hallucinated_requirement")
    else:
        if answer_metrics.get("unanswerable_detection_flag") == 0:
            labels.append("answer_failure.failed_to_abstain")

    primary = labels[0] if labels else None
    return primary, labels


def empty_failure_counts() -> dict[str, int]:
    return {failure_type: 0 for failure_type in ALL_FAILURE_TYPES}


def count_failures(failure_types: list[str | None]) -> dict[str, int]:
    counts = empty_failure_counts()
    observed = Counter(label for label in failure_types if label)
    for label, count in observed.items():
        if label in counts:
            counts[label] = count
    return counts
