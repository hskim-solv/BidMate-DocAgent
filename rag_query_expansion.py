"""Query expansion Protocol — pluggable pre-retrieval query rewrite (#396).

The ``QueryExpander`` Protocol decouples ``rag_core.retrieve_candidates``
from the specific query-side rewrite backend, so future strategies
(multi-query rewrite, LLM-as-judge query reformulation, custom domain
templates) can plug in without modifying retrieval orchestration code.
Mirrors the ``Reranker`` Protocol pattern (``rag_reranker.py``, #345/#358).

``IdentityExpander`` is the default; it returns the query unchanged so
the ADR 0001 ``naive_baseline`` invariant — bit-identical top-K scores
against ``tests/data/naive_baseline_top_k.json`` — is preserved by
construction. ``HyDEExpander`` is the first opt-in implementation
(Hypothetical Document Embeddings, Gao et al. 2022): an LLM generates
a short hypothetical RFP-style answer passage; that passage is used as
the dense-embedding target instead of the raw query.

Critical contract: HyDE replaces ONLY the dense-embedding input. The
lexical / BM25 / metadata scoring paths in ``retrieve_candidates``
consume tokens from ``analysis`` (not the raw query string), so they
remain invariant under expansion. See ADR 0022 for the design rationale.

Never-raise: ``HyDEExpander.expand`` catches every backend exception
(SDK import, API key missing, network, parsing) and falls back to the
original query with ``meta["fell_back"] = True``. No exception escapes
into ``retrieve_candidates``.
"""
from __future__ import annotations

import os
import time
from typing import Any, Protocol, runtime_checkable

# Env-var contract (mirrors rag_synthesis.py / rag_rerank.py idioms).
ENV_BACKEND = "BIDMATE_QUERY_EXPANSION_BACKEND"
ENV_MODEL = "BIDMATE_QUERY_EXPANSION_MODEL"
ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
ENV_MAX_TOKENS = "BIDMATE_QUERY_EXPANSION_MAX_TOKENS"

DEFAULT_BACKEND = "identity"
# Haiku is the right cost/latency point for a 2-3 sentence rewrite. The
# expansion is single-shot, temperature 0.0 — quality variance comes from
# prompt design (ADR 0022), not model choice.
DEFAULT_HYDE_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 256

# Bilingual single-shot prompt. Korean public-sector RFPs use formal
# 합니다-체 with domain terminology; the hypothetical passage must match
# that register so its dense embedding aligns with corpus chunks.
HYDE_SYSTEM_PROMPT = (
    "You are an expert that generates brief hypothetical RFP (Request "
    "for Proposal / 제안요청서) answer passages in formal Korean "
    "(합니다체). Given a user query, write a 2-3 sentence answer as if "
    "quoting directly from a Korean public-sector RFP document. Use "
    "domain terms (보안 통제, 평가 기준, 사업비, 납품 일정, etc.) "
    "naturally. Do NOT add citations, bullet points, headings, or "
    "commentary — output the answer text only."
)


