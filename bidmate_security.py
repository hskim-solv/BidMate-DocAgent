"""Lightweight security screening for the BidMate-DocAgent surface.

Two pure-regex helpers — query-side prompt-injection screening and
text-side PII redaction. Designed as a leaf utility: no imports from
rag_core / ingestion / api, no I/O, no model loading, no third-party
SDKs. The detection is deterministic and never raises (ADR 0028 mirror
of ADR 0011 / 0013 additive-opt-in pattern but simpler — the screen is
diagnostic-only and the PII redaction is gated at the call site).
"""

from __future__ import annotations

import re
from typing import TypedDict

# Korean RFP-domain prompt-injection patterns. The phrasing is specific
# enough that false positives on real RFP text are unlikely; each
# pattern targets a *directive* shape rather than a topical keyword.
_KOREAN_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ko-ignore-prior",
        re.compile(
            r"이전\s*(지시|답변|시스템\s*(프롬프트|지시))[^\n]*?(무시|삭제|폐기|잊)"
        ),
    ),
    (
        "ko-bypass-agency",
        re.compile(r"발주\s*기관[^\n]*?(무시|상관\s*없|상관없)"),
    ),
    (
        "ko-reveal-system",
        re.compile(
            r"(시스템\s*프롬프트|숨겨진\s*(규칙|지시|프롬프트))[^\n]*?(공개|드러내|보여)"
        ),
    ),
    (
        "ko-role-override",
        re.compile(r"(역할|페르소나|기본\s*규칙)[^\n]*?(잊|재설정|바꿔|버려)"),
    ),
    (
        "ko-rating-injection",
        re.compile(r"이\s*문서[^\n]*?(평가\s*기준|점수)[^\n]*?(만점|최고|일등)"),
    ),
)

# General English injection patterns.
_ENGLISH_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "en-ignore-prior",
        re.compile(
            r"ignore\s+(?:previous|prior|all)\s+(?:instruction|prompt|answer|system)",
            re.IGNORECASE,
        ),
    ),
    (
        "en-reveal-system",
        re.compile(
            r"(?:reveal|show|print)\s+(?:the\s+)?(?:system|hidden|internal)\s+prompt",
            re.IGNORECASE,
        ),
    ),
    (
        "en-forget-context",
        re.compile(
            r"forget\s+(?:everything|all\s+context|the\s+rules)",
            re.IGNORECASE,
        ),
    ),
)

# PII redaction patterns. Each replaces a match with a stable token
# that contains no PII characters → applying redact_pii twice yields
# the same result as applying it once (idempotent by construction).
#
# Order matters: RRN (13 digits) must be applied before phone (10-11
# digits) because the phone pattern can otherwise eat the trailing
# 10-11 digits of an RRN and leave the leading 2-3 digits visible.
# `\b` word boundaries at both ends of the phone pattern provide
# defense-in-depth — they prevent the phone regex from matching
# *inside* a longer numeric run even if RRN ordering changes.
_PII_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # 주민등록번호: 6-digit DOB, optional dash, 7-digit suffix whose
    # first digit is 1-4 (sex + century marker).
    (re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b"), "<rrn>"),
    # Korean mobile phone: 010/011/016/017/018/019 prefix with
    # optional dash or whitespace separators. Three or four mid-digits
    # to cover both 010-3-4 and 010-4-4 formats. `\b` at both ends so
    # the pattern does not match inside a longer digit run.
    (re.compile(r"\b01[016789][-\s]?\d{3,4}[-\s]?\d{4}\b"), "<phone>"),
    # Email — RFC-ish, deliberately conservative.
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "<email>"),
)


class InjectionScreenResult(TypedDict):
    status: str  # "passed" | "flagged"
    patterns: list[str]


def screen_query(query: str) -> InjectionScreenResult:
    """Screen a user query for prompt-injection patterns.

    Returns a result dict with `status` ("passed" | "flagged") and
    `patterns` listing the labels of matched patterns. Detection is
    diagnostic-only — callers decide whether to block, log, or pass
    through. The screening is deterministic, never raises, and accepts
    any string (including empty).
    """
    if not query:
        return {"status": "passed", "patterns": []}
    matched: list[str] = []
    for label, pat in _KOREAN_INJECTION_PATTERNS:
        if pat.search(query):
            matched.append(label)
    for label, pat in _ENGLISH_INJECTION_PATTERNS:
        if pat.search(query):
            matched.append(label)
    return {
        "status": "flagged" if matched else "passed",
        "patterns": matched,
    }


def redact_pii(text: str) -> str:
    """Replace Korean phone / email / RRN with stable tokens.

    Designed for opt-in ingestion-time use under
    `BIDMATE_INGEST_REDACT_PII=true`. The function is idempotent —
    the replacement tokens (`<phone>`, `<email>`, `<rrn>`) contain
    no characters matched by any pattern, so successive applications
    leave the result unchanged.
    """
    if not text:
        return text
    for pat, token in _PII_PATTERNS:
        text = pat.sub(token, text)
    return text
