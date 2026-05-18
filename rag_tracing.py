"""Tracing, telemetry, and evidence-stripping helpers.

Extracted from ``rag_core.py`` (PR-J4, issue #560) as the fourth slice
of the rag_core decomposition. Owns the observability surface that lives
between the orchestration loop and the trace backend:

- :class:`_StageTimer` — ``time.perf_counter`` accumulator; optionally
  wraps a ``TraceContext.span`` (ADR 0010). Used as a context manager
  inside the orchestration phase functions.
- :func:`_attach_trace_diagnostics` — flushes ``trace_handle.finish``
  and injects ADR 0013 trace fields into ``result['diagnostics']``.
- :func:`summarize_stage_attempt` — per-stage summary dict for the
  planner trace ``attempts`` list.
- :func:`build_query_rewrite_trace` / :func:`build_planner_trace` /
  :func:`build_result_trace` — top-level trace payload builders.
- :func:`redact_trace` — masks sensitive list fields (doc ids, entities)
  for external exposure. ``REDACTED_LIST_PLACEHOLDER`` is the sentinel
  value; imported by ``tests/test_fuzzy_retrieval.py``.
- :func:`strip_internal_scores` — returns evidence items with only the
  public fields (drops ranking internals before API serialization).
- :func:`percentile` / :func:`rate` — scalar helpers consumed by
  ``eval/scorers/alignment.py`` and ``eval/scorers/citation.py``.

Constants:

- :data:`TRACE_SCHEMA_VERSION` — schema version tag embedded in
  ``build_result_trace`` output.
- :data:`REDACTED_LIST_PLACEHOLDER` — sentinel string inserted by
  ``redact_trace``; imported by the test suite.

This module is a leaf in the dependency graph: it imports only from
``rag_metadata_processing`` (for ``normalize_regions`` /
``normalize_page_span`` used by ``strip_internal_scores``) and stdlib.
``rag_core`` re-exports every public name so existing callers remain
unchanged.

JSON-identity guarantee: every function moves byte-for-byte from
``rag_core``. Regression gates remain green:
``tests/test_fuzzy_retrieval.py`` (``redact_trace`` /
``REDACTED_LIST_PLACEHOLDER``), ``tests/test_langgraph_orchestrator_regression.py``.
"""

from __future__ import annotations

import copy
import math
import time
from typing import Any

from rag_metadata_processing import normalize_page_span, normalize_regions


TRACE_SCHEMA_VERSION = 2  # bumped 1→2 in issue #967 (synthesis full I/O env-gated)

REDACTED_LIST_PLACEHOLDER = "<redacted>"


class _StageTimer:
    """Accumulate ``time.perf_counter`` deltas (ms) into a dict bucket.

    Adds the elapsed milliseconds to ``bucket[key]`` so re-entering the same
    key (e.g. a stage invoked twice) sums into a single total.

    Optionally wraps the timed region in a ``TraceContext.span`` (ADR
    0010). The span context manager is best-effort — any exception
    from the backend is swallowed so a misbehaving tracer cannot break
    the pipeline.
    """

    def __init__(
        self,
        bucket: dict[str, float],
        key: str,
        *,
        trace: Any = None,
        attrs: dict[str, Any] | None = None,
    ) -> None:
        self.bucket = bucket
        self.key = key
        self._trace = trace
        self._attrs = attrs or {}
        self._span_cm: Any = None

    def __enter__(self) -> "_StageTimer":
        self._t0 = time.perf_counter()
        if self._trace is not None:
            span_name = self.key[:-3] if self.key.endswith("_ms") else self.key
            try:
                self._span_cm = self._trace.span(span_name, **self._attrs)
                self._span_cm.__enter__()
            except Exception:
                self._span_cm = None
        return self

    def __exit__(self, *exc: Any) -> None:
        elapsed_ms = (time.perf_counter() - self._t0) * 1000
        self.bucket[self.key] = self.bucket.get(self.key, 0.0) + elapsed_ms
        if self._span_cm is not None:
            try:
                self._span_cm.__exit__(*exc)
            except Exception:
                pass