@runtime_checkable
class QueryExpander(Protocol):
    """Pluggable pre-retrieval query rewrite stage.

    Implementations must NEVER raise; on backend failure they must
    return the input query unchanged with ``meta["fell_back"]`` set,
    preserving retrieval recall as the fallback contract (matches the
    ``rag_rerank.rerank`` / ``rag_synthesis.synthesize_answer``
    never-raise guarantee).
    """

    def expand(
        self,
        query: str,
        *,
        plan: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        ...


class IdentityExpander:
    """Default ``QueryExpander`` — returns the query unchanged.

    Used by ``naive_baseline`` and any preset that does not opt into
    query expansion. Deterministic, no LLM call, no env-var read. This
    is the implementation that keeps the ADR 0001 golden file
    (``tests/data/naive_baseline_top_k.json``) bit-identical across the
    PR seam.
    """

    def expand(
        self,
        query: str,
        *,
        plan: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        return query, {
            "backend": "identity",
            "model": None,
            "fell_back": False,
            "fallback_reason": None,
            "latency_ms": 0.0,
            "expanded_length": len(query),
        }


class HyDEExpander:
    """Opt-in ``QueryExpander`` — Hypothetical Document Embeddings.

    Calls the Anthropic API to generate a short hypothetical RFP-style
    answer passage; the passage text is what gets embedded for the
    dense-retrieval path. Lexical / BM25 paths are untouched (they
    consume ``analysis.tokens`` upstream of this call site).

    Never-raise: every backend error path (SDK import, missing key,
    API exception, empty / whitespace response) returns ``(query, meta)``
    with ``meta["fell_back"] = True`` and a structured
    ``fallback_reason`` string. ``retrieve_candidates`` continues with
    the original query embedding under fallback.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        # Allow tests / callers to inject overrides without env-var
        # plumbing; falls back to env / default when None.
        self._model = model
        self._max_tokens = max_tokens

    def expand(
        self,
        query: str,
        *,
        plan: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        model = self._model or os.environ.get(ENV_MODEL) or DEFAULT_HYDE_MODEL
        try:
            max_tokens = int(
                self._max_tokens
                if self._max_tokens is not None
                else os.environ.get(ENV_MAX_TOKENS) or DEFAULT_MAX_TOKENS
            )
        except (TypeError, ValueError):
            max_tokens = DEFAULT_MAX_TOKENS

        meta: dict[str, Any] = {
            "backend": "hyde",
            "model": model,
            "fell_back": False,
            "fallback_reason": None,
            "latency_ms": None,
            "expanded_length": len(query),
        }

        started = time.perf_counter()
        try:
            expanded = _call_anthropic_hyde(
                query=query, model=model, max_tokens=max_tokens
            )
        except Exception as exc:  # never raise out
            meta["fell_back"] = True
            meta["fallback_reason"] = (
                f"backend_error:{type(exc).__name__}:{str(exc)[:120]}"
            )
            meta["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            return query, meta

        meta["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)

        cleaned = (expanded or "").strip()
        if not cleaned:
            meta["fell_back"] = True
            meta["fallback_reason"] = "empty_response"
            return query, meta

        meta["expanded_length"] = len(cleaned)
        return cleaned, meta


def _call_anthropic_hyde(
    *,
    query: str,
    model: str,
    max_tokens: int,
) -> str:  # pragma: no cover - network
    """Lazy-import the Anthropic SDK and call it for HyDE expansion.

    Separated from ``HyDEExpander.expand`` so tests can monkeypatch this
    function without instantiating the SDK. Raises on any error — the
    caller is responsible for never-raise wrapping.
    """
    try:
        import anthropic  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "hyde backend requires the anthropic SDK. Install with "
            "`pip install anthropic` or set "
            "BIDMATE_QUERY_EXPANSION_BACKEND=identity."
        ) from exc

    api_key = os.environ.get(ENV_ANTHROPIC_KEY)
    if not api_key:
        raise RuntimeError(f"{ENV_ANTHROPIC_KEY} is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.0,
        system=[
            {
                "type": "text",
                "text": HYDE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": query}],
    )
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", None)
            if text:
                return str(text)
    return ""


def default_expander(plan: dict[str, Any] | None = None) -> QueryExpander:
    """Factory used by ``retrieve_candidates``.

    Dispatches on ``plan["query_expansion"]`` (string discriminator,
    case-insensitive). Unknown values silently fall through to identity
    so a typo in eval/config.yaml degrades gracefully rather than
    crashing retrieval.

    Returns a fresh instance so callers can swap implementations in
    tests without module-level state — same idiom as ``default_reranker()``.
    """
    expansion_kind = "identity"
    if plan is not None:
        raw = plan.get("query_expansion")
        if raw is not None:
            expansion_kind = str(raw).strip().lower() or "identity"
    if expansion_kind == "hyde":
        return HyDEExpander()
    return IdentityExpander()


__all__ = [
    "DEFAULT_BACKEND",
    "DEFAULT_HYDE_MODEL",
    "ENV_BACKEND",
    "ENV_MODEL",
    "ENV_ANTHROPIC_KEY",
    "ENV_MAX_TOKENS",
    "HYDE_SYSTEM_PROMPT",
    "HyDEExpander",
    "IdentityExpander",
    "QueryExpander",
    "default_expander",
]
