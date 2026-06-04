"""Unit coverage for rag_query.extract_requested_agencies (issue #2361).

``extract_requested_agencies`` 는 쿼리에서 ``기관 A``/``기관-b`` 형태의 발주
기관 토큰을 ``ENTITY_RE`` (``기관\\s*[-_]?\\s*([A-Za-z0-9]+)``) 로 추출해
``normalize_metadata_token`` → 대문자화 후 ``기관 X`` 리스트로 반환하는
import-safe leaf(rag_core/torch/chromadb 미로드, ADR 0045)인데 직접 단위
테스트가 0건이었다(test-only, 소스 무수정).

핵심 변별:
- 매칭 토큰을 대문자화("a"→"A") 후 ``기관 X`` 로 추출.
- 하이픈/언더스코어 구분자 + 공백 없는 변형("기관A") 매칭.
- ``ordered_unique`` 로 순서 보존 중복 제거.
- ENTITY_RE 는 ``[A-Za-z0-9]+`` 만 — 한글 토큰/매칭 없음/빈 입력 → [].
"""
from __future__ import annotations

from rag_query import extract_requested_agencies


def test_extracts_and_uppercases_tokens() -> None:
    # ENTITY_RE 매칭 토큰을 normalize→대문자화하여 "기관 X" 로 추출.
    assert extract_requested_agencies("기관 A와 기관 B 비교") == ["기관 A", "기관 B"]
    # 하이픈/언더스코어 구분자 + 숫자 토큰.
    assert extract_requested_agencies("기관-c 사업") == ["기관 C"]
    assert extract_requested_agencies("기관_123 예산") == ["기관 123"]
    # 구분자 공백이 없는 변형("기관A")도 ENTITY_RE \\s* 로 매칭.
    assert extract_requested_agencies("기관A 사업") == ["기관 A"]


def test_uppercases_lowercase_token() -> None:
    # 소문자 토큰도 대문자로 — upper() 를 제거하면 "기관 b" 가 되어 KILL.
    assert extract_requested_agencies("기관 b 사업") == ["기관 B"]


def test_dedupes_preserving_first_seen_order() -> None:
    # 동일 기관 반복 → ordered_unique 로 1개 — dedup 제거 시 중복 리스트로 KILL.
    assert extract_requested_agencies("기관 A 기관 A 차이") == ["기관 A"]
    # 첫 등장 순서 보존(B 가 A 보다 먼저, 두번째 B 는 버림).
    assert extract_requested_agencies("기관 B 기관 A 기관 B") == ["기관 B", "기관 A"]


def test_ignores_non_ascii_and_unmatched() -> None:
    # ENTITY_RE 는 [A-Za-z0-9]+ 만 매칭 — 한글 토큰은 캡처하지 않는다.
    assert extract_requested_agencies("기관 서울시 예산") == []
    # 패턴 자체가 없는 쿼리 / 빈 입력 → [].
    assert extract_requested_agencies("예산은 얼마인가요?") == []
    assert extract_requested_agencies("") == []
