"""Unit coverage for rag_answer.render_answer_text 렌더링 (issue #2391).

``render_answer_text``(rag_answer.py:445)는 ADR 0003 답변 dict 를 사람이 읽는
plain-text 로 직렬화하는 순수 import-safe leaf(rag_core/torch/chromadb 미로드,
ADR 0045)인데 직접 단위 테스트가 0건이었다. test-only, 소스 무수정.

핵심 변별:
- summary 줄 strip, 빈 문자열이면 줄에서 drop.
- claim 줄 ``- {target}: {claim}`` + citation suffix ``[{ids}]``(chunk_id 있는 것만,
  전부 빈/없으면 suffix 없음).
- insufficiency 블록은 reasons/missing_targets 가 있을 때만 줄로 추가, 둘 다 비면 생략.
"""
from __future__ import annotations

from typing import Any

from rag_answer import render_answer_text


def test_render_full_summary_strip_claims_and_citations() -> None:
    answer: dict[str, Any] = {
        "summary": "  요약문  ",  # 앞뒤 공백 strip.
        "claims": [
            {"target": "기관A", "claim": "예산 10억", "citations": [{"chunk_id": "c1"}, {"chunk_id": "c2"}]},
            {"target": "기관B", "claim": "기간 12개월", "citations": [{"chunk_id": ""}]},  # 빈 chunk_id → suffix 없음.
        ],
    }
    assert render_answer_text(answer) == "요약문\n- 기관A: 예산 10억 [c1, c2]\n- 기관B: 기간 12개월"


def test_render_empty_summary_line_dropped() -> None:
    # 빈 summary 는 falsy 라 줄에서 제거(맨 앞 빈 줄 안 생김).
    out = render_answer_text({"summary": "", "claims": [{"target": "T", "claim": "C"}]})
    assert out == "- T: C"
    assert not out.startswith("\n")


def test_render_citation_suffix_only_when_chunk_id_present() -> None:
    # citations 키 없음 → suffix 없음.
    assert render_answer_text({"summary": "S", "claims": [{"target": "T", "claim": "C"}]}) == "S\n- T: C"
    # 일부 citation 만 chunk_id 보유 → 있는 것만 join.
    partial = render_answer_text(
        {"summary": "S", "claims": [{"target": "T", "claim": "C", "citations": [{"chunk_id": ""}, {"chunk_id": "c2"}]}]}
    )
    assert partial == "S\n- T: C [c2]"


def test_render_insufficiency_block_reasons_and_missing() -> None:
    # reasons + missing_targets 둘 다 → "사유: …; 확인 필요 대상: …".
    out = render_answer_text(
        {"summary": "S", "claims": [], "insufficiency": {"reasons": ["r1", "r2"], "missing_targets": ["M1"]}}
    )
    assert out == "S\n- 근거 부족: 사유: r1, r2; 확인 필요 대상: M1"


def test_render_insufficiency_reasons_only_vs_missing_only() -> None:
    # reasons 만 → "확인 필요 대상" 미포함.
    reasons_only = render_answer_text(
        {"summary": "S", "claims": [], "insufficiency": {"reasons": ["r1"], "missing_targets": []}}
    )
    assert reasons_only == "S\n- 근거 부족: 사유: r1"
    assert "확인 필요 대상" not in reasons_only
    # missing 만 → "사유" 미포함.
    missing_only = render_answer_text(
        {"summary": "S", "claims": [], "insufficiency": {"reasons": [], "missing_targets": ["M1", "M2"]}}
    )
    assert missing_only == "S\n- 근거 부족: 확인 필요 대상: M1, M2"
    assert "사유:" not in missing_only


def test_render_no_insufficiency_line_when_empty_or_absent() -> None:
    # insufficiency dict 가 있어도 reasons·missing 둘 다 비면 블록 줄 생략.
    empty_block = render_answer_text(
        {"summary": "S", "claims": [], "insufficiency": {"reasons": [], "missing_targets": []}}
    )
    assert empty_block == "S"
    assert "근거 부족" not in empty_block
    # insufficiency 키 자체 없음 → 블록 없음.
    assert render_answer_text({"summary": "S", "claims": []}) == "S"
    # falsy-present 값(None)도 outer 가드에서 skip — truthiness 판정이지 key-presence 가 아님
    # (`if "insufficiency" in answer:` 로 바뀌면 None.get → AttributeError 라 이 케이스가 KILL).
    assert render_answer_text({"summary": "S", "claims": [], "insufficiency": None}) == "S"
