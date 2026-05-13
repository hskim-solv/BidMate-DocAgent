"""Reranker Protocol — pluggable post-retrieval reordering stage (#345).

The Protocol decouples ``rag_core.apply_fusion_and_reranking`` from the
specific cross-encoder backend dispatch in ``rag_rerank``, so future
reranking strategies (HyDE, LLM-as-judge, custom domain models) can
plug in without modifying retrieval orchestration code. Mirrors the
``VectorStore`` Protocol pattern (``rag_vector_store.py``) introduced
for #176.

``CrossEncoderReranker`` is the default implementation; it delegates
to ``rag_rerank.rerank`` so the existing ``BIDMATE_RERANK_BACKEND``
env-var dispatch (stub / bge / cohere / bge_ko) and the never-raise
fallback contract are preserved unchanged.

``default_reranker()`` returns ``CrossEncoderReranker()`` today; when
a second concrete reranker (e.g. ``HydeReranker``) lands, the plan-
based dispatch becomes a one-file change here — ``rag_core.py`` stays
untouched.

Convention: follows the four-property Protocol-based pluggability pattern
(ADR 0020). New rerankers implement ``Reranker`` and register via
``default_reranker()`` — retrieval orchestration is untouched.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Reranker(Protocol):
    """Pluggable post-retrieval scoring + reordering stage.

    Implementations must NEVER raise; on backend failure they must
    return the input candidates unchanged with ``meta["fell_back"]``
    set, preserving retrieval recall as the fallback contract
    (matches ``rag_rerank.rerank``'s existing guarantee).
    """

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        top_n: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        ...


class CrossEncoderReranker:
    """Default ``Reranker`` — delegates to ``rag_rerank.rerank`` so the
    existing ``BIDMATE_RERANK_BACKEND`` env-var dispatch and the
    never-raise fallback path stay unchanged."""

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        top_n: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        from rag_rerank import rerank as _cross_rerank

        return _cross_rerank(query, candidates, top_n=top_n)


def default_reranker() -> Reranker:
    """The reranker ``apply_fusion_and_reranking`` uses unless a future
    plan-level override is wired in. Returns a fresh instance so callers
    can swap implementations in tests without module-level state."""
    return CrossEncoderReranker()
