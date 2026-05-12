"""Contract test for the Reranker Protocol (#345, follow-up to #332).

Single test file by design — heavier behavior assertions
(stub-backend identity pass-through, bge / cohere shape, postcondition
guards) already live in ``tests/test_cross_encoder_rerank.py`` against
``rag_rerank.rerank`` itself. This file only nails down the Protocol
surface: ``default_reranker()`` returns a ``Reranker`` whose ``rerank``
delegation produces the same shape as the underlying
``rag_rerank.rerank`` contract.
"""

from __future__ import annotations

import pytest

from rag_reranker import CrossEncoderReranker, Reranker, default_reranker


def test_default_reranker_is_cross_encoder() -> None:
    reranker = default_reranker()
    assert isinstance(reranker, Reranker)
    assert isinstance(reranker, CrossEncoderReranker)


def test_cross_encoder_reranker_delegates_under_stub_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stub backend is identity pass-through (see rag_rerank.py
    docstring on the full_reranker / full byte-equivalence contract);
    the Protocol must preserve that semantics so a hashing-CI eval
    swap from direct ``rag_rerank.rerank`` to ``default_reranker()``
    leaves ``eval_summary.json`` byte-identical."""
    monkeypatch.setenv("BIDMATE_RERANK_BACKEND", "stub")
    candidates = [
        {"chunk_id": "a", "text": "alpha", "score": 0.5},
        {"chunk_id": "b", "text": "beta", "score": 0.3},
        {"chunk_id": "c", "text": "gamma", "score": 0.1},
    ]
    reordered, meta = default_reranker().rerank(
        "irrelevant query", candidates, top_n=3
    )
    assert reordered == candidates
    assert meta["backend"] == "stub"
    assert meta["fell_back"] is False
    assert meta["candidates_scored"] == 3


def test_cross_encoder_reranker_empty_candidates_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDMATE_RERANK_BACKEND", "stub")
    reordered, meta = default_reranker().rerank("q", [], top_n=5)
    assert reordered == []
    assert meta["fell_back"] is False
