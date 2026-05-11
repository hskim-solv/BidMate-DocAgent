"""Korean RFP eval axes (issue #126).

Heuristic per-axis detector over query / gold-answer / must-include /
acceptable-aliases strings. The detector is intentionally regex-based
and pandas-free so it can be exercised from the test suite without
spinning up the full pandas-backed evaluator.

A query row may carry zero, one, or multiple axes simultaneously — the
aggregation layer in :mod:`eval.evaluate_dev_results` reports each
axis independently.
"""

from __future__ import annotations

import re
from typing import List, Mapping


KO_AXIS_CURRENCY = "금액단위"
KO_AXIS_DATE = "날짜형식"
KO_AXIS_HANJA = "한자"
KO_AXIS_PROJECT_NUMBER = "사업번호"
KO_AXIS_ABBREVIATION = "약칭"

KO_AXES: tuple[str, ...] = (
    KO_AXIS_CURRENCY,
    KO_AXIS_DATE,
    KO_AXIS_HANJA,
    KO_AXIS_PROJECT_NUMBER,
    KO_AXIS_ABBREVIATION,
)

_DETECT_FIELDS: tuple[str, ...] = (
    "question",
    "gold_answer",
    "must_include",
    "acceptable_aliases",
)

_CURRENCY_RE = re.compile(
    r"(\d[\d,]*\s*원|일금|\d+\s*[억만천백]\s*[원만천]?|[일이삼사오육칠팔구]\s*[억만천]\s*원?)"
)
_DATE_RE = re.compile(
    r"(\d{4}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{1,2}|\d{4}\s*년\s*\d{1,2}\s*월|\d{1,3}\s*일\b|[\'‘’]\d{2}\s*[-./]\s*\d{1,2})"
)
_HANJA_RE = re.compile(r"[㐀-䶿一-鿿]")
_PROJECT_NUMBER_RE = re.compile(
    r"\[[가-힣A-Za-z]+\]|사업번호|입찰공고|사전공개|[A-Z0-9]{2,}-[A-Z0-9][A-Z0-9-]*"
)
_ABBREVIATION_RE = re.compile(r"\([A-Z]{2,6}\)|\b[A-Z]{2,6}\b\s*(?:구축|시스템|사업)")


def detect_ko_axes(row: Mapping[str, object]) -> List[str]:
    """Detect which Korean RFP eval axes apply to a query row.

    Reads ``question`` / ``gold_answer`` / ``must_include`` /
    ``acceptable_aliases`` if present. Returns the axes that match in
    :data:`KO_AXES` declaration order. Empty list when no axis applies.
    """
    haystack = " ".join(str(row.get(field) or "") for field in _DETECT_FIELDS)
    detected: List[str] = []
    if _CURRENCY_RE.search(haystack):
        detected.append(KO_AXIS_CURRENCY)
    if _DATE_RE.search(haystack):
        detected.append(KO_AXIS_DATE)
    if _HANJA_RE.search(haystack):
        detected.append(KO_AXIS_HANJA)
    if _PROJECT_NUMBER_RE.search(haystack):
        detected.append(KO_AXIS_PROJECT_NUMBER)
    if _ABBREVIATION_RE.search(haystack):
        detected.append(KO_AXIS_ABBREVIATION)
    return detected
