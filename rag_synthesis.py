#!/usr/bin/env python3
"""LLM answer synthesis path for ADR 0011.

The synthesizer is an *additive* renderer for the structured answer
produced by ``rag_core.generate_answer``. It rewrites only ``summary``
and ``answer_text`` while leaving ``status``, ``claims``,
``citations``, ``insufficiency``, and ``status_reason`` untouched — so
the ADR 0003 ``schema_version: 2`` contract is preserved by
construction.

A synthesized response is only accepted if every chunk_id the LLM
references resolves into the evidence list. On any guard failure the
caller falls back to ``rag_core.render_answer_text``.

Backends (``BIDMATE_SYNTHESIS_BACKEND``):

* ``stub`` (default) — deterministic, offline, no SDK requirement.
  Produces a templated paragraph from the extractive claims.
* ``anthropic`` — Claude API (Sonnet 4.6 default). Uses prompt caching
  on the system prompt and tool use for structured output. Requires
  ``ANTHROPIC_API_KEY``. ``BIDMATE_SYNTHESIS_MODEL`` overrides the
  model id.
* ``openai_compatible`` — generic OpenAI-compatible endpoint
  (vLLM / llama.cpp / Solar / KURE-finetuned). Reads
  ``BIDMATE_SYNTHESIS_API_KEY``, ``BIDMATE_SYNTHESIS_MODEL``,
  ``BIDMATE_SYNTHESIS_BASE_URL``.

The synthesizer never raises out to the pipeline — on any unexpected
error it returns ``(None, meta_with_fallback_reason)`` and the caller
keeps the deterministic answer.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

SYNTHESIS_SCHEMA_VERSION = 2
ENV_BACKEND = "BIDMATE_SYNTHESIS_BACKEND"
ENV_MODEL = "BIDMATE_SYNTHESIS_MODEL"
ENV_API_KEY = "BIDMATE_SYNTHESIS_API_KEY"
ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
ENV_BASE_URL = "BIDMATE_SYNTHESIS_BASE_URL"
ENV_MAX_TOKENS = "BIDMATE_SYNTHESIS_MAX_TOKENS"
# Trace v2 surface (issue #967) — when set to "1", backends capture full
# ``user_prompt_text`` + ``completion_text`` on the returned dict, and
# ``rag_tracing.build_result_trace`` surfaces them as ``synthesis_llm_call``.
# Default off so ADR 0001 run-to-run determinism + ADR 0005 commit boundary
# are unchanged; only env=on traces add the new fields.
ENV_TRACE_FULL = "BIDMATE_TRACE_FULL"


def _trace_full_enabled() -> bool:
    return os.environ.get(ENV_TRACE_FULL) == "1"


DEFAULT_BACKEND = "stub"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 1024
EVIDENCE_TEXT_LIMIT = 600
EVIDENCE_FOR_PROMPT = 6

# Public list-pricing per million tokens (USD) used for portfolio-side
# cost estimation only — NOT an Anthropic billing source of truth. The
# real invoice authority is the Anthropic console; these constants let
# the eval surface flag order-of-magnitude regressions ("a refactor
# 10x'd token spend") without a billing API dependency. Update when
# Anthropic publishes new tiers.
PRICING_PER_MTOK_USD: dict[str, dict[str, float]] = {
    # Claude 4.x family (input/output, plus the standard 0.1x cache-read
    # discount and 1.25x cache-write surcharge on input).
    "claude-opus-4-7": {
        "input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75,
    },
    "claude-sonnet-4-6": {
        "input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 1.0, "output": 5.0, "cache_read": 0.10, "cache_write": 1.25,
    },
}


def _resolve_pricing(model: str | None) -> dict[str, float] | None:
    if not model:
        return None
    # Allow versioned ids (e.g. ``claude-sonnet-4-6-20260301``) to match
    # the base entry — we look up by longest known prefix.
    candidates = [m for m in PRICING_PER_MTOK_USD if model.startswith(m)]
    if not candidates:
        return None
    best = max(candidates, key=len)
    return PRICING_PER_MTOK_USD[best]


def compute_cost_usd(
    *,
    model: str | None,
    tokens_in: int | None,
    tokens_out: int | None,
    cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None,
) -> float | None:
    """Estimate USD cost from token counts and the model price card.

    Returns ``None`` when the model is unknown (e.g. ``stub`` or any
    openai-compatible endpoint where local pricing is not modeled).
    ``tokens_in`` is the *uncached* input tokens — cache-read and
    cache-write tokens are billed separately and must be passed
    explicitly, not double-counted.
    """
    pricing = _resolve_pricing(model)
    if pricing is None:
        return None
    cost = 0.0
    if tokens_in:
        cost += (tokens_in / 1_000_000.0) * pricing["input"]
    if tokens_out:
        cost += (tokens_out / 1_000_000.0) * pricing["output"]
    if cache_read_tokens:
        cost += (cache_read_tokens / 1_000_000.0) * pricing["cache_read"]
    if cache_write_tokens:
        cost += (cache_write_tokens / 1_000_000.0) * pricing["cache_write"]
    # Six-decimal rounding: the typical per-query spend is fractions of a cent.
    return round(cost, 6)

SYSTEM_PROMPT = (
    "You rewrite the summary of an answer produced by a retrieval-augmented "
    "system for Korean RFP (Request-For-Proposal) documents. The deterministic "
    "verifier has already extracted the claims and validated the citations. "
    "Your job is to weave those claims into a natural, concise Korean answer "
    "(2-4 sentences). You MUST cite by referencing chunk_ids in square "
    "brackets, e.g. [doc-a#0003]. You MUST NOT introduce a chunk_id that is "
    "not in the provided evidence list. You MUST NOT contradict, weaken, or "
    "expand beyond the claims. If a claim cites a chunk, your summary must "
    "preserve that linkage. Do not invent agencies, deadlines, budgets, or "
    "numbers."
)

TOOL_DEFINITION = {
    "name": "emit_summary",
    "description": (
        "Emit the rewritten summary and the chunk_ids it references. "
        "used_chunk_ids must be a subset of the evidence's chunk_ids."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "2-4 sentence Korean answer weaving the claims naturally with [chunk_id] citations.",
            },
            "used_chunk_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Every chunk_id referenced in the summary.",
            },
        },
        "required": ["summary", "used_chunk_ids"],
    },
}


def synthesize_answer(
    query: str,
    analysis: dict[str, Any],
    answer: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    backend: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Try to synthesize an enriched summary for an extractive answer.

    Returns ``(updated_answer | None, meta)``. ``updated_answer`` is
    ``None`` when the caller should keep the deterministic answer; in
    that case ``meta['fell_back']`` is True with a reason. The returned
    answer is always a deep-enough copy that the caller can use it
    directly without aliasing.
    """
    backend = (backend or os.environ.get(ENV_BACKEND) or DEFAULT_BACKEND).lower()
    meta: dict[str, Any] = {
        "schema_version": SYNTHESIS_SCHEMA_VERSION,
        "backend": backend,
        "model": None,
        "tokens_in": None,
        "tokens_out": None,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "cost_estimate_usd": None,
        "latency_ms": None,
        "fell_back": False,
        "fallback_reason": None,
    }

    backend_fn = _BACKENDS.get(backend)
    if backend_fn is None:
        meta["fell_back"] = True
        meta["fallback_reason"] = f"unknown_backend:{backend}"
        return None, meta

    allowed_chunk_ids = {
        str(item.get("chunk_id")) for item in evidence if item.get("chunk_id")
    }
    if not allowed_chunk_ids:
        meta["fell_back"] = True
        meta["fallback_reason"] = "no_evidence_chunks"
        return None, meta

    started = time.perf_counter()
    try:
        payload = backend_fn(query=query, analysis=analysis, answer=answer, evidence=evidence)
    except Exception as exc:  # never raise out
        meta["fell_back"] = True
        meta["fallback_reason"] = f"backend_error:{type(exc).__name__}:{str(exc)[:120]}"
        meta["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return None, meta
    meta["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)

    summary = str(payload.get("summary") or "").strip()
    used_chunk_ids = [str(cid) for cid in (payload.get("used_chunk_ids") or [])]
    if not summary:
        meta["fell_back"] = True
        meta["fallback_reason"] = "empty_summary"
        return None, meta

    invalid_chunks = [cid for cid in used_chunk_ids if cid not in allowed_chunk_ids]
    if invalid_chunks:
        meta["fell_back"] = True
        meta["fallback_reason"] = "unauthorized_chunk_ids:" + ",".join(invalid_chunks[:3])
        return None, meta

    claim_chunk_ids = _claim_chunk_ids(answer)
    if claim_chunk_ids and used_chunk_ids:
        out_of_claim = [cid for cid in used_chunk_ids if cid not in claim_chunk_ids]
        if out_of_claim:
            meta["fell_back"] = True
            meta["fallback_reason"] = "chunks_outside_claims:" + ",".join(out_of_claim[:3])
            return None, meta

    updated = dict(answer)
    updated["summary"] = summary
    updated["answer_text"] = _render_with_synthesis(summary, answer)

    meta["model"] = payload.get("model")
    meta["tokens_in"] = payload.get("tokens_in")
    meta["tokens_out"] = payload.get("tokens_out")
    meta["cache_read_tokens"] = payload.get("cache_read_tokens")
    meta["cache_write_tokens"] = payload.get("cache_write_tokens")
    # Trace v2 (issue #967) — env-gated full I/O surface for synthesis.
    # ``meta["user_prompt_text"]`` / ``["completion_text"]`` are absent when
    # env=off (existing consumers see no schema change).
    if _trace_full_enabled() and "user_prompt_text" in payload:
        meta["user_prompt_text"] = payload.get("user_prompt_text")
        meta["completion_text"] = payload.get("completion_text")
    meta["cost_estimate_usd"] = compute_cost_usd(
        model=meta["model"],
        tokens_in=meta["tokens_in"],
        tokens_out=meta["tokens_out"],
        cache_read_tokens=meta["cache_read_tokens"],
        cache_write_tokens=meta["cache_write_tokens"],
    )
    meta["used_chunk_ids"] = used_chunk_ids
    return updated, meta


def _claim_chunk_ids(answer: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for claim in answer.get("claims") or []:
        for citation in claim.get("citations") or []:
            chunk_id = citation.get("chunk_id")
            if chunk_id:
                out.add(str(chunk_id))
    return out


def _render_with_synthesis(summary: str, answer: dict[str, Any]) -> str:
    lines = [summary]
    for claim in answer.get("claims") or []:
        citations = claim.get("citations") or []
        citation_ids = ", ".join(
            citation.get("chunk_id", "")
            for citation in citations
            if citation.get("chunk_id")
        )
        suffix = f" [{citation_ids}]" if citation_ids else ""
        lines.append(f"- {claim.get('target')}: {claim.get('claim')}{suffix}")
    insufficiency = answer.get("insufficiency")
    if insufficiency:
        reasons = ", ".join(insufficiency.get("reasons") or [])
        missing_targets = ", ".join(insufficiency.get("missing_targets") or [])
        details = []
        if reasons:
            details.append(f"사유: {reasons}")
        if missing_targets:
            details.append(f"확인 필요 대상: {missing_targets}")
        if details:
            lines.append("- 근거 부족: " + "; ".join(details))
    return "\n".join(line for line in lines if line)


def _format_evidence_for_prompt(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "(no evidence)"
    parts: list[str] = []
    for item in evidence[:EVIDENCE_FOR_PROMPT]:
        chunk_id = str(item.get("chunk_id") or "")
        doc_id = str(item.get("doc_id") or "")
        agency = str(item.get("agency") or "")
        text = str(item.get("text") or "")[:EVIDENCE_TEXT_LIMIT]
        head = f"[{chunk_id}] doc={doc_id} agency={agency}".rstrip()
        parts.append(f"{head}\n{text}")
    return "\n\n".join(parts)


def _format_claims_for_prompt(answer: dict[str, Any]) -> str:
    claims = answer.get("claims") or []
    if not claims:
        return "(no claims)"
    lines: list[str] = []
    for claim in claims:
        citation_ids = ", ".join(
            c.get("chunk_id", "")
            for c in claim.get("citations") or []
            if c.get("chunk_id")
        )
        suffix = f" [{citation_ids}]" if citation_ids else ""
        lines.append(f"- {claim.get('target')}: {claim.get('claim')}{suffix}")
    return "\n".join(lines)


def _build_user_prompt(
    query: str,
    analysis: dict[str, Any],
    answer: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> str:
    return (
        f"Query: {query}\n"
        f"Query type: {analysis.get('query_type') or 'unknown'}\n"
        f"Entities: {', '.join(analysis.get('entities') or []) or 'none'}\n\n"
        f"Verified claims (you must respect these):\n"
        f"{_format_claims_for_prompt(answer)}\n\n"
        f"Evidence chunks (your only citation universe):\n"
        f"{_format_evidence_for_prompt(evidence)}\n\n"
        "Rewrite the summary in 2-4 natural Korean sentences. Cite by "
        "[chunk_id]. Do not add facts beyond the claims. Call emit_summary."
    )


# -----------------------------------------------------------------------------
# Backends
# -----------------------------------------------------------------------------


def _stub_backend(
    *,
    query: str,
    analysis: dict[str, Any],
    answer: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    # Pass through the extractive summary so the LLM path produces
    # identical metrics to agentic_full on stub-mode eval — making the
    # `full_llm` column a zero-regression contract test, with quality
    # gains scoped to live backends.
    summary = str(answer.get("summary") or "").strip()
    used: list[str] = []
    for claim in answer.get("claims") or []:
        for citation in claim.get("citations") or []:
            cid = citation.get("chunk_id")
            if cid and cid not in used:
                used.append(str(cid))
    return {
        "summary": summary,
        "used_chunk_ids": used,
        "model": "stub",
        "tokens_in": None,
        "tokens_out": None,
    }


def _anthropic_backend(  # pragma: no cover - network
    *,
    query: str,
    analysis: dict[str, Any],
    answer: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        import anthropic  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "anthropic backend requires the anthropic SDK. "
            "Install with `pip install anthropic` or use BIDMATE_SYNTHESIS_BACKEND=stub."
        ) from exc

    api_key = os.environ.get(ENV_ANTHROPIC_KEY)
    if not api_key:
        raise RuntimeError(f"{ENV_ANTHROPIC_KEY} is not set.")

    model = os.environ.get(ENV_MODEL) or DEFAULT_ANTHROPIC_MODEL
    max_tokens = int(os.environ.get(ENV_MAX_TOKENS) or DEFAULT_MAX_TOKENS)

    client = anthropic.Anthropic(api_key=api_key)
    user_prompt = _build_user_prompt(query, analysis, answer, evidence)
    # Tool definitions stay stable across queries, so we mark the LAST
    # tool in the array with cache_control — that creates a cache
    # breakpoint covering tools + system in one block, maximizing hit
    # rate on subsequent calls.
    cached_tool = dict(TOOL_DEFINITION)
    cached_tool["cache_control"] = {"type": "ephemeral"}
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.0,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[cached_tool],
        tool_choice={"type": "tool", "name": TOOL_DEFINITION["name"]},
        messages=[{"role": "user", "content": user_prompt}],
    )

    payload = _extract_tool_payload(response)
    usage = getattr(response, "usage", None)
    result: dict[str, Any] = {
        "summary": payload.get("summary", ""),
        "used_chunk_ids": payload.get("used_chunk_ids", []),
        "model": model,
        "tokens_in": getattr(usage, "input_tokens", None) if usage else None,
        "tokens_out": getattr(usage, "output_tokens", None) if usage else None,
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", None) if usage else None,
        "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", None) if usage else None,
    }
    if _trace_full_enabled():
        # Trace v2 (issue #967): capture full prompt + tool-call payload JSON
        # so rationality_judge (Step 3) can score planner/answer reasoning.
        # ``completion_text`` is the JSON payload of the tool_use block (the
        # actual structured answer); the raw response.content list is not
        # serialisable as-is so we render the extracted payload.
        result["user_prompt_text"] = user_prompt
        result["completion_text"] = json.dumps(payload, ensure_ascii=False)
    return result


def _openai_compatible_backend(  # pragma: no cover - network
    *,
    query: str,
    analysis: dict[str, Any],
    answer: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "openai_compatible backend requires the openai SDK. "
            "Install with `pip install openai` or use BIDMATE_SYNTHESIS_BACKEND=stub."
        ) from exc

    api_key = os.environ.get(ENV_API_KEY)
    if not api_key:
        raise RuntimeError(f"{ENV_API_KEY} is not set.")
    model = os.environ.get(ENV_MODEL)
    if not model:
        raise RuntimeError(f"{ENV_MODEL} is not set.")
    base_url = os.environ.get(ENV_BASE_URL) or None
    max_tokens = int(os.environ.get(ENV_MAX_TOKENS) or DEFAULT_MAX_TOKENS)

    client = OpenAI(api_key=api_key, base_url=base_url)
    user_prompt = _build_user_prompt(query, analysis, answer, evidence)
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": user_prompt
                + '\n\nReply ONLY with JSON: {"summary": "...", "used_chunk_ids": ["..."]}',
            },
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    usage = getattr(response, "usage", None)
    result: dict[str, Any] = {
        "summary": str(parsed.get("summary") or ""),
        "used_chunk_ids": list(parsed.get("used_chunk_ids") or []),
        "model": model,
        "tokens_in": getattr(usage, "prompt_tokens", None) if usage else None,
        "tokens_out": getattr(usage, "completion_tokens", None) if usage else None,
    }
    if _trace_full_enabled():
        # Trace v2 (issue #967): capture full prompt + JSON completion text.
        result["user_prompt_text"] = user_prompt
        result["completion_text"] = content
    return result


def _extract_tool_payload(response: Any) -> dict[str, Any]:
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_DEFINITION["name"]:
            payload = getattr(block, "input", None) or {}
            if isinstance(payload, dict):
                return payload
    return {}


_BACKENDS = {
    "stub": _stub_backend,
    "anthropic": _anthropic_backend,
    "openai_compatible": _openai_compatible_backend,
}


__all__ = [
    "SYNTHESIS_SCHEMA_VERSION",
    "DEFAULT_BACKEND",
    "ENV_BACKEND",
    "ENV_MODEL",
    "PRICING_PER_MTOK_USD",
    "compute_cost_usd",
    "synthesize_answer",
]
