"""Contract tests for the QueryExpander Protocol (#396).

Single test file by design — mirrors ``tests/test_reranker_protocol.py``.
This file nails down the Protocol surface (``default_expander`` returns
a ``QueryExpander``), the deterministic identity passthrough that
preserves the ADR 0001 ``naive_baseline`` invariant, and the
never-raise fallback contract on HyDE backend failure.

LLM-side integration tests (live Anthropic backend) are out of scope
here — the test patches ``rag_query_expansion._call_anthropic_hyde``
so no SDK / network is required.
"""
from __future__ import annotations

import pytest

from rag_query_expansion import (
    HyDEExpander,
    IdentityExpander,
    QueryExpander,
    default_expander,
)


def test_default_expander_is_query_expander() -> None:
    """Without a plan (or with ``query_expansion`` unset) the factory
    must return an ``IdentityExpander`` that satisfies the Protocol.
    This is the path naive_baseline takes — its plan dict carries no
    ``query_expansion`` key, so the dense-embedding call site must
    receive an identity passthrough."""
    expander = default_expander()
    assert isinstance(expander, QueryExpander)
    assert isinstance(expander, IdentityExpander)

    # Also exercise the plan-with-no-key path explicitly.
    expander_with_plan = default_expander({"top_k": 4})
    assert isinstance(expander_with_plan, IdentityExpander)


def test_identity_expander_passthrough() -> None:
    """The default identity backend must return the query bit-identical.
    This is the ADR 0001 invariant: a refactor that swaps direct
    ``embed_query_for_index(query, ...)`` for
    ``embed_query_for_index(expanded, ...)`` where ``expanded`` came
    from ``IdentityExpander`` must produce byte-identical embeddings
    (string == string → same hash backend output)."""
    query = "기관 A의 보안 통제 요구사항은?"
    expanded, meta = IdentityExpander().expand(query, plan={})
    assert expanded == query
    assert meta["backend"] == "identity"
    assert meta["fell_back"] is False
    assert meta["model"] is None
    assert meta["expanded_length"] == len(query)


def test_default_expander_hyde_dispatch_returns_hyde() -> None:
    """A plan that explicitly opts into HyDE must yield a HyDEExpander
    (case-insensitive). Unknown values must fall through to identity
    so a typo in eval/config.yaml doesn't crash retrieval."""
    assert isinstance(default_expander({"query_expansion": "hyde"}), HyDEExpander)
    assert isinstance(default_expander({"query_expansion": "HyDE"}), HyDEExpander)
    assert isinstance(default_expander({"query_expansion": "identity"}), IdentityExpander)
    # Typo / unknown → identity (graceful degrade).
    assert isinstance(default_expander({"query_expansion": "hide"}), IdentityExpander)


def test_hyde_expander_uses_mocked_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``_call_anthropic_hyde`` mocked, ``HyDEExpander.expand`` must
    return the mocked text (not the raw query) and populate meta with
    ``backend='hyde'`` and ``fell_back=False``."""
    fake_passage = (
        "본 사업의 보안 통제 요구사항은 행정안전부 가이드라인을 준수하며, "
        "접근 통제·로그 기록·암호화를 포함합니다."
    )

    def fake_call(*, query: str, model: str, max_tokens: int) -> str:
        return fake_passage

    monkeypatch.setattr("rag_query_expansion._call_anthropic_hyde", fake_call)

    expanded, meta = HyDEExpander().expand(
        "기관 A의 보안 통제 요구사항은?", plan={}
    )
    assert expanded == fake_passage
    assert meta["backend"] == "hyde"
    assert meta["fell_back"] is False
    assert meta["fallback_reason"] is None
    assert meta["model"]  # populated with the model id
    assert meta["expanded_length"] == len(fake_passage)
    assert meta["latency_ms"] is not None and meta["latency_ms"] >= 0


def test_hyde_expander_falls_back_on_llm_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM exceptions MUST NOT escape — the expander returns the
    original query with ``meta['fell_back'] = True``. This locks the
    never-raise contract: a flaky API or missing key during eval
    degrades to identity-style retrieval rather than aborting the run."""
    def boom(*, query: str, model: str, max_tokens: int) -> str:
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr("rag_query_expansion._call_anthropic_hyde", boom)

    query = "기관 A의 보안 통제 요구사항은?"
    expanded, meta = HyDEExpander().expand(query, plan={})
    assert expanded == query  # untouched fallback
    assert meta["backend"] == "hyde"
    assert meta["fell_back"] is True
    assert meta["fallback_reason"] is not None
    assert "RuntimeError" in meta["fallback_reason"]
    assert "simulated API failure" in meta["fallback_reason"]


def test_hyde_expander_empty_response_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty / whitespace-only response is treated as a soft failure:
    same fallback contract, ``fallback_reason='empty_response'``."""
    monkeypatch.setattr(
        "rag_query_expansion._call_anthropic_hyde",
        lambda **_: "   \n  ",
    )

    query = "사업 평가 기준은?"
    expanded, meta = HyDEExpander().expand(query, plan={})
    assert expanded == query
    assert meta["fell_back"] is True
    assert meta["fallback_reason"] == "empty_response"
