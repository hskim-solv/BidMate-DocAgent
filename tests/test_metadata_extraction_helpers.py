"""Unit coverage for rag_metadata_extraction.py 순수 helper (issue #2296).

대상 6종은 모두 순수(import 시 torch/chromadb/rag_core 미로드)인데 직접 단위
테스트가 0건이라 RFP 메타데이터(기관·예산·날짜·연락처) 추출의 ADR 0001 regex
baseline + Anthropic tool-call 경로 기초가 조용히 깨질 수 있었다(test-only,
소스 무수정).

핵심 변별: ``_iso_date`` 의 시작 앵커(중간 날짜→None), ``_coerce_float``/
``_clean_str`` 의 0 vs None 구별(0→0.0 / "0", falsy 가드는 None/"" 한정),
``_extract_anthropic_tool_payload`` 의 type+name 동시 매치·non-dict 거부.
"""
from __future__ import annotations

from types import SimpleNamespace

from rag_metadata_extraction import (
    TEXT_CHAR_LIMIT,
    TOOL_DEFINITION,
    _clean_str,
    _coerce_float,
    _extract_anthropic_tool_payload,
    _extract_email,
    _iso_date,
    _join_text,
)


# ---- _join_text ----

def test_join_text_concatenates_and_skips_empty_and_non_dict() -> None:
    doc = {"sections": [{"text": "가"}, {"text": ""}, {"text": "나"}, "not-a-dict"]}
    # 빈 text·non-dict sec 는 건너뛰고 "\n\n" 로 결합.
    assert _join_text(doc) == "가\n\n나"


def test_join_text_missing_sections_is_empty() -> None:
    assert _join_text({}) == ""


def test_join_text_truncates_to_char_limit() -> None:
    big = {"sections": [{"text": "x" * (TEXT_CHAR_LIMIT + 500)}]}
    assert len(_join_text(big)) == TEXT_CHAR_LIMIT  # 상한 초과분 절단


# ---- _extract_email ----

def test_extract_email_hit_and_miss() -> None:
    assert _extract_email("문의 a.b+1@ex-ample.co.kr 끝") == "a.b+1@ex-ample.co.kr"
    assert _extract_email("이메일 없음") is None


# ---- _iso_date ----

def test_iso_date_matches_only_at_start() -> None:
    assert _iso_date("2026-01-02 마감") == "2026-01-02"
    # match 앵커: 중간에 있는 날짜는 잡지 않는다(search 로 바뀌면 KILL).
    assert _iso_date("마감 2026-01-02") is None


def test_iso_date_rejects_falsy_and_non_iso() -> None:
    assert _iso_date("") is None
    assert _iso_date(None) is None
    assert _iso_date(0) is None
    assert _iso_date("2026/01/02") is None  # 슬래시 포맷 미지원


# ---- _coerce_float ----

def test_coerce_float_parses_numbers_including_zero() -> None:
    assert _coerce_float("3.14") == 3.14
    # 0/False 는 None/"" 가드를 통과해 0.0 으로 변환된다(None 으로 새면 KILL).
    assert _coerce_float(0) == 0.0
    assert _coerce_float(False) == 0.0


def test_coerce_float_returns_none_for_empty_and_garbage() -> None:
    assert _coerce_float(None) is None
    assert _coerce_float("") is None
    assert _coerce_float("abc") is None
    assert _coerce_float([]) is None  # TypeError → None


# ---- _clean_str ----

def test_clean_str_strips_and_distinguishes_zero_from_empty() -> None:
    assert _clean_str("  x  ") == "x"
    assert _clean_str("   ") is None  # strip 후 빈 → None
    assert _clean_str("") is None
    assert _clean_str(None) is None
    assert _clean_str(0) == "0"  # 0 은 falsy 가드(None/"") 밖 → str("0")


# ---- _extract_anthropic_tool_payload ----

def test_tool_payload_returns_input_on_type_and_name_match() -> None:
    name = TOOL_DEFINITION["name"]
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", name="x", input={"ignored": 1}),
            SimpleNamespace(type="tool_use", name=name, input={"agency": "A"}),
        ]
    )
    assert _extract_anthropic_tool_payload(response) == {"agency": "A"}


def test_tool_payload_empty_when_name_mismatch_or_no_content() -> None:
    name = TOOL_DEFINITION["name"]
    # type 은 맞지만 name 불일치 → {}
    wrong = SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="other", input={"a": 1})])
    assert _extract_anthropic_tool_payload(wrong) == {}
    # content 부재 → {}
    assert _extract_anthropic_tool_payload(SimpleNamespace(content=None)) == {}
    assert _extract_anthropic_tool_payload(SimpleNamespace()) == {}
    # input 이 dict 아님 → {} (isinstance 가드)
    nondict = SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=name, input="not-a-dict")])
    assert _extract_anthropic_tool_payload(nondict) == {}


def test_tool_payload_requires_type_tool_use_not_just_name() -> None:
    # name 만 일치하고 type 이 tool_use 가 아닌 block 은 input 을 흘리면 안 된다.
    # (type 가드를 제거하면 {"leaked":1} 누출 → KILL. name 가드와 독립 검증.)
    name = TOOL_DEFINITION["name"]
    spoof = SimpleNamespace(content=[SimpleNamespace(type="text", name=name, input={"leaked": 1})])
    assert _extract_anthropic_tool_payload(spoof) == {}
