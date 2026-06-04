"""Unit coverage for ``scripts/render_failure_distribution.py`` 집계 헬퍼.

실패 분포 보드의 per-category slice 와 top-level 카운트를 만드는 순수 헬퍼들이다.
fail-loud 경계(taxonomy drift·비숫자 값)나 whitelist→other collapse 가 조용히
회귀하면 측정 표면이 케이스를 누락하거나 schema drift 를 삼키므로 oracle 로 고정한다.
특히:

- ``_extract_failure_counts`` 는 **fail-loud**: dict 아님/taxonomy 외부 키/비숫자/
  bool 값에 ``ValueError``. 누락 키는 0, float 은 ``int`` 절삭.
- ``_extract_abstention_outcomes`` 는 동형이나 **bool 을 배제하지 않는다**(``int(True)==1``)
  — failure_counts 와의 대조 경계.
- ``_accumulate_case`` 는 카운트만 in-place fold: query_type/hardcase whitelist→other,
  빈 태그→untagged, 단일 str 태그는 리스트 래핑, aux 는 True 개수만.

모든 기대값은 pristine 소스 실행으로 캡처했다.
``from scripts.render_failure_distribution import ...`` (implicit namespace).
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.render_failure_distribution import (
    FAILURE_CATEGORIES,
    SAFE_CATEGORIES,
    SAFE_OUTCOME_KEYS,
    _accumulate_case,
    _build_slice_counts,
    _empty_slice,
    _extract_abstention_outcomes,
    _extract_failure_counts,
)


def _leaf_sum(payload: dict[str, Any]) -> int:
    total = 0
    for value in payload.values():
        if isinstance(value, dict):
            total += _leaf_sum(value)
        elif isinstance(value, int):
            total += value
    return total


# ----------------------------------------------------------------------
# _empty_slice  (전 키 0 인 zeroed 페이로드)
# ----------------------------------------------------------------------


def test_empty_slice_is_fully_zeroed() -> None:
    payload = _empty_slice()
    assert payload["n"] == 0
    assert _leaf_sum(payload) == 0  # 모든 leaf 카운트가 0


def test_empty_slice_shape() -> None:
    payload = _empty_slice()
    assert set(payload) == {
        "n",
        "query_type",
        "hardcase_categories",
        "evidence_cardinality",
        "expected_doc_coverage",
        "retry_count",
        "query_specificity",
        "aux_true",
    }
    # query_type = SAFE whitelist + other; hardcase = SAFE + untagged + other.
    assert "other" in payload["query_type"]
    assert {"untagged", "other"} <= set(payload["hardcase_categories"])
    assert set(payload["aux_true"]) == {"abstained", "term_match", "doc_match"}
    assert set(payload["evidence_cardinality"]) == {"empty", "single_doc", "multi_doc"}


# ----------------------------------------------------------------------
# _extract_failure_counts  (fail-loud)
# ----------------------------------------------------------------------


def test_extract_failure_counts_happy_zero_fills_and_truncates() -> None:
    raw = {FAILURE_CATEGORIES[0]: 2, FAILURE_CATEGORIES[1]: 3.7}
    counts = _extract_failure_counts({"failure_category_counts": raw})
    assert set(counts) == set(FAILURE_CATEGORIES)   # 전 taxonomy 키 보장
    assert counts[FAILURE_CATEGORIES[1]] == 3        # 3.7 → int 절삭(반올림 아님, raw float 아님)
    assert counts[FAILURE_CATEGORIES[-1]] == 0       # 누락 키 → 0


@pytest.mark.parametrize(
    "summary",
    [
        {},                                                      # 키 없음 → None → not dict
        {"failure_category_counts": []},                         # dict 아님
        {"failure_category_counts": {"__not_a_category__": 1}},  # taxonomy drift
        {"failure_category_counts": {FAILURE_CATEGORIES[0]: "x"}},   # 비숫자
        {"failure_category_counts": {FAILURE_CATEGORIES[0]: True}},  # bool 명시 배제
    ],
)
def test_extract_failure_counts_fail_loud(summary: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _extract_failure_counts(summary)


# ----------------------------------------------------------------------
# _extract_abstention_outcomes  (bool 배제 안 함)
# ----------------------------------------------------------------------


@pytest.mark.parametrize("summary", [{}, {"abstention_outcomes": None}, {"abstention_outcomes": []}])
def test_extract_abstention_outcomes_non_dict_all_zero(summary: dict[str, Any]) -> None:
    assert _extract_abstention_outcomes(summary) == {key: 0 for key in SAFE_OUTCOME_KEYS}


def test_extract_abstention_outcomes_filters_coerces_zerofills() -> None:
    raw = {SAFE_OUTCOME_KEYS[0]: 4, SAFE_OUTCOME_KEYS[1]: 2.7, "ignored_key": 99}
    result = _extract_abstention_outcomes({"abstention_outcomes": raw})
    assert set(result) == set(SAFE_OUTCOME_KEYS)        # whitelist 만, "ignored_key" 제외
    assert result[SAFE_OUTCOME_KEYS[0]] == 4
    assert result[SAFE_OUTCOME_KEYS[1]] == 2            # 2.7 → int 절삭(반올림 아님, raw float 아님)
    assert result[SAFE_OUTCOME_KEYS[2]] == 0            # 누락 → 0


def test_extract_abstention_outcomes_does_not_exclude_bool() -> None:
    # failure_counts 와 달리 bool 가드가 없어 int(True)==1 로 집계된다(대조 경계).
    result = _extract_abstention_outcomes({"abstention_outcomes": {SAFE_OUTCOME_KEYS[0]: True}})
    assert result[SAFE_OUTCOME_KEYS[0]] == 1


# ----------------------------------------------------------------------
# _accumulate_case  (카운트만 in-place fold)
# ----------------------------------------------------------------------


def test_accumulate_case_full_whitelisted_fold() -> None:
    payload = _empty_slice()
    _accumulate_case(
        payload,
        {
            "query_type": "comparison",
            "hardcase_categories": ["multi_hop", "long_context"],
            "evidence_doc_ids": ["d1", "d2"],
            "expected_doc_ids": ["d1"],
            "retry_count": 2,
            "query": "얼마",
            "abstained": True,
            "term_match": False,
            "doc_match": True,
        },
    )
    assert payload["n"] == 1
    assert payload["query_type"]["comparison"] == 1
    assert payload["hardcase_categories"]["multi_hop"] == 1
    assert payload["hardcase_categories"]["long_context"] == 1
    assert payload["evidence_cardinality"]["multi_doc"] == 1
    assert payload["expected_doc_coverage"]["expected_in_evidence"] == 1
    assert payload["retry_count"]["2"] == 1
    assert payload["query_specificity"]["keyword_hit"] == 1
    # aux_true 는 truthy 만 — term_match=False 는 미집계.
    assert payload["aux_true"] == {"abstained": 1, "term_match": 0, "doc_match": 1}


def test_accumulate_case_collapses_and_untagged() -> None:
    payload = _empty_slice()
    _accumulate_case(payload, {"query_type": "weird_type", "hardcase_categories": [], "query": "plain"})
    assert payload["query_type"]["other"] == 1            # 비-whitelist → other
    assert payload["hardcase_categories"]["untagged"] == 1  # 빈 태그 → untagged
    assert payload["evidence_cardinality"]["empty"] == 1
    assert payload["expected_doc_coverage"]["no_expected"] == 1
    assert payload["retry_count"]["0"] == 1
    assert payload["query_specificity"]["no_hit"] == 1


def test_accumulate_case_single_string_tag_is_wrapped() -> None:
    payload = _empty_slice()
    _accumulate_case(payload, {"hardcase_categories": "distractor_heavy"})
    assert payload["hardcase_categories"]["distractor_heavy"] == 1


def test_accumulate_case_unknown_tag_to_other() -> None:
    payload = _empty_slice()
    _accumulate_case(payload, {"hardcase_categories": ["bogus_tag"]})
    assert payload["hardcase_categories"]["other"] == 1


def test_accumulate_case_expected_not_in_evidence() -> None:
    payload = _empty_slice()
    _accumulate_case(payload, {"evidence_doc_ids": ["e1"], "expected_doc_ids": ["x9"]})
    assert payload["expected_doc_coverage"]["expected_not_in_evidence"] == 1
    assert payload["evidence_cardinality"]["single_doc"] == 1


# ----------------------------------------------------------------------
# _build_slice_counts  (case_results 부재 → 전 카테고리 zeroed)
# ----------------------------------------------------------------------


@pytest.mark.parametrize("summary", [{}, {"case_results": None}, {"case_results": "x"}])
def test_build_slice_counts_absent_case_results_zeroed(summary: dict[str, Any]) -> None:
    slices = _build_slice_counts(summary)
    assert set(slices) == set(SAFE_CATEGORIES)       # 전 카테고리 full shape
    assert all(slice_payload["n"] == 0 for slice_payload in slices.values())
