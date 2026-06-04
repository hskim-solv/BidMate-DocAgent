"""Unit coverage for rag_query 쿼리 의도 분류 술어 (issue #2357).

``has_comparison_request`` / ``has_implicit_reference`` 는 query_type 라우팅과
멀티턴 컨텍스트 해소의 분기 조건인 import-safe leaf(rag_core/torch/chromadb
미로드, ADR 0045)인데 직접 단위 테스트가 0건이었다(test-only, 소스 무수정).

핵심 변별:
- ``has_comparison_request`` — ``normalize_entity`` 후 비교어
  ("차이"/"비교"/"각각"/"대비") 중 하나라도 부분일치하면 True(any).
- ``has_implicit_reference`` — ``normalize_entity`` 후 IMPLICIT_REFERENCE_PATTERNS
  ("그 사업" 등 12종) 중 하나라도 부분일치하면 True(any). 패턴에 내부 공백이
  있어 ``normalize_entity`` 의 다중공백 축약 적용 여부가 매칭을 가른다.
"""
from __future__ import annotations

from rag_query import has_comparison_request, has_implicit_reference


# ---- has_comparison_request ----

def test_has_comparison_request_true_for_each_comparison_term() -> None:
    # 4개 비교어가 각각 단독으로 True 를 트리거 — any() 이므로 한 입력에 한 term 만
    # 등장한다. 특정 term 을 튜플에서 빼면 그 줄이 KILL(개별 커버리지).
    assert has_comparison_request("A와 B의 차이는?") is True   # 차이
    assert has_comparison_request("각각 알려줘") is True        # 각각
    assert has_comparison_request("둘을 비교해줘") is True      # 비교
    assert has_comparison_request("작년 대비 올해") is True     # 대비


def test_has_comparison_request_false_without_comparison_term() -> None:
    # 비교어가 전혀 없으면 False — 상수 True 반환이면 KILL.
    assert has_comparison_request("예산은 얼마인가요?") is False
    assert has_comparison_request("") is False


# ---- has_implicit_reference ----

def test_has_implicit_reference_true_for_demonstrative_patterns() -> None:
    # 접두 계열("그 "/"해당 ") + 단독 토큰("그중") 대표 패턴이 각각 True.
    assert has_implicit_reference("그 사업 예산은?") is True
    assert has_implicit_reference("해당 기관 정보 줘") is True
    assert has_implicit_reference("그중 첫번째") is True


def test_has_implicit_reference_false_without_pattern() -> None:
    # 명시적 엔티티만 있고 지시 참조가 없으면 False — 상수 True 면 KILL.
    assert has_implicit_reference("서울시 사업 예산은?") is False
    assert has_implicit_reference("이거 알려줘") is False
    assert has_implicit_reference("") is False


def test_has_implicit_reference_applies_normalize_entity_whitespace_collapse() -> None:
    # "그  사업"(공백 2칸)은 raw 부분문자열로는 "그 사업"(1칸) 패턴과 불일치하지만,
    # normalize_entity 가 내부 다중공백을 1칸으로 축약하므로 매칭되어 True.
    # → normalize_entity 호출을 제거하고 raw query 로 매칭하는 mutation 을 KILL.
    assert has_implicit_reference("그  사업 예산은?") is True
