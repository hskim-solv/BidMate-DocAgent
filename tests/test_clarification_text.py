"""Unit coverage for rag_clarification.py text builders (issue #2160).

rag_clarification.py 의 명확화 텍스트 구성 함수가 직접 테스트 0. 이 파일은
외부 의존 없는(``ordered_unique`` 만 실제 호출) 순수 text 함수 2개의 분기·
렌더 계약을 고정한다:

- ``clarification_answer``: ``context_resolution["reason"]`` 3분기
- ``metadata_clarification_answer``: candidate 렌더 (agency·project / agency /
  project / bare doc_id), ``candidate_doc_ids`` fallback, 빈 후보 suffix 생략

``make_context_clarification_result`` / ``make_metadata_clarification_result``
는 index/trace/diagnostics dict 구성(무거운 통합 경로)이라 범위 외 (follow-up).
substring 검증으로 문구 변경에 견고하게 둔다.
"""
from __future__ import annotations

from typing import Any

from rag_clarification import clarification_answer, metadata_clarification_answer


# --- clarification_answer: context_resolution["reason"] 분기 ---


def test_clarification_no_active_state() -> None:
    """reason=no_active_state → 기관/사업 확인 요청 + query 삽입, 후보 나열 없음."""
    out = clarification_answer("그건 어때?", {"reason": "no_active_state"})
    assert "그건 어때?" in out
    assert "기관명 또는 사업명을 포함" in out


def test_clarification_ambiguous_lists_unique_entities() -> None:
    """reason=ambiguous_active_state → context_entities + context_projects 를
    ordered_unique 로 합쳐 나열, query 삽입, 중복 제거."""
    out = clarification_answer(
        "그 사업은?",
        {
            "reason": "ambiguous_active_state",
            "context_entities": ["A기관", "A기관"],  # 중복
            "context_projects": ["B사업"],
        },
    )
    assert "그 사업은?" in out
    assert "모호" in out
    assert "A기관, B사업" in out  # dedup + 순서 보존
    assert out.count("A기관") == 1  # 중복 제거됨


def test_clarification_default_branch() -> None:
    """알 수 없는/None reason → 기본(생략 참조 미확정) 메시지."""
    for cr in ({"reason": "something_else"}, {}):
        out = clarification_answer("이거?", cr)
        assert "이거?" in out
        assert "충분히 확정하지 못했습니다" in out


def test_clarification_ambiguous_empty_entities() -> None:
    """entities 가 비어도 crash 없이 렌더 (빈 나열)."""
    out = clarification_answer("그건?", {"reason": "ambiguous_active_state"})
    assert "그건?" in out
    assert "모호" in out


# --- metadata_clarification_answer: candidate 렌더 ---


def _analysis(
    candidate_doc_ids: list[str],
    metadata_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "metadata_ambiguity": {"candidate_doc_ids": candidate_doc_ids},
        "metadata_matches": metadata_matches or [],
    }


def test_metadata_clarification_agency_and_project() -> None:
    out = metadata_clarification_answer(
        "예산은?",
        _analysis(
            ["doc1"],
            [{"doc_id": "doc1", "agency": "행안부", "project": "사업A"}],
        ),
    )
    assert "예산은?" in out
    assert "행안부 · 사업A (doc1)" in out


def test_metadata_clarification_agency_only() -> None:
    out = metadata_clarification_answer(
        "예산은?",
        _analysis(
            ["doc1"],
            [{"doc_id": "doc1", "agency": "행안부", "project": ""}],
        ),
    )
    assert "행안부 (doc1)" in out
    assert "행안부 ·" not in out  # project 없으면 middot 결합 없음


def test_metadata_clarification_project_only() -> None:
    out = metadata_clarification_answer(
        "예산은?",
        _analysis(
            ["doc1"],
            [{"doc_id": "doc1", "agency": "", "project": "사업A"}],
        ),
    )
    assert "사업A (doc1)" in out


def test_metadata_clarification_bare_doc_id_when_no_match() -> None:
    """metadata_matches 에 label 정보 없으면 bare doc_id (괄호 형식 아님)."""
    out = metadata_clarification_answer("예산은?", _analysis(["doc9"]))
    assert "doc9" in out
    assert "(doc9)" not in out


def test_metadata_clarification_empty_candidates_no_suffix() -> None:
    """후보 0 → '현재 후보는' suffix 생략, 기본 메시지만."""
    out = metadata_clarification_answer("예산은?", _analysis([]))
    assert "예산은?" in out
    assert "여러 개라서" in out
    assert "현재 후보는" not in out


def test_metadata_clarification_falls_back_to_matched_doc_ids() -> None:
    """candidate_doc_ids 부재 시 matched_doc_ids 로 fallback."""
    analysis = {
        "metadata_ambiguity": {},  # candidate_doc_ids 없음
        "matched_doc_ids": ["docX"],
        "metadata_matches": [
            {"doc_id": "docX", "agency": "교육부", "project": "정보화"}
        ],
    }
    out = metadata_clarification_answer("예산은?", analysis)
    assert "교육부 · 정보화 (docX)" in out


def test_metadata_clarification_strips_agency_project() -> None:
    """agency/project 주변 공백은 strip 된다."""
    out = metadata_clarification_answer(
        "예산은?",
        _analysis(
            ["doc1"],
            [{"doc_id": "doc1", "agency": "  행안부  ", "project": "  사업A "}],
        ),
    )
    assert "행안부 · 사업A (doc1)" in out


def test_metadata_clarification_duplicate_doc_id_keeps_first_label() -> None:
    out = metadata_clarification_answer(
        "예산은?",
        _analysis(
            ["doc1"],
            [
                {"doc_id": "doc1", "agency": "행안부", "project": "사업A"},
                {"doc_id": "doc1", "agency": "교육부", "project": "사업B"},
            ],
        ),
    )
    assert "행안부 · 사업A (doc1)" in out
    assert "교육부 · 사업B (doc1)" not in out
