"""Unit coverage for rag_answer.py 문장 선택·메타데이터 claim 빌더 (issue #2260).

``rag_answer.py`` 의 답변 대표 문장 선택기와 메타데이터 claim 빌더 2종을 oracle
로 고정한다 (test-only, 소스 무수정). 직접 단위 import 기존 0.

- ``best_sentence`` — evidence 텍스트에서 답변 대표 문장 1개 선택. ``topic_hits*3
  + token_hits`` 스코어, 동점 시 짧은 문장 우선(``key=(score, -len)`` reverse).
  빈 텍스트는 ``[text]`` fallback.
- ``metadata_claim_sentences`` — chunk metadata dict→claim 문장 리스트.
  ``METADATA_CLAIM_LABELS`` 순회 + 빈/None 값 skip + ``metadata_field_requested``
  필터 + ``ordered_unique`` dedup. metadata 부재/비-dict → ``[]``.

leaf 모듈(rag_text_processing/rag_verifier + stdlib, rag_core back-edge 0 =
ADR 0045). negative assertion 으로 topic 가중 비대칭(×3)·tie-break 방향·필터
분기·값 가드가 실제로 일어나는지 못 박는다.
"""
from __future__ import annotations

from rag_answer import best_sentence, metadata_claim_sentences


# --- best_sentence ---


def test_best_sentence_single_returns_itself() -> None:
    assert best_sentence("예산은 1조원이다", [], []) == "예산은 1조원이다"


def test_best_sentence_empty_text_falls_back_to_text() -> None:
    # sentence_split 이 빈 결과면 [text] fallback → 빈 문자열 그대로
    assert best_sentence("", [], []) == ""


def test_best_sentence_topic_weight_is_strictly_three() -> None:
    # topic 문장을 token 문장보다 길게 만들어 tie-break(동점 시 짧은 문장 우선)이
    # token 문장을 선호하게 한다. 그래도 topic 이 이기려면 strict score 우위가
    # 필요 → ×3(score 3 > 2)에서만 topic 승. ×2(2=2 동점→짧은 token 승)·×1(token
    # 승)·swap(topic×1+token×3=6, token 승) 모두 기대값 위반 → KILL.
    out = best_sentence("예산 관련 항목 상세 검토. 계약 분석.", ["예산"], ["계약", "분석"])
    assert out == "예산 관련 항목 상세 검토."


def test_best_sentence_topic_hit_is_case_insensitive() -> None:
    # case-sensitive 로 회귀하면 두 문장 score=0 동점이 되어 더 짧은 fallback 문장이 이긴다.
    out = best_sentence("Budget detail with additional context. x.", ["budget"], [])
    assert out == "Budget detail with additional context."


def test_best_sentence_token_only_selection() -> None:
    # topic 없이 query token 매칭만으로 선택
    assert best_sentence("계약 내용. 예산 집행.", [], ["예산"]) == "예산 집행."


def test_best_sentence_enough_tokens_outweigh_one_topic() -> None:
    # token 4개(×1=4) > topic 1개(×3=3) → 가중이 무한대가 아님을 못 박는다
    out = best_sentence(
        "예산 항목. 계약 검토 분석 평가 내용.", ["예산"], ["계약", "검토", "분석", "평가"]
    )
    assert out == "계약 검토 분석 평가 내용."


def test_best_sentence_tie_prefers_shorter() -> None:
    # 동점(둘 다 score 0) → key=(score, -len) reverse 로 짧은 문장 우선.
    # tie-break 를 +len 으로 뒤집으면 긴 문장이 이겨 KILL.
    assert best_sentence("아주 긴 문장이다 정말. 짧다.", [], []) == "짧다."


# --- metadata_claim_sentences ---


def test_metadata_claims_no_metadata_is_empty() -> None:
    assert metadata_claim_sentences({}, {}) == []


def test_metadata_claims_non_dict_metadata_is_empty() -> None:
    # metadata 가 dict 가 아니면 early return []
    assert metadata_claim_sentences({"metadata": "행안부"}, {}) == []


def test_metadata_claims_empty_value_skipped() -> None:
    # 빈 문자열 값은 claim 으로 만들지 않는다 (requested 여도)
    assert metadata_claim_sentences({"metadata": {"budget": ""}}, {"topics": ["예산"]}) == []


def test_metadata_claims_none_value_skipped() -> None:
    assert metadata_claim_sentences({"metadata": {"budget": None}}, {"topics": ["예산"]}) == []


def test_metadata_claims_requested_field_rendered() -> None:
    # budget label '사업예산' 이 topic '예산' 으로 요청됨 → 라벨+포맷값 claim
    out = metadata_claim_sentences({"metadata": {"budget": 1000000}}, {"topics": ["예산"]})
    assert out == ["사업예산: 1,000,000원"]


def test_metadata_claims_zero_value_is_rendered() -> None:
    out = metadata_claim_sentences({"metadata": {"budget": 0}}, {"topics": ["예산"]})
    assert out == ["사업예산: 0원"]


def test_metadata_claims_unrequested_field_filtered_out() -> None:
    # 같은 값이라도 topic 이 매칭 안 되면 metadata_field_requested 필터로 제외 → []
    out = metadata_claim_sentences({"metadata": {"budget": 1000000}}, {"topics": ["일정"]})
    assert out == []
