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


def test_render_null_claims_keeps_summary_only() -> None:
    assert render_answer_text({"summary": "요약문", "claims": None}) == "요약문"


def test_render_empty_claims_keeps_summary_only() -> None:
    assert render_answer_text({"summary": "요약문", "claims": []}) == "요약문"


def test_render_summary_strips_outer_whitespace() -> None:
    # summary 는 strip 된 뒤 빈 줄 필터를 거쳐 출력된다.
    assert render_answer_text({"summary": "  요약문 \n"}) == "요약문"


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


def test_render_multiple_claims_preserves_ordered_lines() -> None:
    answer = {
        "summary": "요약",
        "claims": [
            {"target": "행안부", "claim": "예산 1조", "citations": []},
            {"target": "교육부", "claim": "마감 6월", "citations": []},
        ],
    }

    assert render_answer_text(answer) == "요약\n- 행안부: 예산 1조\n- 교육부: 마감 6월"


def test_render_claim_filters_blank_citation_ids() -> None:
    answer = {
        "summary": "요약",
        "claims": [
            {
                "target": "행안부",
                "claim": "예산 1조",
                "citations": [
                    {"chunk_id": ""},
                    {"doc_id": "missing-chunk"},
                    {"chunk_id": "c1"},
                ],
            }
        ],
    }
    assert render_answer_text(answer) == "요약\n- 행안부: 예산 1조 [c1]"


def test_render_claim_filters_falsy_citation_ids() -> None:
    answer = {
        "summary": "요약",
        "claims": [
            {
                "target": "행안부",
                "claim": "예산 1조",
                "citations": [
                    {"chunk_id": 0},
                    {"chunk_id": None},
                    {"chunk_id": "c1"},
                ],
            }
        ],
    }
    assert render_answer_text(answer) == "요약\n- 행안부: 예산 1조 [c1]"


def test_render_claim_without_citation_omits_suffix() -> None:
    # citation 이 비면 ' [..]' suffix 를 붙이지 않는다
    out = render_answer_text({"summary": "S", "claims": [{"target": "A", "claim": "C", "citations": []}]})
    assert out == "S\n- A: C"
    assert "[" not in out


def test_render_claim_with_null_citations_omits_suffix() -> None:
    out = render_answer_text({"summary": "S", "claims": [{"target": "A", "claim": "C", "citations": None}]})
    assert out == "S\n- A: C"
    assert "[" not in out


def test_render_insufficiency_block() -> None:
    out = render_answer_text(
        {"summary": "S", "insufficiency": {"reasons": ["r1", "r2"], "missing_targets": ["교육부"]}}
    )
    assert out == "S\n- 근거 부족: 사유: r1, r2; 확인 필요 대상: 교육부"


def test_render_insufficiency_reasons_only() -> None:
    out = render_answer_text({"summary": "S", "insufficiency": {"reasons": ["r1"]}})

    assert out == "S\n- 근거 부족: 사유: r1"


def test_render_insufficiency_missing_targets_only() -> None:
    out = render_answer_text({"summary": "S", "insufficiency": {"missing_targets": ["교육부"]}})

    assert out == "S\n- 근거 부족: 확인 필요 대상: 교육부"


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


def test_sentence_topic_matches_case_insensitively() -> None:
    # sentence/topic 모두 lower 처리되어 영문 topic 대소문자 차이는 매칭을 막지 않는다.
    assert sentence_has_verification_topic("Budget execution detail", {"topics": ["budget"]}) is True


def test_sentence_topic_no_match_is_false() -> None:
    assert sentence_has_verification_topic("계약 내용", {"topics": ["예산"]}) is False


# --- metadata_field_requested ---


def test_metadata_field_requested_no_terms_is_false() -> None:
    # verification_topics(빈 analysis) → terms 없음 → 무조건 False
    assert metadata_field_requested("budget", 1000, {}) is False


def test_metadata_field_requested_matches_label() -> None:
    # 'budget' label('예산')이 topic '예산' 과 compact 매칭
    assert metadata_field_requested("budget", 1000, {"topics": ["예산"]}) is True


def test_metadata_field_requested_matches_compacted_label_alias() -> None:
    # label alias '사업금액' 은 topic '사업 금액' 과 compact 매칭된다.
    assert metadata_field_requested("budget", 1000, {"topics": ["사업 금액"]}) is True


def test_metadata_field_requested_matches_summary_alias() -> None:
    assert metadata_field_requested("summary", "전자입찰", {"topics": ["사업요약"]}) is True


def test_metadata_field_requested_matches_numeric_value() -> None:
    # numeric metadata value 도 str(value) 기반 검색 대상으로 포함된다.
    assert metadata_field_requested("budget", 1000, {"topics": ["1000"]}) is True


def test_metadata_field_requested_matches_raw_key_when_no_label_map() -> None:
    # label map 이 없는 metadata key 는 raw key 자체가 검색 대상으로 사용된다.
    assert metadata_field_requested("custom_field", "값", {"topics": ["custom field"]}) is True


def test_metadata_field_requested_matches_later_topic_after_non_match() -> None:
    # 여러 topic 중 앞 topic 이 빗나가도 뒤 topic 이 label/value 에 맞으면 True 다.
    assert metadata_field_requested("agency", "행정안전부", {"topics": ["예산", "행정 안전부"]}) is True


def test_metadata_field_requested_matches_compacted_value() -> None:
    # value 쪽 공백도 compact 되어 topic '행정안전부' 와 매칭된다.
    assert metadata_field_requested("agency", "행정 안전부", {"topics": ["행정안전부"]}) is True


def test_metadata_field_requested_matches_compacted_summary_value() -> None:
    assert metadata_field_requested("summary", "전자 입찰", {"topics": ["전자입찰"]}) is True


def test_metadata_field_requested_matches_compacted_topic() -> None:
    # topic 쪽 공백도 compact 되어 metadata value '행정안전부' 와 매칭된다.
    assert metadata_field_requested("agency", "행정안전부", {"topics": ["행정 안전부"]}) is True


def test_metadata_field_requested_no_match_is_false() -> None:
    # topic '예산' 이 agency label/value 에 없으면 False
    assert metadata_field_requested("agency", "행안부", {"topics": ["예산"]}) is False