def _attach_trace_diagnostics(
    result: dict[str, Any],
    trace_handle: Any,
    backend_name: str,
    unavailable_reason: str | None,
    trace_error: str | None,
) -> None:
    """Inject the ADR 0013 trace fields into ``result['diagnostics']``.

    Calls ``trace_handle.finish(diagnostics)`` to flush the trace and
    capture a URL when the backend supports one. Any exception in
    ``finish`` is swallowed and recorded — the additive-ablation
    invariant requires that tracing never breaks the query path.
    """
    diagnostics = result.setdefault("diagnostics", {})
    trace_url: str | None = None
    if trace_handle is not None:
        try:
            trace_url = trace_handle.finish(diagnostics)
        except Exception as exc:
            trace_error = (trace_error or "") + f"|finish:{type(exc).__name__}:{str(exc)[:120]}"
    diagnostics["trace_url"] = trace_url
    diagnostics["trace_backend"] = backend_name
    diagnostics["trace_unavailable_reason"] = unavailable_reason
    diagnostics["trace_error"] = trace_error or None


def summarize_stage_attempt(
    plan: dict[str, Any],
    verified: bool,
    verification_reasons: list[str],
    *,
    timings: dict[str, float] | None = None,
) -> dict[str, Any]:
    summary = {
        "stage": plan.get("filter_stage"),
        "pipeline": plan.get("pipeline"),
        "prompt_profile": plan.get("prompt_profile"),
        "metadata_filters": plan.get("metadata_filters") or {},
        "top_k": plan.get("top_k"),
        "retrieval_budget": plan.get("retrieval_budget") or {},
        "candidate_count": plan.get("candidate_count"),
        "parent_candidate_count": plan.get("parent_candidate_count"),
        "total_chunks": plan.get("total_chunks"),
        "filter_fallback_used": plan.get("filter_fallback_used", False),
        "retrieval_mode": plan.get("retrieval_mode", "flat"),
        "verified": verified,
        "verification_reasons": verification_reasons,
        "retrieve_ms": round(float((timings or {}).get("retrieve_ms", 0.0)), 2),
        "verify_ms": round(float((timings or {}).get("verify_ms", 0.0)), 2),
    }
    if plan.get("comparison_coverage") is not None:
        summary["comparison_coverage"] = plan["comparison_coverage"]
    return summary


def build_query_rewrite_trace(
    original_query: str,
    resolved_query: str,
    context_resolution: dict[str, Any],
) -> dict[str, Any]:
    rewritten = bool(resolved_query and resolved_query != original_query)
    source = str(context_resolution.get("source") or "none")
    status = str(context_resolution.get("status") or "")
    if rewritten and source == "conversation_state":
        rewrite_type = "conversation_state_prefix"
    elif source == "context_entities":
        rewrite_type = "explicit_context"
    elif status == "needs_clarification":
        rewrite_type = "clarification_required"
    else:
        rewrite_type = "none"

    return {
        "original_query": original_query,
        "resolved_query": resolved_query or original_query,
        "rewritten": rewritten,
        "rewrite_type": rewrite_type,
        "context_source": source,
        "context_status": status,
        "context_resolution_confidence": round(
            float(context_resolution.get("confidence") or 0.0), 3
        ),
        "reason": context_resolution.get("reason", ""),
        "context_entities": context_resolution.get("context_entities") or [],
        "context_projects": context_resolution.get("context_projects") or [],
        "active_doc_ids": context_resolution.get("active_doc_ids") or [],
        "readable_summary": (
            f"{rewrite_type}: {original_query} -> {resolved_query}"
            if rewritten
            else f"{rewrite_type}: query used without text rewrite"
        ),
    }


