"""Unit coverage for rag_answer.py 렌더링·topic 매칭 헬퍼 (issue #2248).

``rag_answer.py`` 의 미커버 렌더링·topic 매칭 헬퍼 3종을 oracle 로 고정한다
(test-only, 소스 무수정). 직접 단위 import 기존 0.

- ``render_answer_text`` — answer dict→사람용 텍스트. summary + claims('- target:
  claim [chunk_ids]', citation 없으면 suffix 생략) + insufficiency('- 근거 부족:
  사유: ...; 확인 필요 대상: ...', 빈 detail 생략) + 빈 line 제외
- ``sentence_has_verification_topic`` — verification_topics 없으면 True(가드),
  있으면 lowered 매칭
- ``metadata_field_requested`` — verification_topics term 이 label+value compact
  텍스트에 포함되는지 bool(terms 없으면 False)

leaf 모듈(rag_verifier/rag_text_processing 등 + stdlib, rag_core back-edge 0 =
ADR 0045). negative assertion 으로 citation suffix·insufficiency 분기·topics 가드·
매칭이 실제로 일어나는지 못 박는다.
"""
from __future__ import annotations

from rag_answer import (
    metadata_field_requested,
    render_answer_text,
    sentence_has_verification_topic,
)


# --- render_answer_text ---


def test_render_summary_only() -> None:
    assert render_answer_text({"summary": "요약문"}) == "요약문"


def test_render_empty_summary_omits_blank_line() -> None:
    # summary 가 비면 빈 line 으로 필터되어 선행 빈 줄이 생기지 않는다
    # (빈 line 제외 필터가 없으면 '\n- A: C [c1]' 로 새어 KILL)
    out = render_answer_text(
        {"summary": "", "claims": [{"target": "A", "claim": "C", "citations": [{"chunk_id": "c1"}]}]}
    )
    assert out == "- A: C [c1]"
    assert not out.startswith("\n")


def test_render_claim_with_citation_ids() -> None:
    answer = {
        "summary": "요약",
        "claims": [
            {"target": "행안부", "claim": "예산 1조", "citations": [{"chunk_id": "c1"}, {"chunk_id": "c2"}]}
        ],
    }
    assert render_answer_text(answer) == "요약\n- 행안부: 예산 1조 [c1, c2]"


def test_render_claim_without_citation_omits_suffix() -> None:
    # citation 이 비면 ' [..]' suffix 를 붙이지 않는다
    out = render_answer_text({"summary": "S", "claims": [{"target": "A", "claim": "C", "citations": []}]})
    assert out == "S\n- A: C"
    assert "[" not in out


def test_render_insufficiency_block() -> None:
    out = render_answer_text(
        {"summary": "S", "insufficiency": {"reasons": ["r1", "r2"], "missing_targets": ["교육부"]}}
    )
    assert out == "S\n- 근거 부족: 사유: r1, r2; 확인 필요 대상: 교육부"


def test_render_insufficiency_empty_details_omitted() -> None:
    # insufficiency 가 있어도 reasons/missing_targets 가 모두 비면 '근거 부족' 줄 생략
    out = render_answer_text({"summary": "S", "insufficiency": {"reasons": [], "missing_targets": []}})
    assert out == "S"
    assert "근거 부족" not in out


# --- sentence_has_verification_topic ---


def test_sentence_topic_no_topics_returns_true() -> None:
    # verification_topics 가 비면 모든 문장이 통과(가드 — over-filter 방지)
    assert sentence_has_verification_topic("아무 문장", {}) is True


def test_sentence_topic_matches() -> None:
    assert sentence_has_verification_topic("예산 집행 내용", {"topics": ["예산"]}) is True


def test_sentence_topic_no_match_is_false() -> None:
    assert sentence_has_verification_topic("계약 내용", {"topics": ["예산"]}) is False


# --- metadata_field_requested ---


def test_metadata_field_requested_no_terms_is_false() -> None:
    # verification_topics(빈 analysis) → terms 없음 → 무조건 False
    assert metadata_field_requested("budget", 1000, {}) is False


def test_metadata_field_requested_matches_label() -> None:
    # 'budget' label('예산')이 topic '예산' 과 compact 매칭
    assert metadata_field_requested("budget", 1000, {"topics": ["예산"]}) is True


def test_metadata_field_requested_no_match_is_false() -> None:
    # topic '예산' 이 agency label/value 에 없으면 False
    assert metadata_field_requested("agency", "행안부", {"topics": ["예산"]}) is False
