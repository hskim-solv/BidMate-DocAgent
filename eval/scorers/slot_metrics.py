"""Slot-exactness scorer for numeric/date/condition RFP fields.

This is a deterministic eval-only helper. It measures whether expected
slot-like terms are present in the generated answer or retrieved evidence after
the same Korean amount/date normalization used by the verifier. It does not
read private labels beyond the existing per-case expected terms.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from text_normalize import expand_forms, normalize_text, parse_amounts, parse_dates


SLOT_TYPES: tuple[str, ...] = ("amount", "date", "numeric_or_score", "condition")

_NUMERIC_RE = re.compile(r"\d")
_SCORE_RE = re.compile(r"(?:점|배점|평점|score|percent|%)", re.IGNORECASE)
_CONDITION_RE = re.compile(
    r"(?:조건|자격|요건|기준|제출|마감|기간|일정|deadline|eligibility|requirement|condition)",
    re.IGNORECASE,
)


def classify_slot_term(term: Any) -> str | None:
    """Return the slot type for an expected term, or None if not slot-like."""
    text = str(term or "").strip()
    if not text:
        return None
    if parse_amounts(text):
        return "amount"
    if any(parsed.iso for parsed in parse_dates(text, anchor_year=None)):
        return "date"
    if _NUMERIC_RE.search(text):
        return "numeric_or_score"
    if _SCORE_RE.search(text):
        return "numeric_or_score"
    if _CONDITION_RE.search(text):
        return "condition"
    return None


def _term_matches(term: str, haystack: str, normalized_haystack: str) -> bool:
    needle = term.strip()
    if not needle:
        return False
    haystack_lower = haystack.lower()
    for form in expand_forms(needle.lower()):
        if form and form in haystack_lower:
            return True
        normalized = normalize_text(form)
        if normalized and normalized in normalized_haystack:
            return True
    return False


def score_numeric_date_condition_slots(
    expected_terms: list[str],
    answer_and_evidence_text: str,
) -> dict[str, Any]:
    """Score slot-like expected terms against answer + evidence text.

    ``numeric_date_condition_accuracy`` is None when the case has no
    slot-like expected terms, so run-level means skip non-applicable cases.
    Type counts are aggregate-safe enum counters.
    """
    slots: list[tuple[str, str]] = []
    for term in expected_terms:
        slot_type = classify_slot_term(term)
        if slot_type is not None:
            slots.append((str(term), slot_type))

    if not slots:
        return {
            "numeric_date_condition_accuracy": None,
            "numeric_date_condition_slot_count": 0,
            "numeric_date_condition_type_counts": {},
            "numeric_date_condition_type_correct_counts": {},
        }

    normalized_haystack = normalize_text(answer_and_evidence_text.lower())
    type_counts: Counter[str] = Counter()
    type_correct: Counter[str] = Counter()
    correct = 0
    for term, slot_type in slots:
        type_counts[slot_type] += 1
        if _term_matches(term, answer_and_evidence_text, normalized_haystack):
            correct += 1
            type_correct[slot_type] += 1

    return {
        "numeric_date_condition_accuracy": correct / len(slots),
        "numeric_date_condition_slot_count": len(slots),
        "numeric_date_condition_type_counts": {
            key: int(type_counts[key]) for key in SLOT_TYPES if type_counts.get(key)
        },
        "numeric_date_condition_type_correct_counts": {
            key: int(type_correct[key]) for key in SLOT_TYPES if type_correct.get(key)
        },
    }
