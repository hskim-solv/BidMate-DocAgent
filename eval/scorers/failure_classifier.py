"""Rule-based normalized failure-mode classifier.

Consumes a ``case_result`` dict emitted by ``eval.scorers.case.score_case()``
and returns a normalized failure category (or ``None`` for successful cases).

ADR 0075 supersedes the original ADR 0059 7-category surface. The classifier
is still deterministic, still reads only aggregate-safe metric fields already
present in ``case_result``, and still avoids trace JSON or raw text
dependencies. The residual ``unknown`` bucket remains a fallback only.
"""
from __future__ import annotations

from typing import Any, Literal

FailureCategory = Literal[
    "retrieval_miss",
    "citation_or_page_metadata_issue",
    "verifier_false_negative",
    "verifier_false_positive",
    "answer_synthesis_issue",
    "abstention_failure",
    "evaluation_label_issue",
    "parse_or_metadata_issue",
    "unknown",
]

FAILURE_CATEGORIES: tuple[FailureCategory, ...] = (
    "retrieval_miss",
    "citation_or_page_metadata_issue",
    "verifier_false_negative",
    "verifier_false_positive",
    "answer_synthesis_issue",
    "abstention_failure",
    "evaluation_label_issue",
    "parse_or_metadata_issue",
    "unknown",
)

ANSWER_SYNTHESIS_ALIGNMENT_THRESHOLD = 0.5

_OK_METADATA_DECISIONS = {
    "",
    "accept",
    "accepted",
    "exact",
    "none",
    "not_applicable",
    "not_ambiguous",
    "resolved",
    "selected",
}
_METADATA_RETRY_REASON_PREFIXES = (
    "missing_comparison_doc",
    "missing_comparison_entity",
    "metadata_ambiguity",
    "metadata_missing",
    "metadata_not_found",
)
_BAD_CONTEXT_STATUSES = {"ambiguous", "failed", "missing", "unresolved"}
_BAD_CITATION_GROUNDING_CODES = {
    "page_missing",
    "page_mismatch",
    "region_unavailable",
    "region_misaligned",
}
_BAD_CITATION_COVERAGE_REASONS = {
    "missing_claim_citation",
    "page_metadata_missing",
    "region_metadata_missing",
    "no_citations",
}


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if item}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _is_less_than_one(value: Any) -> bool:
    numeric = _number(value)
    return numeric is not None and numeric < 1.0


def _has_gold_label(case_result: dict[str, Any]) -> bool:
    return bool(
        case_result.get("expected_doc_ids")
        or case_result.get("gold_chunk_ids")
        or case_result.get("gold_evidence")
    )


def _retrieved_chunk_ids(case_result: dict[str, Any]) -> set[str]:
    direct = _string_set(case_result.get("retrieved_chunk_ids"))
    if direct:
        return direct
    rows = case_result.get("retrieved_chunks") or []
    if not isinstance(rows, list):
        return set()
    return {
        str(row.get("chunk_id") or "")
        for row in rows
        if isinstance(row, dict) and row.get("chunk_id")
    }


def _has_label_issue(case_result: dict[str, Any], answerable: bool, abstained: bool) -> bool:
    if answerable and not _has_gold_label(case_result):
        return True
    if answerable and _number(case_result.get("accuracy")) is None:
        return True
    if not answerable and _number(case_result.get("abstention")) is None:
        return True
    if (
        answerable
        and bool(case_result.get("doc_match"))
        and bool(case_result.get("term_match"))
        and not abstained
        and case_result.get("accuracy") != 1.0
    ):
        return True
    return False


def _has_parse_or_metadata_issue(case_result: dict[str, Any]) -> bool:
    if bool(case_result.get("metadata_ambiguous")):
        return True

    decision = str(case_result.get("ambiguity_decision") or "").strip().lower()
    if decision and decision not in _OK_METADATA_DECISIONS:
        return True

    candidate_count = case_result.get("metadata_candidate_count")
    selected = case_result.get("metadata_selected_doc_ids")
    if isinstance(candidate_count, (int, float)) and candidate_count > 0 and not selected:
        return True

    context_status = str(case_result.get("context_resolution_status") or "").strip().lower()
    if context_status in _BAD_CONTEXT_STATUSES:
        return True

    source_format = str(case_result.get("case_source_format") or "").strip().lower()
    if source_format == "unknown":
        return True

    for reason in case_result.get("retry_trigger_reasons") or []:
        text = str(reason)
        if any(text.startswith(prefix) for prefix in _METADATA_RETRY_REASON_PREFIXES):
            return True

    return False


