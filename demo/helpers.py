#!/usr/bin/env python3
"""Pure helpers for the Streamlit live-demo, importable without Streamlit.

Splitting these out keeps the UI module (``streamlit_app.py``)
streamlit-only and lets tests run in environments that have not
installed the optional ``streamlit`` extra (the deterministic CLI/CI
path).
"""
from __future__ import annotations

import time
from typing import Any


SAMPLE_QUERIES: list[tuple[str, str, str]] = [
    ("single_doc", "기관 A의 보안 통제 요구사항은?", "단일 기관 추출 (보안 + 로그)"),
    ("single_doc", "기관 B의 필수 산출물은?", "단일 기관 추출 (산출물 목록)"),
    ("comparison", "기관 A와 기관 B의 AI 요구사항 차이 알려줘", "다문서 비교 (품질 vs MLOps)"),
    (
        "comparison",
        "기관 A와 기관 D의 보안 요구사항 차이를 비교해줘",
        "비교 + 부분 부재 (D 없음 → partial)",
    ),
    (
        "follow_up",
        "그 기관이 요구한 보안 조건도 보여줘",
        "후속 질의 (context_entities=['기관 A'])",
    ),
    (
        "abstention",
        "기관 A의 양자암호 적용 방안은?",
        "부재 정보 판별 (insufficient)",
    ),
    (
        "abstention",
        "기관 A의 보안과 드론은?",
        "1-of-2 토픽 — 부재 유지 (issue #89)",
    ),
]

VALID_QUERY_TYPES = {"single_doc", "comparison", "follow_up", "abstention"}

STATUS_BADGE: dict[str, str] = {
    "supported": "🟢 supported",
    "partial": "🟡 partial",
    "insufficient": "🔴 insufficient",
}


def run_pipeline(
    index: dict[str, Any],
    query: str,
    *,
    pipeline: str,
    top_k: int | None,
    retrieval_mode: str,
    context_entities: list[str],
) -> dict[str, Any]:
    """Thin wrapper around ``rag_core.run_rag_query`` that adds wall time.

    Kept here (instead of inlined in the Streamlit module) so the
    timing convention is testable and so the demo can be exercised
    headlessly in scripts / tests that have not installed Streamlit.
    """
    from rag_core import run_rag_query

    started = time.perf_counter()
    result = run_rag_query(
        index,
        query,
        pipeline=pipeline,
        top_k=top_k,
        retrieval_mode=retrieval_mode,
        context_entities=context_entities,
    )
    result["_wall_ms"] = (time.perf_counter() - started) * 1000.0
    return result


__all__ = [
    "SAMPLE_QUERIES",
    "STATUS_BADGE",
    "VALID_QUERY_TYPES",
    "run_pipeline",
]
