"""Clarification path: UX abstention payloads for unresolved context.

Extracted from ``rag_core.py`` (PR-J5, issue #563) as the fourth and
final slice of the rag_core decomposition. Owns the four functions that
build abstention result payloads when the orchestration loop exits early
because the query cannot be resolved to a specific document or entity:

- :func:`clarification_answer` — builds the Korean clarification text
  for a context-resolution failure (no active state, ambiguous state,
  or unresolvable implicit reference).
- :func:`make_context_clarification_result` — builds the full result
  dict (``mode``, ``answer``, ``diagnostics``, ``trace``) returned when
  an implicit-reference query cannot be resolved before retrieval.
- :func:`metadata_clarification_answer` — builds the clarification text
  when ambiguous metadata matches force abstention (issue #72); lists
  candidates as ``agency · project (doc_id)``.
- :func:`make_metadata_clarification_result` — builds the full result
  dict returned when metadata ambiguity prevents selecting a single
  target document.

This module is a leaf in the dependency graph: it imports from
``rag_text_processing`` (``ordered_unique`` / ``QUERY_TYPE_TOP_K_DEFAULTS``),
``rag_pipeline_presets`` (``RRF_K``), ``rag_answer_schema``
(``ANSWER_SCHEMA_VERSION`` / ``ANSWER_STATUS_INSUFFICIENT``), ``rag_answer``
(``answer_status_reason`` / ``render_answer_text``), ``rag_verifier``
(``specific_topics`` / ``verification_topics``), ``rag_query``
(``metadata_resolution_diagnostics``), ``rag_tracing``
(``build_result_trace``), and stdlib. No ``rag_core`` imports.

``rag_core`` re-exports all four public names so existing orchestration
callers remain unchanged.

JSON-identity guarantee: every function moves byte-for-byte from
``rag_core``. Regression gates remain green:
``tests/test_langgraph_orchestrator_regression.py``.
"""

from __future__ import annotations

import time
from typing import Any

from rag_answer import answer_status_reason, render_answer_text
from rag_answer_schema import (
    ANSWER_SCHEMA_VERSION,
    ANSWER_STATUS_INSUFFICIENT,
    ANSWER_STATUS_REASON_CONTEXT_CLARIFICATION,
    ANSWER_STATUS_REASON_METADATA_AMBIGUITY_CLARIFICATION,
)
from rag_pipeline_presets import RRF_K
from rag_query import metadata_resolution_diagnostics
from rag_text_processing import QUERY_TYPE_TOP_K_DEFAULTS, ordered_unique
from rag_tracing import build_result_trace
from rag_verifier import specific_topics, verification_topics


def clarification_answer(query: str, context_resolution: dict[str, Any]) -> str:
    reason = context_resolution.get("reason")
    if reason == "no_active_state":
        return (
            f"'{query}'는 이전 문맥의 기관이나 사업을 확인해야 답할 수 있습니다. "
            "기관명 또는 사업명을 포함해 다시 질문해 주세요."
        )
    if reason == "ambiguous_active_state":
        entities = ", ".join(
            ordered_unique(
                [
                    *(context_resolution.get("context_entities") or []),
                    *(context_resolution.get("context_projects") or []),
                ]
            )
        )
        return (
            f"'{query}'에서 가리키는 대상이 모호합니다. "
            f"현재 문맥 후보는 {entities}입니다. 기관명 또는 사업명을 하나로 지정해 주세요."
        )
    return (
        f"'{query}'의 생략된 참조를 충분히 확정하지 못했습니다. "
        "기관명 또는 사업명을 포함해 다시 질문해 주세요."
    )


