"""Free-text data-boundary guard for the staging self-ship lane (ADR 0088).

Why this module exists
----------------------
ADR 0005 splits eval data into a *raw private* surface (local-only: RFP document
text, per-case question/answer/evidence) and an *aggregate* surface (commit-safe:
numbers, ratios, counts, provenance). The staging self-ship lane (ADR 0088) emits
**free text** that crosses the trust boundary: PR bodies, commit messages, and
external notification payloads. Those must never carry raw private content.

``scripts/_governance.py`` already scans for private leakage, but its scanners are
**JSON-structural** — ``find_redacted_summary_forbidden_fields`` is "intentionally
exact-key based" and ``find_eval_private_text`` walks a parsed JSON value. None of
them detect raw chunk text embedded in *free-text prose* (the #1144 failure mode:
raw per-case values surfaced inside an artifact that looked aggregate). This module
is therefore a **new free-text scanner**, not a reuse of the JSON scanners. The only
things reused from ``_governance.py`` are the constants ``PRIVATE_REDACTED_FORBIDDEN_KEYS``
and ``_ABSOLUTE_LOCAL_PATH_RE`` (and the Hangul detection idea).

Known limitation (honest)
-------------------------
Free-text classification of "raw vs aggregate" is undecidable in general. This
scanner reliably catches Korean RFP prose (Hangul density), doc/chunk identifiers,
absolute local paths, and per-case Q/A structure. It does **NOT** reliably catch
short *English* raw chunks with no identifiers. Therefore the external-notification
path MUST use ``allow_aggregate_only=True`` (numeric/aggregate allowlist), which
fails closed on anything that is not purely a metric — that is the real backstop,
not this heuristic. PR-body scanning is a defence-in-depth first line, never the
authority (per ADR 0088 the authority is the GitHub branch-protection CI check).
"""

from __future__ import annotations

import re
from typing import Final

try:  # reuse constants only (not the JSON scanners)
    from _governance import (  # type: ignore
        PRIVATE_REDACTED_FORBIDDEN_KEYS,
        _ABSOLUTE_LOCAL_PATH_RE,
    )
except ImportError:  # pragma: no cover - allow standalone import from repo root
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _governance import (  # type: ignore
        PRIVATE_REDACTED_FORBIDDEN_KEYS,
        _ABSOLUTE_LOCAL_PATH_RE,
    )


class RawPayloadViolation(ValueError):
    """Raised when free text appears to carry raw private RFP content."""


# Hangul code-point classes (mirrors _governance._EVAL_PRIVACY_HANGUL_RE).
_HANGUL_RE: Final = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏ꥠ-꥿]")

# doc_id / chunk_id style identifiers, e.g. "doc_id: rfp_2024_0312", "chunk_id=7".
_DOC_CHUNK_ID_RE: Final = re.compile(
    r"\b(?:doc[_-]?id|chunk[_-]?id|document_id)\b\s*[:=]", re.IGNORECASE
)
# Forbidden-key JSON-ish fragments embedded in prose, e.g. '"question":', "answer=".
_FORBIDDEN_KEY_FRAGMENT_RE: Final = re.compile(
    r"""["']?(%s)["']?\s*[:=]"""
    % "|".join(sorted(re.escape(k) for k in PRIVATE_REDACTED_FORBIDDEN_KEYS)),
    re.IGNORECASE,
)
# Per-case Q/A structure markers (both Korean and English forms).
_QA_STRUCTURE_RE: Final = re.compile(
    r"(질문\s*[:：]|답변\s*[:：]|근거\s*[:：]|\bQ\s*[:.]\s|\bA\s*[:.]\s)",
)

# A short metric/aggregate token is fine; this many Hangul chars in one payload is
# treated as prose (raw) rather than an incidental label.
_HANGUL_PROSE_THRESHOLD: Final = 12