def build_planner_trace(
    analysis: dict[str, Any],
    plan: dict[str, Any],
    metadata_resolution: dict[str, Any],
    stage_sequence: list[str],
    stage_attempts: list[dict[str, Any]],
    *,
    stage_latencies_ms: dict[str, float] | None = None,
) -> dict[str, Any]:
    attempts = [
        {
            "stage": attempt.get("stage"),
            "top_k": attempt.get("top_k"),
            "verified": bool(attempt.get("verified")),
            "verification_reasons": attempt.get("verification_reasons") or [],
            "metadata_doc_ids": (attempt.get("metadata_filters") or {}).get("doc_ids") or [],
        }
        for attempt in stage_attempts
    ]
    selected_doc_ids = metadata_resolution.get("selected_doc_ids") or []
    query_type = str(analysis.get("query_type") or "")
    filter_stage = str(plan.get("filter_stage") or "")
    top_k = plan.get("top_k")
    latencies = {
        key: round(float((stage_latencies_ms or {}).get(key, 0.0)), 2)
        for key in (
            "query_analysis_ms",
            "context_resolution_ms",
            "answer_generation_ms",
        )
    }
    return {
        "query_type": query_type,
        "pipeline": plan.get("pipeline"),
        "prompt_profile": plan.get("prompt_profile"),
        "strategy": plan.get("strategy"),
        "retrieval_mode": plan.get("retrieval_mode"),
        "metadata_first": bool(plan.get("metadata_first")),
        "rerank": bool(plan.get("rerank")),
        "verifier_retry": bool(plan.get("verifier_retry")),
        "stage_sequence": stage_sequence,
        "selected_stage": filter_stage,
        "selected_top_k": top_k,
        "retrieval_budget": plan.get("retrieval_budget") or {},
        "metadata_candidate_count": metadata_resolution.get("candidate_count"),
        "metadata_selected_doc_ids": selected_doc_ids,
        "metadata_ambiguous": bool(analysis.get("metadata_ambiguous")),
        "comparison_coverage": plan.get("comparison_coverage"),
        "stage_latencies_ms": latencies,
        "attempts": attempts,
        "readable_summary": (
            f"{query_type} planned with {plan.get('pipeline')} "
            f"stage={filter_stage or 'none'} top_k={top_k} "
            f"metadata_docs={selected_doc_ids or 'none'}"
        ),
    }


