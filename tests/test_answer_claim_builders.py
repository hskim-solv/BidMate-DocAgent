"""Unit coverage for rag_answer.py claim 빌더 (issue #2240).

``rag_answer.py`` 의 claim 빌더 3종을 oracle 로 고정한다 (ADR 0003 evidence→claim
변환, test-only, 소스 무수정). make_citation/claim_target 등 하위 헬퍼는 기존
테스트가 단위 커버. build_extract_claims(best_sentence/metadata_claim_sentences
의존)는 별도 concern → follow-up.

- ``build_claims`` — 라우팅. query_type=comparison AND len(entities)>1 →
  build_comparison_claims, else build_extract_claims (위임 동등성으로 검증)
- ``make_claim`` — (target,item,analysis,sentence?,support?)→claim dict.
  claim=sentence or best_sentence, support=support or item.text,
  citations=[make_citation]
- ``build_comparison_claims`` — entity별 첫 evidence, used_chunks dedup(같은
  chunk_id 재사용 skip), entity evidence 없으면 skip

leaf 모듈(rag_metadata_processing 등 + stdlib, rag_core back-edge 0 = ADR 0045).
negative assertion 으로 라우팅 분기·sentence/support 폴백·chunk dedup·skip 이 실제로
일어나는지 못 박는다.
"""
from __future__ import annotations

from typing import Any

from rag_answer import (
    build_claims,
    build_comparison_claims,
    build_extract_claims,
    make_claim,
)


def _item(agency: str, chunk_id: str, *, text: str = "본문 내용", doc_id: str = "d") -> dict[str, Any]:
    return {"agency": agency, "chunk_id": chunk_id, "text": text, "doc_id": doc_id, "title": "T"}


# --- make_claim ---


def test_make_claim_shape_and_explicit_sentence() -> None:
    item = _item("행안부", "c1", text="전체 본문")
    claim = make_claim("행안부", item, {}, sentence="요약 문장")
    assert set(claim.keys()) == {"target", "claim", "support", "citations"}
    assert claim["target"] == "행안부"
    assert claim["claim"] == "요약 문장"  # sentence 명시 → best_sentence 우회
    assert claim["support"] == "전체 본문"  # support 미지정 → item.text
    assert len(claim["citations"]) == 1
    assert claim["citations"][0]["doc_id"] == "d"


def test_make_claim_explicit_support_overrides_item_text() -> None:
    item = _item("행안부", "c1", text="전체 본문")
    claim = make_claim("행안부", item, {}, sentence="s", support="명시 support")
    assert claim["support"] == "명시 support"


def test_make_claim_falls_back_to_best_sentence() -> None:
    # sentence 미지정 → best_sentence(item.text, topics, tokens) 로 채워진다(비어있지 않음)
    item = _item("행안부", "c1", text="행안부 예산 집행 계획입니다.")
    claim = make_claim("행안부", item, {"topics": [], "tokens": []})
    assert claim["claim"]  # 빈 문자열 아님


# --- build_claims 라우팅 (위임 동등성) ---


def _two_entity_evidence() -> list[dict[str, Any]]:
    return [
        _item("행안부", "c1", text="행안부 예산 집행", doc_id="d1"),
        _item("교육부", "c2", text="교육부 예산 집행", doc_id="d2"),
    ]


def _diverging_evidence() -> list[dict[str, Any]]:
    # 행안부 evidence 2개 + 교육부 1개 → 두 빌더가 갈라진다:
    #   comparison: entity별 첫 evidence → [행안부, 교육부]
    #   extract:    evidence 순회 max 2 → [행안부, 행안부] (교육부 도달 전 중단)
    # 이 발산이 위임 동등성 테스트를 load-bearing 하게 만든다(우연 일치 vacuity 차단).
    return [
        _item("행안부", "c1", text="행안부 예산 집행 계획.", doc_id="d1"),
        _item("행안부", "c2", text="행안부 사업 추진 현황.", doc_id="d2"),
        _item("교육부", "c3", text="교육부 장학 사업.", doc_id="d3"),
    ]