def make_context_clarification_result(
    index: dict[str, Any],
    query: str,
    analysis: dict[str, Any],
    conversation_state: dict[str, Any],
    context_resolution: dict[str, Any],
    started: float,
    metadata_first: bool,
    rerank: bool,
    verifier_retry: bool,
    retrieval_mode: str,
    retrieval_backend: str,
    pipeline: str,
    prompt_profile: str,
    *,
    stage_timings: dict[str, float] | None = None,
    cold_start: bool = False,
    rrf_k: int = RRF_K,
    bm25_stopword_profile: str = "shared",
) -> dict[str, Any]:
    reason = str(context_resolution.get("reason") or "context_resolution_failed")
    analysis = dict(analysis)
    analysis["query_type"] = "follow_up"
    analysis["context_resolution"] = context_resolution
    metadata_resolution = metadata_resolution_diagnostics(
        query,
        analysis,
        selected_stage="",
        decision="clarify",
        reason=reason,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    insufficiency = {
        "message": f"'{query}'의 생략된 참조를 충분히 확정하지 못했습니다.",
        "reasons": [reason],
        "missing_targets": context_resolution.get("context_entities") or [],
        "missing_topics": specific_topics(analysis),
        "checked_entities": context_resolution.get("context_entities") or [],
        "checked_doc_ids": context_resolution.get("active_doc_ids") or [],
    }
    answer = {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "status": ANSWER_STATUS_INSUFFICIENT,
        "status_reason": answer_status_reason(
            ANSWER_STATUS_INSUFFICIENT,
            False,
            [reason],
            code=ANSWER_STATUS_REASON_CONTEXT_CLARIFICATION,
        ),
        "query_type": "abstention",
        "summary": clarification_answer(query, context_resolution),
        "claims": [],
        "insufficiency": insufficiency,
    }
    answer_text = render_answer_text(answer)
    plan = {
        "strategy": "conversation-state clarification",
        "pipeline": pipeline,
        "prompt_profile": prompt_profile,
        "metadata_first": metadata_first,
        "rerank": rerank,
        "verifier_retry": verifier_retry,
        "retrieval_mode": retrieval_mode,
        "retrieval_backend": retrieval_backend,
        "rrf_k": int(rrf_k),
        "bm25_stopword_profile": bm25_stopword_profile,
        "metadata_filters": {},
        "top_k": None,
        "retrieval_budget": {
            "selected_top_k": None,
            "query_type": "follow_up",
            "reason": "clarification_before_retrieval",
            "defaults": dict(QUERY_TYPE_TOP_K_DEFAULTS),
        },
        "relaxed": False,
        "retry_policy": "clarify before retrieval when entity resolution is weak",
    }
    trace = build_result_trace(
        query,
        context_resolution.get("resolved_query") or query,
        analysis,
        plan,
        metadata_resolution,
        context_resolution,
        [],
        [],
        answer,
        stage_latencies_ms=stage_timings,
    )
    return {
        "mode": "rag",
        "query": query,
        "resolved_query": context_resolution.get("resolved_query") or query,
        "analysis": analysis,
        "plan": plan,
        "answer": answer,
        "answer_text": answer_text,
        "evidence": [],
        "trace": trace,
        "conversation_state": conversation_state,
        "diagnostics": {
            "latency_ms": round(latency_ms, 2),
            "retry_count": 0,
            "abstained": True,
            "answer_status": answer["status"],
            "answer_query_type": answer["query_type"],
            "claim_count": 0,
            "citation_count": 0,
            "verification_reasons": [reason],
            "filter_stage_attempts": [],
            "final_relaxation_reason": [],
            "context_resolution": context_resolution,
            "metadata_resolution": metadata_resolution,
            "selected_top_k": None,
            "embedding_backend": index.get("embedding", {}).get("backend"),
            "embedding_model": index.get("embedding", {}).get("model"),
            "metadata_first": metadata_first,
            "rerank": rerank,
            "verifier_retry": verifier_retry,
            "retrieval_mode": retrieval_mode,
            "retrieval_backend": retrieval_backend,
            "rrf_k": int(rrf_k),
            "bm25_stopword_profile": bm25_stopword_profile,
            "pipeline": pipeline,
            "prompt_profile": prompt_profile,
            "cold_start": cold_start,
            "stage_latency": {
                "query_analysis_ms": round(float((stage_timings or {}).get("query_analysis_ms", 0.0)), 2),
                "context_resolution_ms": round(float((stage_timings or {}).get("context_resolution_ms", 0.0)), 2),
                "answer_generation_ms": round(float((stage_timings or {}).get("answer_generation_ms", 0.0)), 2),
            },
        },
    }


def metadata_clarification_answer(query: str, analysis: dict[str, Any]) -> str:
    """Clarification text shown when ambiguous metadata matches force
    abstention (issue #72).

    Lists each candidate as `agency · project (doc_id)` so the user can
    pick a more specific phrasing without having to look up doc_ids.
    Falls back to bare doc_ids if metadata_matches don't carry agency /
    project (defensive — should not happen on well-formed indexes).
    """
    ambiguity = analysis.get("metadata_ambiguity") or {}
    candidate_doc_ids = ambiguity.get("candidate_doc_ids") or analysis.get("matched_doc_ids") or []
    metadata_matches = analysis.get("metadata_matches") or []
    agency_project_by_doc: dict[str, str] = {}
    for match in metadata_matches:
        doc_id = match.get("doc_id")
        if doc_id and doc_id not in agency_project_by_doc:
            agency = (match.get("agency") or "").strip()
            project = (match.get("project") or "").strip()
            if agency and project:
                agency_project_by_doc[doc_id] = f"{agency} · {project}"
            elif agency:
                agency_project_by_doc[doc_id] = agency
            elif project:
                agency_project_by_doc[doc_id] = project
    candidates_rendered = []
    for doc_id in candidate_doc_ids:
        label = agency_project_by_doc.get(doc_id)
        if label:
            candidates_rendered.append(f"{label} ({doc_id})")
        else:
            candidates_rendered.append(doc_id)
    if not candidates_rendered:
        suffix = ""
    else:
        joined = ", ".join(candidates_rendered)
        suffix = f" 현재 후보는 {joined}입니다."
    return (
        f"'{query}'에서 가리키는 기관 또는 사업 후보가 여러 개라서 하나로 확정할 수 없습니다."
        f"{suffix} 기관명 또는 사업명을 더 구체적으로 지정해 주세요."
    )


def make_metadata_clarification_result(
    index: dict[str, Any],
    query: str,
    retrieval_query: str,
    analysis: dict[str, Any],
    conversation_state: dict[str, Any],
    context_resolution: dict[str, Any],
    started: float,
    metadata_first: bool,
    rerank: bool,
    verifier_retry: bool,
    retrieval_mode: str,
    retrieval_backend: str,
    pipeline: str,
    prompt_profile: str,
    *,
    stage_timings: dict[str, float] | None = None,
    cold_start: bool = False,
    rrf_k: int = RRF_K,
    bm25_stopword_profile: str = "shared",
) -> dict[str, Any]:
    reason = "metadata_ambiguous"
    analysis = dict(analysis)
    analysis["context_resolution"] = context_resolution
    metadata_resolution = metadata_resolution_diagnostics(
        retrieval_query,
        analysis,
        selected_stage="reduced",
        decision="clarify",
        reason=reason,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    checked_entities = ordered_unique(
        [
            *(analysis.get("entities") or []),
            *(analysis.get("matched_projects") or []),
        ]
    )
    insufficiency = {
        "message": f"'{query}'의 기관 또는 사업 후보를 충분히 확정하지 못했습니다.",
        "reasons": [reason],
        "missing_targets": checked_entities,
        "missing_topics": specific_topics(analysis),
        "checked_entities": checked_entities,
        "checked_doc_ids": analysis.get("matched_doc_ids") or [],
    }
    answer = {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "status": ANSWER_STATUS_INSUFFICIENT,
        "status_reason": answer_status_reason(
            ANSWER_STATUS_INSUFFICIENT,
            False,
            [reason],
            code=ANSWER_STATUS_REASON_METADATA_AMBIGUITY_CLARIFICATION,
        ),
        "query_type": "abstention",
        "summary": metadata_clarification_answer(query, analysis),
        "claims": [],
        "insufficiency": insufficiency,
    }
    answer_text = render_answer_text(answer)
    plan = {
        "strategy": "metadata ambiguity clarification",
        "pipeline": pipeline,
        "prompt_profile": prompt_profile,
        "metadata_first": metadata_first,
        "rerank": rerank,
        "verifier_retry": verifier_retry,
        "retrieval_mode": retrieval_mode,
        "retrieval_backend": retrieval_backend,
        "rrf_k": int(rrf_k),
        "bm25_stopword_profile": bm25_stopword_profile,
        "metadata_filters": {},
        "top_k": None,
        "retrieval_budget": {
            "selected_top_k": None,
            "query_type": analysis.get("query_type"),
            "reason": "clarification_before_retrieval",
            "defaults": dict(QUERY_TYPE_TOP_K_DEFAULTS),
        },
        "relaxed": False,
        "retry_policy": "clarify before retrieval when metadata resolution is ambiguous",
    }
    trace = build_result_trace(
        query,
        retrieval_query,
        analysis,
        plan,
        metadata_resolution,
        context_resolution,
        [],
        [],
        answer,
        stage_latencies_ms=stage_timings,
    )
    return {
        "mode": "rag",
        "query": query,
        "resolved_query": retrieval_query,
        "analysis": analysis,
        "plan": plan,
        "answer": answer,
        "answer_text": answer_text,
        "evidence": [],
        "trace": trace,
        "conversation_state": conversation_state,
        "diagnostics": {
            "latency_ms": round(latency_ms, 2),
            "retry_count": 0,
            "abstained": True,
            "answer_status": answer["status"],
            "answer_query_type": answer["query_type"],
            "claim_count": 0,
            "citation_count": 0,
            "verification_reasons": [reason],
            "verification_topics": verification_topics(analysis),
            "filter_stage_attempts": [],
            "final_relaxation_reason": [],
            "context_resolution": context_resolution,
            "metadata_resolution": metadata_resolution,
            "selected_top_k": None,
            "embedding_backend": index.get("embedding", {}).get("backend"),
            "embedding_model": index.get("embedding", {}).get("model"),
            "metadata_first": metadata_first,
            "rerank": rerank,
            "verifier_retry": verifier_retry,
            "retrieval_mode": retrieval_mode,
            "retrieval_backend": retrieval_backend,
            "rrf_k": int(rrf_k),
            "bm25_stopword_profile": bm25_stopword_profile,
            "pipeline": pipeline,
            "prompt_profile": prompt_profile,
            "cold_start": cold_start,
            "stage_latency": {
                "query_analysis_ms": round(float((stage_timings or {}).get("query_analysis_ms", 0.0)), 2),
                "context_resolution_ms": round(float((stage_timings or {}).get("context_resolution_ms", 0.0)), 2),
                "answer_generation_ms": round(float((stage_timings or {}).get("answer_generation_ms", 0.0)), 2),
            },
        },
    }