def _has_retrieval_miss(case_result: dict[str, Any], answerable: bool) -> bool:
    if not answerable:
        return False

    expected_doc_ids = _string_set(case_result.get("expected_doc_ids"))
    evidence_doc_ids = _string_set(case_result.get("evidence_doc_ids"))
    if expected_doc_ids and not expected_doc_ids.issubset(evidence_doc_ids):
        return True

    gold_chunk_ids = _string_set(case_result.get("gold_chunk_ids"))
    if gold_chunk_ids:
        retrieved = _retrieved_chunk_ids(case_result)
        recall10 = _number(case_result.get("chunk_recall_at_10"))
        if recall10 == 0.0 and not (gold_chunk_ids & retrieved):
            return True

    return False


def _has_citation_or_page_issue(case_result: dict[str, Any], answerable: bool) -> bool:
    if not answerable:
        return False
    if bool(case_result.get("abstained")):
        return False

    doc_match = bool(case_result.get("doc_match"))
    evidence_doc_ids = _string_set(case_result.get("evidence_doc_ids"))
    expected_doc_ids = _string_set(case_result.get("expected_doc_ids"))
    has_expected_evidence = doc_match or bool(expected_doc_ids & evidence_doc_ids)
    if not has_expected_evidence:
        return False

    if case_result.get("citation_term_match") is False:
        return True

    for key in (
        "citation_precision",
        "citation_page_precision",
        "citation_region_precision",
        "citation_claim_coverage",
        "citation_page_coverage",
        "citation_region_coverage",
    ):
        if _is_less_than_one(case_result.get(key)):
            return True

    for error in case_result.get("citation_grounding_errors") or []:
        if isinstance(error, dict) and error.get("code") in _BAD_CITATION_GROUNDING_CODES:
            return True

    for key in (
        "citation_claim_coverage_reason",
        "citation_page_coverage_reason",
        "citation_region_coverage_reason",
    ):
        if str(case_result.get(key) or "") in _BAD_CITATION_COVERAGE_REASONS:
            return True

    return False


def _has_answer_synthesis_issue(case_result: dict[str, Any], answerable: bool) -> bool:
    if not answerable or bool(case_result.get("abstained")):
        return False

    cca = _number(case_result.get("claim_citation_alignment"))
    if cca is not None and cca < ANSWER_SYNTHESIS_ALIGNMENT_THRESHOLD:
        return True

    if _is_less_than_one(case_result.get("answer_format_compliance")):
        return True

    doc_match = bool(case_result.get("doc_match"))
    citation_term_match = bool(case_result.get("citation_term_match"))
    if doc_match and citation_term_match and case_result.get("term_match") is False:
        return True
    if doc_match and citation_term_match and case_result.get("accuracy") != 1.0:
        return True

    return False


def is_failed(case_result: dict[str, Any]) -> bool:
    """Return True when this case_result represents a failure worth classifying."""
    answerable = case_result.get("answerable", True)
    if answerable:
        return case_result.get("accuracy") != 1.0
    abstained = bool(case_result.get("abstained"))
    has_evidence = bool(case_result.get("evidence_doc_ids"))
    return not (abstained and not has_evidence)


def classify_failure(case_result: dict[str, Any]) -> FailureCategory | None:
    """Return a normalized label for a failed case, or ``None`` for successes."""
    if not is_failed(case_result):
        return None

    answerable = bool(case_result.get("answerable", True))
    abstained = bool(case_result.get("abstained"))
    expected_doc_ids = _string_set(case_result.get("expected_doc_ids"))
    evidence_doc_ids = _string_set(case_result.get("evidence_doc_ids"))
    citation_term_match = bool(case_result.get("citation_term_match"))

    if _has_label_issue(case_result, answerable, abstained):
        return "evaluation_label_issue"

    if not answerable and not abstained:
        return "verifier_false_negative"

    if (
        answerable
        and abstained
        and expected_doc_ids
        and expected_doc_ids.issubset(evidence_doc_ids)
        and citation_term_match
    ):
        return "verifier_false_positive"

    if not answerable and abstained and evidence_doc_ids:
        return "abstention_failure"

    if answerable and abstained and expected_doc_ids and bool(expected_doc_ids & evidence_doc_ids):
        return "abstention_failure"

    if _has_parse_or_metadata_issue(case_result):
        return "parse_or_metadata_issue"

    if _has_retrieval_miss(case_result, answerable):
        return "retrieval_miss"

    if _has_citation_or_page_issue(case_result, answerable):
        return "citation_or_page_metadata_issue"

    if _has_answer_synthesis_issue(case_result, answerable):
        return "answer_synthesis_issue"

    return "unknown"


def aggregate_failure_categories(case_results: list[dict[str, Any]]) -> dict[str, int]:
    """Return ``{category: count}`` for the normalized taxonomy."""
    counts: dict[str, int] = {category: 0 for category in FAILURE_CATEGORIES}
    for case_result in case_results:
        category = classify_failure(case_result)
        if category is None:
            continue
        counts[category] += 1
    return counts
