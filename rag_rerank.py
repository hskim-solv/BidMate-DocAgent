#!/usr/bin/env python3
"""Cross-encoder reranker as additive ablation (issue #163, ADR 0011 pattern).

The reranker runs *after* the existing 60/25/15 dense+lexical+metadata
blend in ``rag_core.retrieve`` and *before* the ``top_k`` cut. It
re-scores the top-N highest-blend-score candidates with a cross-encoder
model, squashes the resulting logits through sigmoid (so the verifier's
score floor still works — see ``rag_core.py`` line ~2254), and re-sorts.

The reranker is additive: it never introduces new chunk_ids, only
reorders the input set. A postcondition guard rejects any output whose
chunk_ids are not a subset of the input — falling back to input order
keeps the existing recall/precision properties intact on backend
failure.

Backends (``BIDMATE_RERANK_BACKEND``):

* ``stub`` (default) — identity pass-through, CI-deterministic. The
  ``full_reranker`` ablation under stub backend is byte-equivalent to
  ``full`` — that's the contract that lets the hashing-backend CI run
  both rows without spurious deltas.
* ``bge`` — ``BAAI/bge-reranker-v2-m3`` via FlagEmbedding (local, free,
  ~1.1GB model download on first run).
* ``cohere`` — Cohere ``rerank-3.5-multilingual`` (paid). Reads
  ``BIDMATE_COHERE_API_KEY`` or ``COHERE_API_KEY``.
* ``bge_ko`` — ``dragonkue/bge-reranker-v2-m3-ko`` via FlagEmbedding
  (local, Korean-finetuned).

The reranker never raises out of ``rerank()`` — on any unexpected error
it returns the input candidates unchanged with ``meta["fell_back"]`` set
and a ``fallback_reason``.
"""
from __future__ import annotations

import math
import os
import time
from typing import Any

RERANK_SCHEMA_VERSION = 1
ENV_BACKEND = "BIDMATE_RERANK_BACKEND"
ENV_MODEL = "BIDMATE_RERANK_MODEL"
ENV_API_KEY = "BIDMATE_COHERE_API_KEY"
ENV_API_KEY_FALLBACK = "COHERE_API_KEY"

DEFAULT_BACKEND = "stub"
DEFAULT_BGE_MODEL = "BAAI/bge-reranker-v2-m3"
DEFAULT_BGE_KO_MODEL = "dragonkue/bge-reranker-v2-m3-ko"
DEFAULT_COHERE_MODEL = "rerank-3.5-multilingual"
DEFAULT_TOP_N = 30  # Re-score this many top-blend candidates by default.

_RERANKER_CACHE: dict[tuple[str, str], Any] = {}


