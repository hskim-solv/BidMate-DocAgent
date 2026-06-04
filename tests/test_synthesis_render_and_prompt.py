"""Unit coverage for ``rag_synthesis`` 합성-단계 문자열 조립 헬퍼.

``_render_with_synthesis`` 는 요약 + verified claims + 근거부족(insufficiency)
블록을 사람이 읽는 답변 문자열로 렌더링하고, ``_build_user_prompt`` 는 synthesis
LLM 에 넘길 프롬프트(헤더 + claims + evidence + 고정 instruction)를 조립한다.
둘 다 순수·결정적이지만 직접 단위 테스트가 없어, 조립 결과 전체 문자열과 조건부
가지(citation suffix 필터, insufficiency 부분 조각, 빈 줄 필터, placeholder,
고정 footer)를 oracle 로 고정한다.

모든 기대값은 소스 실행으로 캡처했다.
"""

from __future__ import annotations

from rag_synthesis import _build_user_prompt, _render_with_synthesis


# ----------------------------------------------------------------------
# _render_with_synthesis
# ----------------------------------------------------------------------


def test_render_lists_claims_with_filtered_citation_ids() -> None:
    answer = {
        "claims": [
            {
                "target": "입찰 마감",
                "claim": "2026-07-01",
                "citations": [{"chunk_id": "d::c1"}, {"chunk_id": "d::c2"}],
            },
            # 빈 chunk_id citation 은 필터되어 suffix 가 붙지 않는다
            {"target": "사업 금액", "claim": "5천만원", "citations": [{"chunk_id": ""}]},
            # citations 키 없음 → suffix 없음
            {"target": "담당", "claim": "조달청"},
        ]
    }
    assert _render_with_synthesis("요약문", answer) == (
        "요약문\n"
        "- 입찰 마감: 2026-07-01 [d::c1, d::c2]\n"
        "- 사업 금액: 5천만원\n"
        "- 담당: 조달청"
    )


def test_render_filters_empty_chunk_id_among_real_citations() -> None:
    # real + 빈 chunk_id 혼합 시 빈 것만 제거되고 trailing ', ' 가 남지 않는다.
    # (단일 빈 citation 만으로는 join 결과가 '' 라 필터 유무가 구분되지 않으므로 혼합으로 pin.)
    answer = {
        "claims": [
            {"target": "혼합", "claim": "v", "citations": [{"chunk_id": "d::c3"}, {"chunk_id": ""}]}
        ]
    }
    assert _render_with_synthesis("S", answer) == "S\n- 혼합: v [d::c3]"


def test_render_appends_insufficiency_with_reasons_and_missing_targets() -> None:
    # reasons/missing_targets 모두 2원소 — 두 join separator(', ')를 함께 pin 한다
    # (단일 원소면 '|' 등으로 바뀌어도 출력이 같아 회귀가 보이지 않는다).
    answer = {
        "claims": [{"target": "X", "claim": "Y", "citations": []}],
        "insufficiency": {
            "reasons": ["근거 없음", "모호"],
            "missing_targets": ["예산", "일정"],
        },
    }
    assert _render_with_synthesis("요약", answer) == (
        "요약\n- X: Y\n- 근거 부족: 사유: 근거 없음, 모호; 확인 필요 대상: 예산, 일정"
    )


def test_render_insufficiency_reasons_only() -> None:
    assert _render_with_synthesis("S", {"insufficiency": {"reasons": ["r1"]}}) == (
        "S\n- 근거 부족: 사유: r1"
    )


def test_render_insufficiency_missing_targets_only() -> None:
    assert _render_with_synthesis("S", {"insufficiency": {"missing_targets": ["t1"]}}) == (
        "S\n- 근거 부족: 확인 필요 대상: t1"
    )


def test_render_empty_insufficiency_emits_no_shortage_line() -> None:
    # reasons/missing_targets 둘 다 없으면 '근거 부족' 줄 자체가 생략된다(falsy {} → L306 단락).
    assert _render_with_synthesis("S", {"insufficiency": {}}) == "S"


def test_render_truthy_but_empty_insufficiency_omits_shortage_line() -> None:
    # truthy 하지만 reasons/missing_targets 가 빈 리스트면 L314 'if details' 가지에서
    # 줄이 생략된다(falsy {} 가 아니라 빈 조각 경로를 직접 도달시켜 pin).
    answer = {"insufficiency": {"reasons": [], "missing_targets": []}}
    assert _render_with_synthesis("S", answer) == "S"


def test_render_empty_answer_returns_summary_only() -> None:
    assert _render_with_synthesis("only summary", {}) == "only summary"


def test_render_filters_empty_summary_line() -> None:
    # 빈 summary 줄은 falsy 라 출력에서 제외된다(claim 줄만 남는다).
    assert _render_with_synthesis("", {"claims": [{"target": "a", "claim": "b"}]}) == "- a: b"


# ----------------------------------------------------------------------
# _build_user_prompt
# ----------------------------------------------------------------------

_FOOTER = (
    "Rewrite the summary in 2-4 natural Korean sentences. Cite by "
    "[chunk_id]. Do not add facts beyond the claims. Call emit_summary."
)


def test_build_user_prompt_full_assembly() -> None:
    analysis = {"query_type": "deadline", "entities": ["조달청", "입찰"]}
    answer = {"claims": [{"target": "마감", "claim": "7월", "citations": [{"chunk_id": "d::c1"}]}]}
    evidence = [{"chunk_id": "d::c1", "doc_id": "d", "agency": "조달청", "text": "본문"}]
    assert _build_user_prompt("질의?", analysis, answer, evidence) == (
        "Query: 질의?\n"
        "Query type: deadline\n"
        "Entities: 조달청, 입찰\n\n"
        "Verified claims (you must respect these):\n"
        "- 마감: 7월 [d::c1]\n\n"
        "Evidence chunks (your only citation universe):\n"
        "[d::c1] doc=d agency=조달청\n본문\n\n"
        + _FOOTER
    )


def test_build_user_prompt_empty_inputs_use_placeholders() -> None:
    # query_type 누락 → 'unknown', entities 누락 → 'none', claims/evidence 없음 → placeholder.
    assert _build_user_prompt("q", {}, {}, []) == (
        "Query: q\n"
        "Query type: unknown\n"
        "Entities: none\n\n"
        "Verified claims (you must respect these):\n"
        "(no claims)\n\n"
        "Evidence chunks (your only citation universe):\n"
        "(no evidence)\n\n"
        + _FOOTER
    )


def test_build_user_prompt_ends_with_fixed_instruction_footer() -> None:
    # footer 는 입력과 무관한 불변 계약이다.
    prompt = _build_user_prompt("아무 질의", {"query_type": "x"}, {}, [])
    assert prompt.endswith(_FOOTER)
