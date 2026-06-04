"""Unit coverage for ``render_multi_chunk_evidence_failures`` 의 case→bucket 순수 헬퍼.

aggregate 빌더(`build_aggregate`/`main`)는 기존 통합 테스트가 덮지만, 그 내부에서
case dict 를 닫힌 enum 버킷/카운트로 변환하는 순수 헬퍼들은 직접 단위 커버리지가
없었다. 이 경계가 조용히 회귀하면 multi-chunk evidence failure 분석 산출물이
왜곡된다(retrieval miss 분류가 source-format 별로 흐트러지거나, top-10 실패 판정이
slice 경계에서 틀어짐). 특히:

- ``_retrieved_chunk_ids`` 는 삽입순이 아니라 **rank 로 정렬**한 뒤 dedup 한다.
- ``_numeric_lt_one`` 은 bool 을 명시적으로 제외하고 ``< 1.0`` (≤ 아님) 경계다.
- ``_source_format_bucket`` 은 화이트리스트 밖과 ``"other"`` 를 모두 ``"other"`` 로 접는다.
- ``_is_top10_failure`` 는 ``retrieved[:10]`` slice 경계(10번째 in / 11번째 out)에 민감하다.

모든 기대값은 pristine 소스 실행으로 캡처했다. synthetic dict 만 사용하므로
real100/비공개 데이터를 접촉하지 않는다(ADR 0005 경계 무관).
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.render_multi_chunk_evidence_failures import (
    _empty_outcome_counts,
    _gold_doc_ids,
    _is_top10_failure,
    _numeric_lt_one,
    _retrieved_chunk_ids,
    _source_format_bucket,
    _split_bucket,
)


# ----------------------------------------------------------------------
# _gold_doc_ids — gold_evidence 중 (chunk_id ∈ gold_set) AND (doc_id truthy) 만 수집
# ----------------------------------------------------------------------


def test_gold_doc_ids_collects_matching_chunk_docs() -> None:
    case = {
        "gold_evidence": [
            {"chunk_id": "c1", "doc_id": "d1"},
            {"chunk_id": "c2", "doc_id": "d2"},
        ]
    }
    assert _gold_doc_ids(case, ["c1", "c2"]) == {"d1", "d2"}


def test_gold_doc_ids_filters_chunk_not_in_gold_set() -> None:
    # chunk_id 가 gold_ids 에 없으면 doc_id 가 있어도 제외 (chunk_id 멤버십 가드).
    case = {"gold_evidence": [{"chunk_id": "c9", "doc_id": "d9"}]}
    assert _gold_doc_ids(case, ["c1"]) == set()


def test_gold_doc_ids_skips_empty_doc_id() -> None:
    # chunk_id 는 매칭되지만 doc_id 가 falsy → 제외 (doc_id truthy 요구, AND 의 우변).
    case = {"gold_evidence": [{"chunk_id": "c1", "doc_id": ""}]}
    assert _gold_doc_ids(case, ["c1"]) == set()


def test_gold_doc_ids_skips_non_dict_items() -> None:
    case = {"gold_evidence": ["not-a-dict", {"chunk_id": "c1", "doc_id": "d1"}]}
    assert _gold_doc_ids(case, ["c1"]) == {"d1"}


def test_gold_doc_ids_dedups_same_doc() -> None:
    case = {
        "gold_evidence": [
            {"chunk_id": "c1", "doc_id": "d1"},
            {"chunk_id": "c2", "doc_id": "d1"},
        ]
    }
    assert _gold_doc_ids(case, ["c1", "c2"]) == {"d1"}


def test_gold_doc_ids_missing_gold_evidence_is_empty() -> None:
    assert _gold_doc_ids({}, ["c1"]) == set()


def test_gold_doc_ids_none_chunk_id_coerced_to_empty_and_skipped() -> None:
    # chunk_id=None → str(None or "")=="" → gold_set 에 없으므로 제외(키 누락도 동일).
    case = {"gold_evidence": [{"chunk_id": None, "doc_id": "d1"}, {"doc_id": "d2"}]}
    assert _gold_doc_ids(case, ["c1"]) == set()


# ----------------------------------------------------------------------
# _retrieved_chunk_ids — rank 정렬 + dedup, retrieved_chunk_ids alt 경로, 3 raise 경로
# ----------------------------------------------------------------------


def test_retrieved_chunk_ids_sorts_by_rank_not_insertion_order() -> None:
    # 삽입순은 b,a 지만 rank 1→a, 2→b 로 정렬되어야 한다 (핵심 경계).
    case = {"retrieved_chunks": [{"chunk_id": "b", "rank": 2}, {"chunk_id": "a", "rank": 1}]}
    assert _retrieved_chunk_ids(case) == ["a", "b"]


def test_retrieved_chunk_ids_dedups_preserving_first() -> None:
    case = {"retrieved_chunks": [{"chunk_id": "a", "rank": 1}, {"chunk_id": "a", "rank": 2}]}
    assert _retrieved_chunk_ids(case) == ["a"]


def test_retrieved_chunk_ids_bad_rank_falls_back_to_ordinal() -> None:
    # rank 가 int() 불가('x','y') → ordinal+1(1,2) 로 폴백 → 삽입순 a,b 유지.
    case = {"retrieved_chunks": [{"chunk_id": "a", "rank": "x"}, {"chunk_id": "b", "rank": "y"}]}
    assert _retrieved_chunk_ids(case) == ["a", "b"]


def test_retrieved_chunk_ids_explicit_and_falsy_rank_order_preserved() -> None:
    # explicit rank=2 + missing-rank(falsy→ordinal+1 폴백) 혼재: 폴백 rank 가 raw
    # ordinal 이 아니라 ordinal+1 이어야 explicit rank 와 정렬 순서가 보존된다.
    # (둘 다 폴백인 경우엔 상수 shift 라 가려지는 off-by-one 을 explicit 혼재로 노출.)
    case = {"retrieved_chunks": [{"chunk_id": "a", "rank": 2}, {"chunk_id": "b"}]}
    assert _retrieved_chunk_ids(case) == ["a", "b"]


def test_retrieved_chunk_ids_explicit_and_bad_rank_order_preserved() -> None:
    # explicit rank=2 + un-int-able rank(except→ordinal+1 폴백) 혼재: except-path
    # 폴백도 ordinal+1 이어야 정렬 순서 보존.
    case = {"retrieved_chunks": [{"chunk_id": "a", "rank": 2}, {"chunk_id": "b", "rank": "zz"}]}
    assert _retrieved_chunk_ids(case) == ["a", "b"]


def test_retrieved_chunk_ids_skips_non_dict_rows() -> None:
    case = {"retrieved_chunks": ["junk", {"chunk_id": "a", "rank": 1}]}
    assert _retrieved_chunk_ids(case) == ["a"]


def test_retrieved_chunk_ids_empty_list_is_empty() -> None:
    assert _retrieved_chunk_ids({"retrieved_chunks": []}) == []


def test_retrieved_chunk_ids_alt_key_filters_falsy_and_dedups() -> None:
    case = {"retrieved_chunk_ids": ["a", "", "b", "a"]}
    assert _retrieved_chunk_ids(case) == ["a", "b"]


def test_retrieved_chunk_ids_raises_when_rows_have_no_usable_id() -> None:
    # 비어있지 않은 rows 인데 사용 가능한 chunk_id 가 하나도 없으면 fail-loud.
    with pytest.raises(ValueError):
        _retrieved_chunk_ids({"retrieved_chunks": [{"rank": 1}]})


def test_retrieved_chunk_ids_raises_when_alt_key_not_list() -> None:
    with pytest.raises(ValueError):
        _retrieved_chunk_ids({"retrieved_chunk_ids": "abc"})


def test_retrieved_chunk_ids_raises_when_no_diagnostics_present() -> None:
    with pytest.raises(ValueError):
        _retrieved_chunk_ids({})


# ----------------------------------------------------------------------
# _empty_outcome_counts — 4-key 제로 shape (계약)
# ----------------------------------------------------------------------


def test_empty_outcome_counts_exact_shape() -> None:
    assert _empty_outcome_counts() == {
        "all_gold_retrieved": 0,
        "partial_gold_retrieved": 0,
        "no_gold_retrieved": 0,
        "not_observable": 0,
    }


def test_empty_outcome_counts_returns_fresh_dict() -> None:
    # 매 호출 새 dict — 한쪽 변형이 다른 호출에 누출되면 안 된다.
    first = _empty_outcome_counts()
    first["all_gold_retrieved"] = 99
    assert _empty_outcome_counts()["all_gold_retrieved"] == 0


# ----------------------------------------------------------------------
# _split_bucket — doc 수 0→unknown / 1→same_doc / ≥2→multi_doc
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "doc_ids,expected",
    [
        (set(), "unknown"),
        ({"d1"}, "same_doc"),
        ({"d1", "d2"}, "multi_doc"),
        ({"d1", "d2", "d3"}, "multi_doc"),
    ],
)
def test_split_bucket_boundaries(doc_ids: set[str], expected: str) -> None:
    assert _split_bucket(doc_ids) == expected


# ----------------------------------------------------------------------
# _source_format_bucket — strip+lower 후 화이트리스트, "other"/미지원→other, 빈값→unknown
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("PDF", "pdf"),          # 대문자 → lower
        ("  hwp  ", "hwp"),      # 주변 공백 strip
        ("CSV", "csv"),
        ("unknown", "unknown"),  # 화이트리스트 안 → 그대로 (빈값 unknown 과 구분)
        ("exe", "other"),        # 화이트리스트 밖 → other
        ("other", "other"),      # 명시 "other" → other (text != "other" 절 핀)
        ("", "unknown"),         # 빈 문자열 → unknown
        (None, "unknown"),       # None → str(None or "")=="" → unknown
        (True, "other"),         # str(True)=="True"→"true" 화이트리스트 밖 → other
    ],
)
def test_source_format_bucket(value: Any, expected: str) -> None:
    assert _source_format_bucket(value) == expected


# ----------------------------------------------------------------------
# _numeric_lt_one — bool 제외 + int/float 만, `< 1.0` (≤ 아님) 경계
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (0.5, True),
        (0.999, True),    # fractional → 절삭/round 변형 차단
        (0, True),
        (-3, True),
        (1.0, False),     # 경계: < 1.0 이지 ≤ 아님
        (1, False),
        (True, False),    # bool 제외 (float(True)=1.0 이라 자체로도 False)
        (False, False),   # bool 제외 핀: 가드 없으면 float(False)=0.0<1.0=True 가 됨
        ("0.5", False),   # str → 숫자 아님 → False
        (None, False),    # None → 숫자 아님 → False
    ],
)
def test_numeric_lt_one(value: Any, expected: bool) -> None:
    assert _numeric_lt_one({"m": value}, "m") is expected


def test_numeric_lt_one_missing_key_is_false() -> None:
    assert _numeric_lt_one({}, "m") is False


# ----------------------------------------------------------------------
# _is_top10_failure — retrieved[:10] subset 검사, slice 경계(10번째 in / 11번째 out)
# ----------------------------------------------------------------------


def test_is_top10_failure_false_when_gold_within_top10() -> None:
    assert _is_top10_failure(["a", "b", "c"], ["a"]) is False


def test_is_top10_failure_true_when_gold_missing() -> None:
    assert _is_top10_failure(["a", "b"], ["z"]) is True


def test_is_top10_failure_empty_gold_is_not_failure() -> None:
    # 빈 set 은 임의 집합의 subset → 실패 아님.
    assert _is_top10_failure(["a"], []) is False


def test_is_top10_failure_slice_boundary_10th_in_11th_out() -> None:
    retrieved = [str(i) for i in range(11)]  # '0'..'10'
    # '9' 는 index 9 = 10번째 → top-10 slice 안 → 실패 아님.
    assert _is_top10_failure(retrieved, ["9"]) is False
    # '10' 은 index 10 = 11번째 → slice 밖 → 실패.
    assert _is_top10_failure(retrieved, ["10"]) is True
