"""Unit coverage for rag_query.make_plan strategy 문자열 빌드 (issue #2371).

``make_plan``(rag_query.py:479)의 ``strategy`` 문자열은 rerank·metadata_first·
retrieval_backend 조합으로 결정되는데 직접 단위 테스트가 0건이었다. import-safe
leaf(rag_core/torch/chromadb 미로드, ADR 0045). #2368(validation+budget) 후속으로
strategy 문자열 한 concern 한정. test-only, 소스 무수정.

핵심 변별:
- rerank+metadata_first → "dense + lexical + metadata rerank"
- metadata_first=False → "metadata-first " prefix 제거 + metadata rerank 절 제거
- backend hybrid/m3 → 각각 RRF 래핑/대체 문자열.
"""
from __future__ import annotations

from rag_query import make_plan

_A = {"query_type": "single_doc"}


def test_default_strategy_metadata_first_full_rerank() -> None:
    # 기본: rerank=T, metadata_first=T, dense → 전체 rerank 절 + metadata-first prefix.
    assert make_plan(_A)["strategy"] == "metadata-first dense + lexical + metadata rerank"


def test_strategy_without_rerank_is_plain_dense() -> None:
    # rerank=False → lexical/metadata rerank 절이 사라진다("dense" 만 남음).
    assert make_plan(_A, rerank=False)["strategy"] == "metadata-first dense"


def test_strategy_without_metadata_first_drops_prefix_and_metadata_rerank() -> None:
    # metadata_first=False → "metadata-first " prefix 제거 + metadata rerank 절 제거.
    assert make_plan(_A, metadata_first=False)["strategy"] == "dense + lexical rerank"


def test_strategy_hybrid_backend_wraps_in_rrf() -> None:
    # retrieval_backend="hybrid" → 기존 scoring 을 "hybrid (bm25 + {scoring}) rrf" 로 래핑.
    assert (
        make_plan(_A, retrieval_backend="hybrid")["strategy"]
        == "metadata-first hybrid (bm25 + dense + lexical + metadata rerank) rrf"
    )


def test_strategy_m3_backend_replaces_scoring() -> None:
    # retrieval_backend="m3" → m3 멀티채널 RRF 문자열로 대체(기존 scoring 무시).
    assert (
        make_plan(_A, retrieval_backend="m3")["strategy"]
        == "metadata-first m3 (dense + sparse + colbert) rrf"
    )


def test_strategy_no_rerank_no_metadata_first_is_bare_dense() -> None:
    # rerank=False + metadata_first=False → scoring 초기값 "dense" 그대로
    # (rerank 절 없음 + "metadata-first " prefix 없음). rerank×metadata_first 2×2
    # 진리표의 (F,F) 모서리를 닫아 초기값을 prefix 와 함께 gating 하는 compound
    # mutant 를 차단한다.
    assert make_plan(_A, rerank=False, metadata_first=False)["strategy"] == "dense"
