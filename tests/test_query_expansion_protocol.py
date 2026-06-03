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
    DEFAULT_MAX_TOKENS,
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


# --- default_expander 분기 매트릭스 (graceful-degradation 계약, line 246-253) ---
# 기존 test_default_expander_hyde_dispatch_returns_hyde 가 hyde/HyDE/identity/
# typo 분기를 덮으므로, 여기서는 그 테스트가 건드리지 않는 분기만 고정한다.


def test_default_expander_none_value_is_identity() -> None:
    """``query_expansion`` 키는 존재하나 값이 ``None`` 이면 identity.
    ``if raw is not None`` 분기 — 키 자체가 없는 경로(기존 테스트)와는
    다른 코드 경로다."""
    assert isinstance(
        default_expander({"query_expansion": None}), IdentityExpander
    )


def test_default_expander_empty_or_blank_value_is_identity() -> None:
    """빈/공백 문자열 → ``strip()`` 후 ``"" or "identity"`` → identity.
    eval/config.yaml 에 빈 값이 들어가도 crash 대신 graceful degrade."""
    assert isinstance(default_expander({"query_expansion": ""}), IdentityExpander)
    assert isinstance(
        default_expander({"query_expansion": "   "}), IdentityExpander
    )


def test_default_expander_strips_and_lowercases_hyde() -> None:
    """주변 공백 + 대소문자 혼용도 ``strip().lower()`` 후 hyde dispatch.
    config 값에 우발적 공백/대문자가 있어도 opt-in 이 살아있어야 한다."""
    assert isinstance(
        default_expander({"query_expansion": "  hyde  "}), HyDEExpander
    )
    assert isinstance(
        default_expander({"query_expansion": "  HYDE\n"}), HyDEExpander
    )


def test_default_expander_non_string_value_coerced_to_identity() -> None:
    """비-문자열 값은 ``str(raw)`` 로 강제되어 unknown → identity.
    YAML 이 정수/불리언을 주더라도 retrieval 을 crash 시키지 않는다."""
    assert isinstance(
        default_expander({"query_expansion": 123}), IdentityExpander
    )
    assert isinstance(
        default_expander({"query_expansion": True}), IdentityExpander
    )


def test_default_expander_returns_fresh_instance() -> None:
    """``default_reranker()`` 와 같은 idiom — 매 호출 새 인스턴스 반환.
    호출자가 module-level state 없이 테스트에서 구현을 교체할 수 있어야
    한다 (docstring 계약)."""
    assert default_expander({"query_expansion": "hyde"}) is not default_expander(
        {"query_expansion": "hyde"}
    )
    assert default_expander() is not default_expander()


# --- IdentityExpander meta 계약 완전성 ---


def test_identity_expander_meta_is_complete_and_ignores_plan() -> None:
    """Identity meta 는 6개 키를 전부 채우고 plan 내용을 무시한다.
    plan 에 ``query_expansion='hyde'`` 가 있어도 ``IdentityExpander.expand``
    자체는 passthrough — dispatch 는 ``default_expander`` 의 책임이다."""
    query = "사업비 산정 기준은?"
    expanded, meta = IdentityExpander().expand(
        query, plan={"query_expansion": "hyde", "top_k": 9}
    )
    assert expanded == query
    assert meta == {
        "backend": "identity",
        "model": None,
        "fell_back": False,
        "fallback_reason": None,
        "latency_ms": 0.0,
        "expanded_length": len(query),
    }


def test_identity_expander_empty_query() -> None:
    """빈 쿼리도 그대로 통과 — ``expanded_length == 0``, fallback 아님."""
    expanded, meta = IdentityExpander().expand("", plan={})
    assert expanded == ""
    assert meta["expanded_length"] == 0
    assert meta["fell_back"] is False


# --- HyDEExpander 성공 경로 세부 계약 ---


def test_hyde_expander_strips_surrounding_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """성공 응답에 앞뒤 공백이 있으면 ``strip`` 되어 반환되고
    ``expanded_length`` 는 stripped 길이로 갱신된다 (padded raw 길이 아님)."""
    core = "보안 통제 요구사항은 접근 통제를 포함합니다."
    monkeypatch.setattr(
        "rag_query_expansion._call_anthropic_hyde",
        lambda **_: f"\n\n  {core}  \n",
    )
    expanded, meta = HyDEExpander().expand("질의", plan={})
    assert expanded == core  # stripped, not the padded raw response
    assert meta["fell_back"] is False
    assert meta["expanded_length"] == len(core)


def test_hyde_expander_ctor_model_wins_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``__init__(model=..., max_tokens=...)`` 이 env / default 보다 우선하고
    그 값이 ``_call_anthropic_hyde`` 와 meta 양쪽에 전파된다."""
    seen = {}

    def fake_call(*, model: str, max_tokens: int, **_: object) -> str:
        seen["model"] = model
        seen["max_tokens"] = max_tokens
        return "passage"

    monkeypatch.setattr("rag_query_expansion._call_anthropic_hyde", fake_call)
    monkeypatch.setenv("BIDMATE_QUERY_EXPANSION_MODEL", "env-model")

    _, meta = HyDEExpander(model="ctor-model", max_tokens=42).expand(
        "질의", plan={}
    )
    assert seen["model"] == "ctor-model"  # ctor over env
    assert seen["max_tokens"] == 42
    assert meta["model"] == "ctor-model"


def test_hyde_expander_env_model_wins_over_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ctor override 부재 시 env 가 default 모델보다 우선한다."""
    seen = {}

    def fake_call(*, model: str, **_: object) -> str:
        seen["model"] = model
        return "passage"

    monkeypatch.setattr("rag_query_expansion._call_anthropic_hyde", fake_call)
    monkeypatch.setenv("BIDMATE_QUERY_EXPANSION_MODEL", "env-model")

    _, meta = HyDEExpander().expand("질의", plan={})
    assert seen["model"] == "env-model"
    assert meta["model"] == "env-model"


def test_hyde_expander_invalid_max_tokens_falls_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """비정상 ``BIDMATE_QUERY_EXPANSION_MAX_TOKENS`` → ``DEFAULT_MAX_TOKENS``.
    config 오타(``int()`` ValueError)가 expand 를 crash 시키지 않는다."""
    seen = {}

    def fake_call(*, max_tokens: int, **_: object) -> str:
        seen["max_tokens"] = max_tokens
        return "passage"

    monkeypatch.setattr("rag_query_expansion._call_anthropic_hyde", fake_call)
    monkeypatch.setenv("BIDMATE_QUERY_EXPANSION_MAX_TOKENS", "not-an-int")

    HyDEExpander().expand("질의", plan={})
    assert seen["max_tokens"] == DEFAULT_MAX_TOKENS


def test_hyde_expander_fallback_reason_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """긴 예외 메시지는 ``fallback_reason`` 에서 본문 120자로 truncate 된다
    (meta 가 비대해지지 않도록 — ``str(exc)[:120]``)."""
    def boom(**_: object) -> str:
        raise RuntimeError("X" * 500)

    monkeypatch.setattr("rag_query_expansion._call_anthropic_hyde", boom)

    _, meta = HyDEExpander().expand("질의", plan={})
    assert meta["fell_back"] is True
    reason = meta["fallback_reason"]
    assert reason.startswith("backend_error:RuntimeError:")
    assert "X" * 120 in reason  # exactly 120 chars of the message survive
    assert "X" * 121 not in reason