def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    backend: str | None = None,
    model: str | None = None,
    top_n: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Re-score ``candidates`` with a cross-encoder backend.

    Returns ``(reordered, meta)``. ``reordered`` is the full candidate
    list (length preserved) with the top-N re-scored and re-sorted.
    Candidates beyond top-N are appended in their original order. On any
    guard failure the input candidates are returned unchanged with
    ``meta["fell_back"]`` set.
    """
    backend = (backend or os.environ.get(ENV_BACKEND) or DEFAULT_BACKEND).lower()
    meta: dict[str, Any] = {
        "schema_version": RERANK_SCHEMA_VERSION,
        "backend": backend,
        "model": None,
        "top_n": int(top_n or DEFAULT_TOP_N),
        "candidates_scored": 0,
        "latency_ms": None,
        "fell_back": False,
        "fallback_reason": None,
    }

    if not candidates:
        return candidates, meta

    backend_fn = _BACKENDS.get(backend)
    if backend_fn is None:
        meta["fell_back"] = True
        meta["fallback_reason"] = f"unknown_backend:{backend}"
        return candidates, meta

    n = int(top_n or DEFAULT_TOP_N)
    head = candidates[:n]
    tail = candidates[n:]
    started = time.perf_counter()
    try:
        reordered_head, model_used = backend_fn(query=query, candidates=head, model=model)
    except Exception as exc:  # never raise out
        meta["fell_back"] = True
        meta["fallback_reason"] = f"backend_error:{type(exc).__name__}:{str(exc)[:120]}"
        meta["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return candidates, meta
    meta["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)

    in_ids = {str(c.get("chunk_id")) for c in head}
    out_ids = {str(c.get("chunk_id")) for c in reordered_head}
    if out_ids != in_ids:
        meta["fell_back"] = True
        meta["fallback_reason"] = "chunk_id_postcondition_violation"
        return candidates, meta

    meta["model"] = model_used
    meta["candidates_scored"] = len(reordered_head)
    return list(reordered_head) + list(tail), meta


# -----------------------------------------------------------------------------
# Backends
# -----------------------------------------------------------------------------


def _stub_backend(
    *,
    query: str,
    candidates: list[dict[str, Any]],
    model: str | None,
) -> tuple[list[dict[str, Any]], str]:
    # Identity pass-through. Critical for CI: the stub-backend
    # full_reranker row must be byte-equivalent to the full row, so the
    # hashing-backend eval_summary.json delta stays zero on this PR.
    return list(candidates), "stub"


def _bge_backend(  # pragma: no cover - large model download
    *,
    query: str,
    candidates: list[dict[str, Any]],
    model: str | None,
) -> tuple[list[dict[str, Any]], str]:
    model_id = model or os.environ.get(ENV_MODEL) or DEFAULT_BGE_MODEL
    reranker = _get_or_load_flag_reranker(model_id)
    return _score_with_flag_reranker(query, candidates, reranker, model_id)


def _bge_ko_backend(  # pragma: no cover - large model download
    *,
    query: str,
    candidates: list[dict[str, Any]],
    model: str | None,
) -> tuple[list[dict[str, Any]], str]:
    model_id = model or os.environ.get(ENV_MODEL) or DEFAULT_BGE_KO_MODEL
    reranker = _get_or_load_flag_reranker(model_id)
    return _score_with_flag_reranker(query, candidates, reranker, model_id)


def _cohere_backend(  # pragma: no cover - network
    *,
    query: str,
    candidates: list[dict[str, Any]],
    model: str | None,
) -> tuple[list[dict[str, Any]], str]:
    try:
        import cohere  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "cohere backend requires the cohere SDK. "
            "Install with `pip install cohere` or use BIDMATE_RERANK_BACKEND=stub."
        ) from exc

    api_key = os.environ.get(ENV_API_KEY) or os.environ.get(ENV_API_KEY_FALLBACK)
    if not api_key:
        raise RuntimeError(
            f"{ENV_API_KEY} (or {ENV_API_KEY_FALLBACK}) is not set for backend=cohere."
        )

    model_id = model or os.environ.get(ENV_MODEL) or DEFAULT_COHERE_MODEL
    client = cohere.ClientV2(api_key=api_key)
    documents = [str(c.get("text") or "") for c in candidates]
    # Use the explicit `client.v2.rerank()` path recommended by the
    # cohere-python 5.x reference docs. `ClientV2.rerank()` (the
    # alias used historically) routes to the same v2 endpoint, but
    # the explicit form is future-proof if `ClientV2` later exposes
    # additional non-v2 methods.
    response = client.v2.rerank(model=model_id, query=query, documents=documents)
    by_index = {item.index: float(item.relevance_score) for item in response.results}
    reordered = []
    for idx, candidate in enumerate(candidates):
        score = by_index.get(idx, 0.0)
        # Cohere relevance_score is already in [0,1] — skip sigmoid.
        updated = _attach_cross_encoder_score(candidate, score, sigmoid=False)
        reordered.append(updated)
    reordered.sort(key=lambda item: item["score"], reverse=True)
    return reordered, model_id


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _get_or_load_flag_reranker(model_id: str) -> Any:  # pragma: no cover - large model
    cache_key = ("flag", model_id)
    cached = _RERANKER_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "bge / bge_ko backend requires FlagEmbedding. "
            "Install with `pip install FlagEmbedding` or use BIDMATE_RERANK_BACKEND=stub."
        ) from exc
    reranker = FlagReranker(model_id, use_fp16=False)
    _RERANKER_CACHE[cache_key] = reranker
    return reranker


def _score_with_flag_reranker(  # pragma: no cover - large model
    query: str,
    candidates: list[dict[str, Any]],
    reranker: Any,
    model_id: str,
) -> tuple[list[dict[str, Any]], str]:
    pairs = [[query, str(c.get("text") or "")] for c in candidates]
    raw_scores = reranker.compute_score(pairs)
    if not isinstance(raw_scores, list):
        raw_scores = [raw_scores]
    reordered = []
    for candidate, raw in zip(candidates, raw_scores):
        updated = _attach_cross_encoder_score(candidate, float(raw), sigmoid=True)
        reordered.append(updated)
    reordered.sort(key=lambda item: item["score"], reverse=True)
    return reordered, model_id


def _attach_cross_encoder_score(
    candidate: dict[str, Any],
    raw_score: float,
    *,
    sigmoid: bool,
) -> dict[str, Any]:
    if sigmoid:
        # Cross-encoder logits aren't in [0,1]. The verifier score floor
        # at rag_core.py ~L2254 (threshold 0.18) was tuned for normalized
        # scores — sigmoid squash keeps it working without per-backend
        # branches.
        squashed = 1.0 / (1.0 + math.exp(-raw_score))
    else:
        squashed = max(0.0, min(1.0, raw_score))
    updated = dict(candidate)
    score_parts = dict(updated.get("score_parts") or {})
    score_parts["cross_encoder"] = round(float(squashed), 6)
    updated["score_parts"] = score_parts
    updated["score"] = round(float(squashed), 6)
    return updated


_BACKENDS = {
    "stub": _stub_backend,
    "bge": _bge_backend,
    "bge_ko": _bge_ko_backend,
    "cohere": _cohere_backend,
}


__all__ = [
    "RERANK_SCHEMA_VERSION",
    "DEFAULT_BACKEND",
    "DEFAULT_TOP_N",
    "ENV_BACKEND",
    "ENV_MODEL",
    "rerank",
]