# Aggregate-only allowlist of *alphabetic* words that may appear alongside numbers
# on the external-notification path. Tokens containing a digit (metrics, hashes,
# versions like ``abc123``/``p99``/``cap=5``) are allowed automatically. Any pure
# alphabetic word NOT in this set fails closed — that is what blocks prose.
_AGGREGATE_WORDS: Final[frozenset[str]] = frozenset(
    {
        "pr", "prs", "merge", "merged", "merges", "merging",
        "revert", "reverts", "reverted", "task", "tasks",
        "day", "days", "hour", "hours", "count", "total", "ratio", "rate",
        "recall", "precision", "f1", "citation", "citations", "grounding",
        "latency", "ms", "sec", "secs", "second", "seconds",
        "green", "red", "pass", "passed", "passes", "fail", "failed", "fails",
        "false", "true", "halt", "halted", "shipped", "ship",
        "breaker", "cap", "cost", "credit", "credits", "token", "tokens",
        "cycle", "cycles", "status", "ok", "insufficient", "partial", "supported",
        "ci", "sla", "throughput", "blocked", "blocker", "blockers",
        "summary", "aggregate", "provenance", "head", "run", "runs",
        "docs", "doc", "cases", "case", "main", "integration", "none",
        "avg", "mean", "median", "min", "max", "std", "stddev", "pending",
        "error", "errors", "warning", "warnings", "gate", "lane", "mode",
        "and", "of", "per", "with", "at", "on", "in", "to",
        "k", "n", "x",  # metric single-letters: recall@k, n cases, 3x
    }
)
# A token is "alphabetic-only" (must be an allowed word) iff it has no digit.
_HAS_DIGIT_RE: Final = re.compile(r"\d")


def _looks_like_aggregate_only(text: str) -> bool:
    """True iff *text* is aggregate (numbers/metrics) with no prose, ids, or paths."""
    if _HANGUL_RE.search(text):
        return False
    if _ABSOLUTE_LOCAL_PATH_RE.search(text):
        return False
    if _DOC_CHUNK_ID_RE.search(text) or _FORBIDDEN_KEY_FRAGMENT_RE.search(text):
        return False
    # Every alphabetic word adjacent to no digit must be a known aggregate word.
    # Split on non-alphanumeric so "cap=5" -> ["cap", "5"], "abc123" stays one token.
    for token in re.split(r"[^0-9A-Za-z]+", text):
        if not token or _HAS_DIGIT_RE.search(token):
            continue  # numeric / hash / version token: allowed
        if token.lower() not in _AGGREGATE_WORDS:
            return False
    return True


def _raw_indicators(text: str) -> list[str]:
    """Return the list of raw-content indicators found in *text* (empty == clean)."""
    found: list[str] = []
    if _ABSOLUTE_LOCAL_PATH_RE.search(text):
        found.append("absolute_local_path")
    if _DOC_CHUNK_ID_RE.search(text):
        found.append("doc_or_chunk_id")
    if _FORBIDDEN_KEY_FRAGMENT_RE.search(text):
        found.append("forbidden_key_fragment")
    if _QA_STRUCTURE_RE.search(text):
        found.append("per_case_qa_structure")
    if len(_HANGUL_RE.findall(text)) >= _HANGUL_PROSE_THRESHOLD:
        found.append("hangul_prose")
    return found


def assert_no_raw_payload(text: str | None, *, allow_aggregate_only: bool = False) -> None:
    """Raise :class:`RawPayloadViolation` if *text* may carry raw private content.

    Parameters
    ----------
    text:
        The free text about to cross the trust boundary (PR body, commit message,
        or — with ``allow_aggregate_only=True`` — an external notification payload).
    allow_aggregate_only:
        When ``True`` (REQUIRED for external notifications, ADR 0088 §5), the text
        must be *purely* numeric/aggregate. Anything that is not a metric fails
        closed. This is the authoritative backstop for the English-raw limitation;
        the heuristic indicators below are a defence-in-depth first line only.
    """
    if text is None:
        return
    if allow_aggregate_only:
        if not _looks_like_aggregate_only(text):
            raise RawPayloadViolation(
                "external payload is not aggregate-only (numbers/metrics); "
                "raw or prose content is forbidden on the notification path"
            )
        return
    indicators = _raw_indicators(text)
    if indicators:
        raise RawPayloadViolation(
            "free text appears to carry raw private content: "
            + ", ".join(indicators)
        )


def is_raw_payload(text: str | None, *, allow_aggregate_only: bool = False) -> bool:
    """Non-raising convenience wrapper around :func:`assert_no_raw_payload`."""
    try:
        assert_no_raw_payload(text, allow_aggregate_only=allow_aggregate_only)
    except RawPayloadViolation:
        return True
    return False