def test_build_claims_routes_comparison_to_comparison_claims() -> None:
    ev = _diverging_evidence()
    analysis = {"query_type": "comparison", "entities": ["행안부", "교육부"], "topics": [], "tokens": []}
    # precondition: 두 빌더가 이 입력에서 실제로 다른 결과를 내야 동등성이 의미를 가진다
    assert build_comparison_claims(analysis, ev) != build_extract_claims(analysis, ev)
    # comparison AND entities>1 → build_comparison_claims 위임 (라우팅 분기 삭제 mutant KILL)
    assert build_claims(analysis, ev) == build_comparison_claims(analysis, ev)


def test_build_claims_single_entity_comparison_routes_to_extract() -> None:
    ev = _diverging_evidence()
    # comparison 이라도 entities<=1 이면 extract 경로(라우팅 가드: len>1 → len>=1 mutant KILL)
    analysis = {"query_type": "comparison", "entities": ["행안부"], "topics": [], "tokens": []}
    assert build_comparison_claims(analysis, ev) != build_extract_claims(analysis, ev)
    assert build_claims(analysis, ev) == build_extract_claims(analysis, ev)


def test_build_claims_non_comparison_routes_to_extract() -> None:
    ev = _diverging_evidence()
    analysis = {"query_type": "single_doc", "entities": ["행안부", "교육부"], "topics": [], "tokens": []}
    # precondition 발산 → "항상 comparison" 라우팅 mutant 가 KILL 된다
    assert build_comparison_claims(analysis, ev) != build_extract_claims(analysis, ev)
    assert build_claims(analysis, ev) == build_extract_claims(analysis, ev)


# --- build_comparison_claims ---


def test_build_comparison_claims_one_per_entity() -> None:
    ev = _two_entity_evidence()
    analysis = {"entities": ["행안부", "교육부"], "topics": [], "tokens": []}
    claims = build_comparison_claims(analysis, ev)
    assert [c["target"] for c in claims] == ["행안부", "교육부"]


def test_build_comparison_claims_dedupes_shared_chunk() -> None:
    # 두 entity 가 같은 chunk_id 를 가리키면 used_chunks 가 두 번째를 skip
    ev = [_item("행안부", "c1"), _item("교육부", "c1")]
    analysis = {"entities": ["행안부", "교육부"], "topics": [], "tokens": []}
    claims = build_comparison_claims(analysis, ev)
    assert len(claims) == 1
    assert claims[0]["target"] == "행안부"


def test_build_comparison_claims_skips_entity_without_evidence() -> None:
    # evidence 가 없는 entity 는 건너뛴다(빈 claim 생성 안 함)
    ev = [_item("행안부", "c1")]
    analysis = {"entities": ["행안부", "없는기관"], "topics": [], "tokens": []}
    claims = build_comparison_claims(analysis, ev)
    assert [c["target"] for c in claims] == ["행안부"]


def test_build_comparison_claims_empty_when_no_entity_match() -> None:
    ev = [_item("국토부", "c1")]
    analysis = {"entities": ["행안부", "교육부"], "topics": [], "tokens": []}
    assert build_comparison_claims(analysis, ev) == []


def test_build_comparison_claims_uses_first_evidence_per_entity() -> None:
    # 한 entity 에 evidence 가 여럿이면 리스트 순서상 첫 번째(c1/d1)를 선택한다
    # (entity_evidence[0]). [-1] 등으로 바뀌면 citation doc_id 가 d2 가 되어 KILL.
    ev = [_item("행안부", "c1", doc_id="d1"), _item("행안부", "c2", doc_id="d2")]
    analysis = {"entities": ["행안부"], "topics": [], "tokens": []}
    claims = build_comparison_claims(analysis, ev)
    assert len(claims) == 1
    assert claims[0]["citations"][0]["doc_id"] == "d1"