def build_result_trace(
    original_query: str,
    resolved_query: str,
    analysis: dict[str, Any],
    plan: dict[str, Any],
    metadata_resolution: dict[str, Any],
    context_resolution: dict[str, Any],
    stage_sequence: list[str],
    stage_attempts: list[dict[str, Any]],
    answer: dict[str, Any],
    *,
    stage_latencies_ms: dict[str, float] | None = None,
    synthesis_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the per-prediction trace dict.

    The ``synthesis_meta`` kwarg (issue #967, trace schema v2) is the meta
    dict returned by ``rag_synthesis.synthesize_summary``. When the
    ``BIDMATE_TRACE_FULL=1`` env was set during the synthesis call,
    ``synthesis_meta["user_prompt_text"]`` and ``["completion_text"]`` are
    present and surface here as ``synthesis_llm_call``. Default (env=off)
    keeps ``synthesis_llm_call=None`` so consumers can detect the trace
    flavour without inspecting env state.
    """
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "query_rewrite": build_query_rewrite_trace(
            original_query,
            resolved_query,
            context_resolution,
        ),
        "planner": build_planner_trace(
            analysis,
            plan,
            metadata_resolution,
            stage_sequence,
            stage_attempts,
            stage_latencies_ms=stage_latencies_ms,
        ),
        "answer_schema": {
            "schema_version": answer.get("schema_version"),
            "status": answer.get("status"),
            "status_reason": answer.get("status_reason") or {},
            "query_type": answer.get("query_type"),
            "claim_count": len(answer.get("claims") or []),
        },
        "synthesis_llm_call": _synthesis_llm_call_payload(synthesis_meta),
    }


def _synthesis_llm_call_payload(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the trace v2 synthesis_llm_call payload, or None when full I/O
    is not present in ``meta`` (env=off or synthesis fell back).

    Schema (when populated):
        {
          "backend": str,
          "model": str | None,
          "tokens_in": int | None,
          "tokens_out": int | None,
          "user_prompt_text": str,
          "completion_text": str,
        }
    """
    if not isinstance(meta, dict):
        return None
    if "user_prompt_text" not in meta or "completion_text" not in meta:
        return None
    return {
        "backend": meta.get("backend"),
        "model": meta.get("model"),
        "tokens_in": meta.get("tokens_in"),
        "tokens_out": meta.get("tokens_out"),
        "user_prompt_text": meta.get("user_prompt_text"),
        "completion_text": meta.get("completion_text"),
    }


def redact_trace(
    trace: dict[str, Any],
    *,
    include_doc_ids: bool = True,
    include_entities: bool = True,
) -> dict[str, Any]:
    """Return a deep copy of `trace` with sensitive list fields masked.

    `include_doc_ids=False` masks active doc ids in query_rewrite, planner
    metadata selections, and per-attempt metadata filters. `include_entities=False`
    masks context entity / project lists. Counts are preserved so reviewers can
    still see structural shape.
    """
    if not isinstance(trace, dict):
        return trace
    redacted = copy.deepcopy(trace)

    def _mask(values: Any) -> list[str]:
        items = values if isinstance(values, list) else []
        return [REDACTED_LIST_PLACEHOLDER] * len(items)

    rewrite = redacted.get("query_rewrite")
    if isinstance(rewrite, dict):
        if not include_entities:
            rewrite["context_entities"] = _mask(rewrite.get("context_entities"))
            rewrite["context_projects"] = _mask(rewrite.get("context_projects"))
        if not include_doc_ids:
            rewrite["active_doc_ids"] = _mask(rewrite.get("active_doc_ids"))

    planner = redacted.get("planner")
    if isinstance(planner, dict) and not include_doc_ids:
        masked_selected = _mask(planner.get("metadata_selected_doc_ids"))
        planner["metadata_selected_doc_ids"] = masked_selected
        attempts = planner.get("attempts")
        if isinstance(attempts, list):
            for attempt in attempts:
                if isinstance(attempt, dict):
                    attempt["metadata_doc_ids"] = _mask(attempt.get("metadata_doc_ids"))
        # readable_summary embeds the selected doc IDs verbatim; rebuild it
        # so masking is consistent with the structured fields.
        planner["readable_summary"] = (
            f"{planner.get('query_type', '')} planned with {planner.get('pipeline')} "
            f"stage={planner.get('selected_stage') or 'none'} "
            f"top_k={planner.get('selected_top_k')} "
            f"metadata_docs={masked_selected or 'none'}"
        )

    return redacted


def strip_internal_scores(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped = []
    for item in evidence:
        public_item = {
            "doc_id": item["doc_id"],
            "chunk_id": item["chunk_id"],
            "title": item["title"],
            "text": item["text"],
            "score": item["score"],
            "agency": item.get("agency", ""),
            "metadata": item.get("metadata", {}),
            "section": item.get("section", ""),
            "section_id": item.get("section_id"),
            "parent_section_id": item.get("parent_section_id"),
            "section_path": item.get("section_path") or [],
            "chunk_seq_in_section": item.get("chunk_seq_in_section"),
            "total_chunks_in_section": item.get("total_chunks_in_section"),
            "chunking_strategy": item.get("chunking_strategy", ""),
            "retrieval_mode": item.get("retrieval_mode", "flat"),
            "child_chunk_ids": item.get("child_chunk_ids", []),
        }
        regions = normalize_regions(item.get("regions"))
        page_span = normalize_page_span(item.get("page_span"), regions)
        if regions:
            public_item["regions"] = regions
        if page_span:
            public_item["page_span"] = page_span
        stripped.append(public_item)
    return stripped


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def rate(scores: list[float]) -> float | None:
    if not scores:
        return None
    return sum(scores) / len(scores)
