"""Regression tests locking in sentence_split() golden behaviour for Korean edge cases.

SENTENCE_RE = r"(?<=[.!?。])\\s+" — splits only at punctuation followed by whitespace,
so decimals and bracket-abbreviations that lack a trailing space stay intact.
"""

import pytest

from rag_text_processing import sentence_split


# ---------------------------------------------------------------------------
# Corporate-prefix abbreviations
# ---------------------------------------------------------------------------

def test_abbreviation_bracket_prefix():
    # "(주)" is a bracket abbreviation, not a sentence-boundary punctuation char.
    # The "." after the first sentence is followed by a space, so it does split.
    text = "(주)가나다는 입찰에 참여한다. 마감은 5월이다."
    assert sentence_split(text) == ["(주)가나다는 입찰에 참여한다.", "마감은 5월이다."]


def test_abbreviation_jusikhwesa_inline():
    # "주식회사" in the middle of a sentence — no punctuation boundary here.
    text = "주식회사 ABC는 낙찰자이다. 계약 기간은 180일이다."
    assert sentence_split(text) == ["주식회사 ABC는 낙찰자이다.", "계약 기간은 180일이다."]


# ---------------------------------------------------------------------------
# Decimal numbers and unit suffixes
# ---------------------------------------------------------------------------

def test_decimal_not_split():
    # "3.14억원" — decimal point has no trailing whitespace → not a boundary.
    text = "보증금은 3.14억원이다. 추가로 1.5%를 납부한다."
    assert sentence_split(text) == [
        "보증금은 3.14억원이다.",
        "추가로 1.5%를 납부한다.",
    ]


def test_decimal_in_list():
    # Multiple decimal values in a single sentence.
    text = "단가는 각각 2.5억원, 3.7억원, 4.1억원이다."
    assert sentence_split(text) == ["단가는 각각 2.5억원, 3.7억원, 4.1억원이다."]


# ---------------------------------------------------------------------------
# Ellipsis
# ---------------------------------------------------------------------------

def test_ellipsis_etc_no_split():
    # "..." followed immediately by Korean characters — no whitespace → no split.
    text = "가, 나, 다...등 다섯 가지이다."
    assert sentence_split(text) == ["가, 나, 다...등 다섯 가지이다."]


# ---------------------------------------------------------------------------
# Full-width Korean sentence terminator (。)
# ---------------------------------------------------------------------------

def test_fullwidth_terminator_with_space():
    # 。+ space is a valid split point.
    text = "공고합니다。 다음은 안내이다。"
    assert sentence_split(text) == ["공고합니다。", "다음은 안내이다。"]


def test_fullwidth_terminator_no_space():
    # 。without a trailing space — no split.
    text = "공고합니다。다음은 안내이다。"
    assert sentence_split(text) == ["공고합니다。다음은 안내이다。"]


# ---------------------------------------------------------------------------
# Mixed terminal punctuation
# ---------------------------------------------------------------------------

def test_mixed_punctuation():
    text = "질문? 답변! 결론."
    assert sentence_split(text) == ["질문?", "답변!", "결론."]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_string():
    assert sentence_split("") == []


def test_single_sentence_no_trailing_space():
    text = "단일 문장입니다."
    assert sentence_split(text) == ["단일 문장입니다."]


def test_whitespace_only():
    assert sentence_split("   ") == []
