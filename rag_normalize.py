"""Korean money / date normalizer utilities.

Additive module — does not yet wire into the rag_core query path. It is
imported by Korean RFP per-axis eval work (issue #126) to compare
normalized vs un-normalized retrieval / extraction outcomes. Keeping the
parsing in its own module lets tests exercise it without spinning up
the full RAG pipeline.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional


# Sino-Korean numerals as single-digit multipliers.
_SINO_DIGITS: dict[str, int] = {
    "영": 0, "공": 0,
    "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5,
    "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9,
}

# Big scales reset the small-number accumulator into the running total.
_BIG_SCALES: dict[str, Decimal] = {
    "조": Decimal("1000000000000"),
    "억": Decimal("100000000"),
    "만": Decimal("10000"),
}

# Small scales multiply the most recent leading digit and feed the small
# accumulator. They never reset the running total on their own.
_SMALL_SCALES: dict[str, Decimal] = {
    "천": Decimal(1000),
    "백": Decimal(100),
    "십": Decimal(10),
}

_CURRENCY_PREFIX_RE = re.compile(r"^\s*일금\s*")
_CURRENCY_SUFFIX_RE = re.compile(r"\s*원\s*$")
_PURE_NUMERIC_RE = re.compile(r"^\s*[\d][\d.,]*\s*$")
_NUMERIC_TOKEN_RE = re.compile(r"[\d][\d.,]*|[영공일이삼사오육륙칠팔구]")
_SCALE_TOKEN_RE = re.compile(r"조|억|만|천|백|십")


def normalize_currency(text: str) -> Optional[Decimal]:
    """Parse a Korean currency expression into a Decimal won amount.

    Supported shapes:
      - Pure digits with separators: ``"10,000,000원"`` → ``Decimal("10000000")``
      - Scale words: ``"1억원"`` / ``"3억5천만원"`` / ``"3,500만원"``
      - Sino-Korean digit as multiplier: ``"삼억원"`` → ``Decimal("300000000")``
      - Optional ``일금`` prefix and ``원`` suffix
      - Decimal scales: ``"1.5억원"`` → ``Decimal("150000000")``

    Returns ``None`` when the text cannot be parsed as currency.
    """
    if not text:
        return None
    s = _CURRENCY_PREFIX_RE.sub("", text)
    s = _CURRENCY_SUFFIX_RE.sub("", s).strip()
    if not s:
        return None

    if _PURE_NUMERIC_RE.match(s):
        try:
            return Decimal(s.replace(",", ""))
        except InvalidOperation:
            return None

    return _parse_scale_expr(s)


def _parse_scale_expr(s: str) -> Optional[Decimal]:
    """Parse Korean scale expressions hierarchically.

    Korean scale words compose as ``<small> 만 <small> + small_word``,
    where 만/억/조 reset a section into the running total and
    천/백/십 multiply the most recent leading digit into a section
    accumulator. Walking left-to-right:

      "5천만" → digit 5, ×천 → section 5000, ×만 → total 50_000_000.
    """
    total = Decimal(0)
    section = Decimal(0)
    pending: Optional[Decimal] = None
    remaining = s
    progressed = False

    while remaining:
        remaining = remaining.lstrip()
        if not remaining:
            break

        num_match = _NUMERIC_TOKEN_RE.match(remaining)
        if num_match:
            token = num_match.group(0)
            if token in _SINO_DIGITS:
                value: Decimal = Decimal(_SINO_DIGITS[token])
            else:
                try:
                    value = Decimal(token.replace(",", ""))
                except InvalidOperation:
                    return None
            if pending is not None:
                section += pending
            pending = value
            remaining = remaining[num_match.end():]
            progressed = True
            continue

        scale_match = _SCALE_TOKEN_RE.match(remaining)
        if scale_match:
            word = scale_match.group(0)
            if word in _SMALL_SCALES:
                multiplier = _SMALL_SCALES[word]
                section += (pending if pending is not None else Decimal(1)) * multiplier
                pending = None
            else:
                multiplier = _BIG_SCALES[word]
                segment = section + (pending if pending is not None else Decimal(0))
                if segment == 0:
                    segment = Decimal(1)
                total += segment * multiplier
                section = Decimal(0)
                pending = None
            remaining = remaining[scale_match.end():]
            progressed = True
            continue

        return None

    if pending is not None:
        section += pending
    total += section
    return total if progressed and total > 0 else None


# --- Date ---

_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # YYYY년 M월 D일 — full Korean form, optional 일 suffix and whitespace.
    re.compile(r"(?P<y>\d{4})\s*년\s*(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일?"),
    # YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD with digit-boundary guards.
    re.compile(r"(?<!\d)(?P<y>\d{4})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})(?!\d)"),
    # 'YY.M.D, 'YY-M-D — explicit apostrophe prefix to disambiguate.
    re.compile(r"[\'‘’](?P<y2>\d{2})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})(?!\d)"),
)


def normalize_date(text: str, *, century_pivot: int = 2000) -> Optional[date]:
    """Parse a Korean date expression into a ``datetime.date``.

    Supported shapes:
      - ``YYYY-MM-DD`` / ``YYYY/MM/DD`` / ``YYYY.MM.DD``
      - ``YYYY년 M월 D일`` (with or without trailing 일)
      - ``'YY.M.D`` style 2-digit year (resolved as ``century_pivot + YY``)

    Returns ``None`` when no recognizable date is found, or when the
    matched fields don't form a real calendar date.
    """
    if not text:
        return None
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groupdict()
        year = (
            int(groups["y"]) if groups.get("y") is not None
            else century_pivot + int(groups["y2"])
        )
        try:
            return date(year, int(groups["m"]), int(groups["d"]))
        except ValueError:
            return None
    return None
