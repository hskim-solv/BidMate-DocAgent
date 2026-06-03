"""Unit coverage for rag_metadata_processing.py target constructors (issue #2177).

#2173 follow-up. ``rag_metadata_processing.py`` 의 순수 metadata target 구성 함수
4종의 동작 계약을 oracle 로 고정한다 (test-only, 소스 무수정). 정규화(#2168)·
match 후처리(#2173)·difflib 매칭은 각각 별도 concern → 매칭은 follow-up.

- ``make_metadata_target`` — doc+field+value → tokens/core_tokens(METADATA_GENERIC_TOKENS
  제외)/compact/aliases/explicit_aliases 를 담은 target dict
- ``metadata_explicit_aliases`` — metadata.{field}_aliases + generic aliases(dict/list) 조합
- ``metadata_aliases`` — agency 특수처리(영숫자 1~4자 토큰, '기관' prefix 추출) + explicit 병합
- ``coerce_metadata_targets`` — dict 리스트는 그대로, 문자열 리스트는 agency target 생성

leaf 모듈(rag_text_processing/rag_conversation_state/korean_lexicon + stdlib 만
의존, rag_core back-edge 0 = ADR 0045 보존). negative assertion 으로 GENERIC 제외/
한글 토큰 제외/non-agency 분기가 실제로 일어나는지(non-vacuous) 못 박는다.
"""
from __future__ import annotations

from rag_metadata_processing import (
    coerce_metadata_targets,
    make_metadata_target,
    metadata_aliases,
    metadata_explicit_aliases,
)


# --- make_metadata_target ---


def test_make_metadata_target_shape_and_compact() -> None:
    doc = {"doc_id": "d1", "agency": "행정안전부", "project": "정보화", "metadata": {}}
    target = make_metadata_target(doc, "agency", "행정안전부")
    assert set(target.keys()) == {
        "doc_id", "agency", "project", "field", "value",
        "compact", "tokens", "core_tokens", "aliases", "explicit_aliases",
    }
    assert target["field"] == "agency"
    assert target["value"] == "행정안전부"
    assert target["compact"] == "행정안전부"


def test_make_metadata_target_core_tokens_drop_generic() -> None:
    # '시스템' 은 METADATA_GENERIC_TOKENS → core_tokens 에서 빠지지만 tokens 에는 남는다
    doc = {"doc_id": "d", "agency": "a", "metadata": {}}
    target = make_metadata_target(doc, "agency", "행정안전부 시스템")
    assert "시스템" in target["tokens"]
    assert "시스템" not in target["core_tokens"]  # generic 토큰이 실제로 걸러졌다
    assert "행정안전부" in target["core_tokens"]


# --- metadata_explicit_aliases ---


def test_metadata_explicit_aliases_field_specific_string() -> None:
    # {field}_aliases 문자열은 구분자 split
    out = metadata_explicit_aliases({"metadata": {"agency_aliases": "행안부, MOIS"}}, "agency")
    assert out == ["행안부", "MOIS"]


def test_metadata_explicit_aliases_generic_dict_and_list() -> None:
    assert metadata_explicit_aliases({"metadata": {"aliases": {"agency": "행안부"}}}, "agency") == ["행안부"]
    # 리스트 형태는 dedup
    out = metadata_explicit_aliases({"metadata": {"aliases": ["A", "B", "A"]}}, "agency")
    assert out == ["A", "B"]


def test_metadata_explicit_aliases_no_metadata_returns_empty() -> None:
    assert metadata_explicit_aliases({}, "agency") == []


# --- metadata_aliases ---


def test_metadata_aliases_agency_keeps_short_alphanumeric_only() -> None:
    # 'mois'(영숫자 1~4자) 는 alias, '행정'(한글) 은 제외
    out = metadata_aliases("agency", "MOIS 행정", ["mois", "행정"], [])
    assert out == ["mois"]
    assert "행정" not in out  # 한글 토큰은 agency alias 로 채택되지 않는다


def test_metadata_aliases_agency_extracts_gigwan_prefix() -> None:
    # compact 가 '기관' 으로 시작하면 그 뒤를 alias 로 추출.
    # tokens=['기관abc'] 는 '기관' prefix 분기를 격리하기 위한 합성 입력
    # (실제 metadata_tokens('기관ABC')=['abc']); dedup 으로 무해하게 흡수된다.
    out = metadata_aliases("agency", "기관ABC", ["기관abc"], [])
    assert out == ["abc"]


def test_metadata_aliases_non_agency_uses_explicit_only() -> None:
    # project 등은 agency 특수처리를 타지 않고 explicit_aliases 만 반환
    out = metadata_aliases("project", "정보화 시스템", ["정보화", "시스템"], ["별칭"])
    assert out == ["별칭"]


def test_metadata_aliases_explicit_listed_first() -> None:
    out = metadata_aliases("agency", "MOIS", ["mois"], ["공식별칭"])
    assert out == ["공식별칭", "mois"]  # explicit 먼저, 그다음 agency 토큰


# --- coerce_metadata_targets ---


def test_coerce_metadata_targets_passes_through_dicts() -> None:
    # 이미 dict 리스트면 그대로 통과 — agency target 으로 재가공하지 않는다
    targets = [{"doc_id": "x", "field": "agency"}]
    assert coerce_metadata_targets(targets) == targets


def test_coerce_metadata_targets_builds_agency_target_from_strings() -> None:
    out = coerce_metadata_targets(["행안부"])
    assert len(out) == 1
    assert out[0]["doc_id"] == "agency::행안부"
    assert out[0]["agency"] == "행안부"
    assert out[0]["field"] == "agency"  # 문자열은 agency target 으로 승격


def test_coerce_metadata_targets_empty_returns_empty() -> None:
    assert coerce_metadata_targets([]) == []


def test_coerce_metadata_targets_branches_on_first_element_only() -> None:
    # 분기는 values[0] 타입만 본다 — 첫 원소가 dict 면 뒤따르는 문자열도
    # agency target 으로 가공되지 않고 그대로 통과한다(현재 계약 고정).
    mixed = [{"doc_id": "x", "field": "agency"}, "행안부"]
    assert coerce_metadata_targets(mixed) == mixed
    assert "행안부" in coerce_metadata_targets(mixed)  # 문자열이 미가공으로 남는다
