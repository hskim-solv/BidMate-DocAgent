#!/usr/bin/env python3
"""Korean money/date text normalizer for retrieval-time and verification-time use.

Korean RFP documents (나라장터) routinely express the same value in multiple
scripts within a single document — `1,500,000,000` / `15억` / `일금일십오억원정`
/ `壹拾伍億元` may all refer to the same amount. The naive substring match in
`rag_core.verify_evidence` cannot bridge these forms.

This module supplies a small canonical-form rewriter applied at query-rewrite
and verification time (NOT at ingestion — that would force a full reindex,
ruled out by issue #170).

The contract is strictly additive: callers pair this module's `expand_forms`
with their existing substring checks, so every match that worked before still
works. Approximate spans (`약 5천만원`, `5천만정도`) are *augmented* with their
canonical form rather than replaced, preserving the approximation qualifier.

See `tests/test_text_normalize_regression.py` for the canonical case table
including the `반올림` false-positive guard.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from typing import NamedTuple


# ── Digit / power tables ─────────────────────────────────────────────────────

_HANGUL_DIGIT_MAP: dict[str, int] = {
    "영": 0, "공": 0,
    "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5,
    "육": 6, "칠": 7, "팔": 8, "구": 9,
}

_HANJA_DIGIT_MAP: dict[str, int] = {
    "壹": 1, "貳": 2, "叄": 3, "肆": 4, "伍": 5,
    "陸": 6, "柒": 7, "捌": 8, "玖": 9,
}

_DIGITS_ALL = {**_HANGUL_DIGIT_MAP, **_HANJA_DIGIT_MAP}

_SUBUNIT_MAP: dict[str, int] = {
    "십": 10, "拾": 10,
    "백": 100, "佰": 100, "百": 100,
    "천": 1000, "仟": 1000, "千": 1000,
}

_SECTION_MAP: dict[str, int] = {
    "만": 10**4, "萬": 10**4,
    "억": 10**8, "億": 10**8,
    "조": 10**12, "兆": 10**12,
}

_ENVELOPE_STRIP = ("일금", "정", "원", "元", "圓")
_APPROX_PREFIX = ("약", "대략", "~")
_APPROX_SUFFIX = ("정도", "내외")


# ── Compiled regexes ────────────────────────────────────────────────────────

# A Korean number is structured as: (digit subunit?)+ optional section, repeated.
# The grammar below enforces "every myriad needs a section marker (만/억/조)" so
# random digit runs in non-money contexts don't get absorbed. A bare body
# without a section is only accepted when followed by a money-unit suffix.

_HANGUL_DIGIT_PART = r"(?:[\d,]+|[영공일이삼사오육칠팔구])"
_HANGUL_SUBUNIT_PART = r"[십백천]"
_HANGUL_SECTION_PART = r"[만억조]"

_HANGUL_MYRIAD_BODY = (
    rf"{_HANGUL_DIGIT_PART}\s*"
    rf"(?:{_HANGUL_SUBUNIT_PART}\s*{_HANGUL_DIGIT_PART}\s*)*"
    rf"{_HANGUL_SUBUNIT_PART}?"
)
_HANGUL_NUMBER_SECTIONED = (
    rf"(?:{_HANGUL_MYRIAD_BODY}\s*{_HANGUL_SECTION_PART}\s*)+"
)
# Trailing money-unit suffix. 정 must NOT be followed by 도 (그것은 '정도' approximation marker).
_HANGUL_MONEY_SUFFIX = r"(?:\s*원\s*정|\s*원|\s*정(?!도))"

_HANGUL_MONEY_RE = re.compile(
    r"(?:일금\s*)?"
    r"(?:"
    rf"{_HANGUL_NUMBER_SECTIONED}{_HANGUL_MONEY_SUFFIX}?"  # sectioned (anchor = section)
    r"|"
    rf"{_HANGUL_MYRIAD_BODY}{_HANGUL_MONEY_SUFFIX}"        # bare body (anchor = 원/정)
    r")"
)

_HANJA_DIGIT_PART = r"[壹貳叄肆伍陸柒捌玖]"
_HANJA_SUBUNIT_PART = r"[拾佰百仟千]"
_HANJA_SECTION_PART = r"[萬億兆]"

_HANJA_MYRIAD_BODY = (
    rf"{_HANJA_DIGIT_PART}\s*"
    rf"(?:{_HANJA_SUBUNIT_PART}\s*{_HANJA_DIGIT_PART}\s*)*"
    rf"{_HANJA_SUBUNIT_PART}?"
)
_HANJA_NUMBER_SECTIONED = (
    rf"(?:{_HANJA_MYRIAD_BODY}\s*{_HANJA_SECTION_PART}\s*)+"
)

_HANJA_MONEY_RE = re.compile(
    r"(?:"
    rf"{_HANJA_NUMBER_SECTIONED}(?:\s*[元圓])?"
    r"|"
    rf"{_HANJA_MYRIAD_BODY}\s*[元圓]"
    r")"
)

# Arabic with commas: require ≥2 commas (millions+) OR ≥1 comma followed by
# explicit 원. Single comma without 원 is too ambiguous (count vs. money).
_ARABIC_COMMA_MONEY_RE = re.compile(
    r"\b\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?(?:\s*원)?"
    r"|"
    r"\b\d{1,3},\d{3}\s*원"
)

# Approximation markers — checked against text around each money span.
_APPROX_PREFIX_RE = re.compile(r"(?:약|대략|~)\s*$")
_APPROX_SUFFIX_RE = re.compile(r"^\s*(?:정도|내외)")

# Date families.
_DATE_ISO_RE = re.compile(r"\b(\d{4})[-./](\d{1,2})[-./](\d{1,2})\.?")
_DATE_APOS_RE = re.compile(r"'(\d{2})\.(\d{1,2})\.(\d{1,2})\.?")
_DATE_HANGUL_FULL_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")
_DATE_HANGUL_MD_RE = re.compile(r"(?<!\d)(\d{1,2})월\s*(\d{1,2})일")


# ── Structured result types ─────────────────────────────────────────────────

class ParsedAmount(NamedTuple):
    raw: str
    value: int
    approximate: bool
    span: tuple[int, int]


class ParsedDate(NamedTuple):
    raw: str
    iso: str
    year_inferred: bool
    span: tuple[int, int]


# ── Internal helpers ────────────────────────────────────────────────────────

def _strip_envelopes(text: str) -> str:
    out = text
    for env in _ENVELOPE_STRIP:
        out = out.replace(env, "")
    return out.replace(" ", "").replace(",", "")


def _parse_korean_number(raw: str) -> int | None:
    """Parse a money span into its integer KRW value.

    Returns None for spans that aren't well-formed money (e.g. unknown
    characters, all-envelope, zero value). This is the second-line
    false-positive guard after the regex.
    """
    text = _strip_envelopes(raw)
    if not text:
        return None

    total = 0
    section = 0
    current = 0
    saw_input = False

    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isdigit():
            j = i
            while j < len(text) and text[j].isdigit():
                j += 1
            current = int(text[i:j])
            saw_input = True
            i = j
            continue
        if ch in _DIGITS_ALL:
            current = _DIGITS_ALL[ch]
            saw_input = True
            i += 1
            continue
        if ch in _SUBUNIT_MAP:
            mult = _SUBUNIT_MAP[ch]
            if current == 0 and not saw_input:
                current = 1
            section += current * mult
            current = 0
            saw_input = True
            i += 1
            continue
        if ch in _SECTION_MAP:
            mult = _SECTION_MAP[ch]
            if current:
                section += current
                current = 0
            if section == 0:
                section = 1
            total += section * mult
            section = 0
            saw_input = True
            i += 1
            continue
        return None

    if current:
        section += current
    if section:
        total += section
    return total if total > 0 else None


def _is_approximate(text: str, span: tuple[int, int]) -> bool:
    start, end = span
    prefix = text[max(0, start - 6):start]
    suffix = text[end:end + 6]
    if _APPROX_PREFIX_RE.search(prefix):
        return True
    if _APPROX_SUFFIX_RE.match(suffix):
        return True
    return False


def _resolve_year(yy: int, anchor_year: int | None) -> int:
    if anchor_year is None:
        anchor_year = datetime.date.today().year
    anchor_yy = anchor_year % 100
    century = (anchor_year // 100) * 100
    if yy <= anchor_yy + 5:
        return century + yy
    return century - 100 + yy


def _valid_md(month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= 31


# ── Public API ──────────────────────────────────────────────────────────────

def parse_amounts(s: str) -> list[ParsedAmount]:
    """Extract money spans from s. Returns ParsedAmount entries sorted by span."""
    if not s:
        return []

    candidates: list[tuple[int, int]] = []
    for pattern in (_HANGUL_MONEY_RE, _HANJA_MONEY_RE, _ARABIC_COMMA_MONEY_RE):
        for m in pattern.finditer(s):
            candidates.append(m.span())
    if not candidates:
        return []

    # Prefer longer matches starting at the same position; then drop overlaps.
    candidates.sort(key=lambda sp: (sp[0], -(sp[1] - sp[0])))
    accepted: list[tuple[int, int]] = []
    last_end = -1
    for start, end in candidates:
        if start < last_end:
            continue
        accepted.append((start, end))
        last_end = end

    results: list[ParsedAmount] = []
    for start, end in accepted:
        raw = s[start:end].rstrip()
        # Trim trailing whitespace from span to keep approximation-suffix
        # detection accurate.
        end = start + len(raw)
        value = _parse_korean_number(raw)
        if value is None or value == 0:
            continue
        approximate = _is_approximate(s, (start, end))
        results.append(ParsedAmount(raw=raw, value=value, approximate=approximate, span=(start, end)))
    return results


def parse_dates(s: str, anchor_year: int | None = None) -> list[ParsedDate]:
    """Extract date spans from s. Returns ParsedDate entries sorted by span.

    Year-less `M월 D일` is parsed only when anchor_year is supplied. Two-digit
    years use a rolling +5 window around anchor (default: today's year).
    """
    if not s:
        return []

    found: list[ParsedDate] = []

    for m in _DATE_HANGUL_FULL_RE.finditer(s):
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not _valid_md(month, day):
            continue
        found.append(ParsedDate(
            raw=m.group(),
            iso=f"{year:04d}-{month:02d}-{day:02d}",
            year_inferred=False,
            span=m.span(),
        ))

    for m in _DATE_APOS_RE.finditer(s):
        yy, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not _valid_md(month, day):
            continue
        year = _resolve_year(yy, anchor_year)
        found.append(ParsedDate(
            raw=m.group(),
            iso=f"{year:04d}-{month:02d}-{day:02d}",
            year_inferred=True,
            span=m.span(),
        ))

    for m in _DATE_ISO_RE.finditer(s):
        # Skip if this span is already covered by an earlier match (e.g.
        # the digit prefix of `2026년 3월 15일` is not a separate ISO date).
        if any(_spans_overlap(m.span(), other.span) for other in found):
            continue
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not _valid_md(month, day):
            continue
        found.append(ParsedDate(
            raw=m.group(),
            iso=f"{year:04d}-{month:02d}-{day:02d}",
            year_inferred=False,
            span=m.span(),
        ))

    # Year-less M월 D일: only when anchor_year is supplied. Skip spans already
    # covered by YYYY년 M월 D일 matches.
    for m in _DATE_HANGUL_MD_RE.finditer(s):
        if any(_spans_overlap(m.span(), other.span) for other in found):
            continue
        if anchor_year is None:
            # Surface the span with empty iso so callers know it was seen.
            month, day = int(m.group(1)), int(m.group(2))
            if not _valid_md(month, day):
                continue
            found.append(ParsedDate(
                raw=m.group(), iso="", year_inferred=True, span=m.span(),
            ))
            continue
        month, day = int(m.group(1)), int(m.group(2))
        if not _valid_md(month, day):
            continue
        found.append(ParsedDate(
            raw=m.group(),
            iso=f"{anchor_year:04d}-{month:02d}-{day:02d}",
            year_inferred=True,
            span=m.span(),
        ))

    found.sort(key=lambda p: p.span[0])
    return found


def normalize_text(s: str, anchor_year: int | None = None) -> str:
    """Rewrite money/date spans in s to canonical form.

    Money:
    - Literal amounts: span replaced with the integer literal (`5천만원` →
      `50000000`).
    - Approximate amounts: canonical form *appended* in `[≈N]` brackets so
      the qualifier survives (`약 5천만원` → `약 5천만원 [≈50000000]`).

    Dates:
    - Canonicalized to ISO `YYYY-MM-DD`. Year-less `M월 D일` left unchanged
      unless anchor_year is supplied.
    """
    if not s:
        return s

    s = unicodedata.normalize("NFC", s)
    amounts = parse_amounts(s)
    dates = parse_dates(s, anchor_year=anchor_year)

    spans: list[tuple[int, int, str]] = []
    for a in amounts:
        if a.approximate:
            spans.append((a.span[0], a.span[1], f"{a.raw} [≈{a.value}]"))
        else:
            spans.append((a.span[0], a.span[1], str(a.value)))
    for d in dates:
        if d.iso:
            spans.append((d.span[0], d.span[1], d.iso))

    if not spans:
        return s

    spans.sort(key=lambda x: x[0])
    out: list[str] = []
    cursor = 0
    for start, end, replacement in spans:
        if start < cursor:
            continue
        out.append(s[cursor:start])
        out.append(replacement)
        cursor = end
    out.append(s[cursor:])
    return "".join(out)


def expand_forms(s: str) -> list[str]:
    """Return [s, normalize_text(s)] deduped, stable order.

    Callers use this with substring matching for additive OR-match semantics —
    if the legacy form matched, the original is still in the list and matches
    identically.
    """
    if not s:
        return [s]
    normalized = normalize_text(s)
    if normalized == s:
        return [s]
    return [s, normalized]


def _spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]
