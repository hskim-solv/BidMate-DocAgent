#!/usr/bin/env python3
"""Shared local RAG primitives for the public BidMate sample.

The implementation keeps the public demo deterministic: retrieval is local,
generation is extractive, and external LLM/API calls are not required.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable
import unicodedata

import numpy as np

try:
    from rank_bm25 import BM25Okapi as _BM25Okapi
except ImportError:  # pragma: no cover — defensive; declared in requirements.txt
    _BM25Okapi = None  # type: ignore[assignment]

from bidmate_logging import get_logger, log_query_event
from rag_observability import resolve_trace_backend
from rag_query_expansion import default_expander
from rag_synthesis import synthesize_answer

_LOGGER = get_logger("rag_core")
from rag_vector_store import (
    InMemoryVectorStore,
    VectorStore,
    load_vector_store,
    vector_store_from_matrix,
)
from text_normalize import expand_forms, normalize_text

# Korean lexicon constants live in korean_lexicon.py (data/lexicon/ko_default.yaml).
# Re-exported here so existing call sites — including
# `tests/test_hybrid_retrieval_regression.py` which imports
# BM25_EXTRA_PARTICLE_SUFFIXES / BM25_EXTRA_STOPWORDS from rag_core —
# keep working unchanged. See issue #344.
from korean_lexicon import (
    BM25_EXTRA_PARTICLE_SUFFIXES,
    BM25_EXTRA_STOPWORDS,
    IMPLICIT_REFERENCE_PATTERNS,
    KOREAN_PARTICLE_SUFFIXES,
    METADATA_CLAIM_LABELS,
    METADATA_CLAIM_TOPIC_LABELS,
    METADATA_EVIDENCE_LABELS,
    TOPIC_KEYWORDS,
    VERIFICATION_INTENT_TOKENS,
)

# Pipeline preset registry (PIPELINE_PRESETS, PIPELINE_ALIASES, helpers,
# RRF_K, VALID_RRF_K_RANGE, etc.) lives in rag_pipeline_presets.py as
# of issue #364 — stage 1 of the rag_core.py decomposition epic. The
# symbols below are re-exported so the FastAPI server, CLI app,
# benchmark / build_index / eval scripts, Streamlit demo and the test
# suite keep importing them from ``rag_core`` unchanged.
from rag_pipeline_presets import (
    DEFAULT_CLI_PIPELINE_NAME,
    DEFAULT_COMPARISON_BALANCE,
    DEFAULT_RAG_PIPELINE_NAME,
    PIPELINE_ALIASES,
    PIPELINE_CONFIG_KEYS,
    PIPELINE_PRESETS,
    RRF_K,
    VALID_BM25_STOPWORD_PROFILES,
    VALID_QUERY_EXPANSIONS,
    VALID_RETRIEVAL_BACKENDS,
    VALID_RETRIEVAL_MODES,
    VALID_RRF_K_RANGE,
    canonical_pipeline_name,
    is_pipeline_name,
    pipeline_cli_choices,
    resolve_pipeline_config,
)
# PR-H1a (issue #459) + PR-H1b (issue #461): retrieval pipeline
# extracted to rag_retrieval (candidate generation + similarity
# primitives + BM25 surface + fusion + comparison balance + hierarchical
# reassembly). Public functions re-exported so any caller that
# imported them from rag_core keeps working without change.
from rag_retrieval import (
    _apply_bm25_extra_filter,  # noqa: F401 — friend-of-module test export (tests/test_hybrid_retrieval_regression.py)
    apply_comparison_balance,
    apply_fusion_and_reranking,
    bm25_scores_for_index,
    dense_similarity,
    embed_query_for_index,
    get_or_build_bm25,
    lexical_similarity,
    metadata_similarity,
    reassemble_parent_sections,
    retrieve_candidates,
)
# PR-J1 (issue #465): verifier path extracted to rag_verifier. Re-exports
# kept stable for external callers — EVIDENCE_BOUNDARY is consumed by
# tests/test_synthetic_judge.py, tests/test_prompt_injection_regression.py,
# scripts/llm_judge.py, eval/synthetic_judge.py; neutralize_instruction_patterns
# by scripts/llm_judge.py and eval/synthetic_judge.py; verify_evidence and
# specific_topics by orchestration / answer-generation paths inside this module.
from rag_verifier import (
    EVIDENCE_BOUNDARY,
    PARTIAL_TOPIC_GROUNDING_MIN_FRACTION,
    PARTIAL_TOPIC_GROUNDING_MIN_MATCHED,
    PARTIAL_TOPIC_GROUNDING_REASON,
    evidence_has_topic,
    evidence_text_for_verification,
    metadata_terms_for_verification,
    neutralize_instruction_patterns,
    specific_topics,
    verification_topics,
    verify_evidence,
)
# PR-J2 (issue #468): answer generation extracted to rag_answer. The
# 20 functions own the ADR 0003 answer-dict construction surface
# (`schema_version: 2` literal, citation contract). Re-exported so
# orchestration (`_phase_build_answer`) and any direct importer keep
# working unchanged.
from rag_answer import (
    answer_query_type,
    answer_status,
    answer_status_reason,
    answer_summary,
    answer_verification_reasons,
    best_sentence,
    build_claims,
    build_comparison_claims,
    build_extract_claims,
    build_insufficiency,
    claim_target,
    format_metadata_claim_value,
    generate_answer,
    make_citation,
    make_claim,
    metadata_claim_sentences,
    metadata_field_requested,
    render_answer_text,
    select_supporting_evidence,
    sentence_has_verification_topic,
)
# PR-J3 (issue #478): query analysis + planning extracted to rag_query.
# Re-exports kept so orchestration (`_phase_analyze`), rag_retrieval
# (which late-imports `comparison_targets_for_analysis`), rag_answer
# (which uses `verification_topics` via rag_verifier), and external
# callers all keep working unchanged.
from rag_query import (
    active_state_size,
    active_state_terms,
    analyze_query,
    comparison_targets_for_analysis,
    extract_requested_agencies,
    has_comparison_request,
    has_implicit_reference,
    inject_entities_into_query,
    is_metadata_ambiguous,
    make_context_resolution,
    make_plan,
    metadata_resolution_diagnostics,
    query_type_default_top_k,
    resolve_conversation_context,
    summarize_metadata_match,
)

# Conversation state schema + helpers live in rag_conversation_state.py as
# of issue #415 (PR-E stage 3 of the rag_core.py decomposition epic). The
# symbols below are direct-imported (no re-export wrapper) — repo-wide
# grep at PR filing confirmed zero external consumers.
# Embedding primitives extracted to rag_embedding (ADR 0045, issue #843).
# Re-exported here so existing ``from rag_core import embed_texts`` /
# ``DEFAULT_EMBEDDING_MODEL`` call sites keep working unchanged. The
# bodies live in rag_embedding now; this is a structural relocation
# only and is byte-identical for the naive_baseline preset (ADR 0001).
from rag_embedding import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_HASH_DIM,
    MODEL_CACHE,
    EmbeddingResult,
    _embed_with_openai,
    embed_texts,
    expand_features,
    hashing_embeddings,
    huggingface_offline,
    sentence_transformer_cache_available,
)
# Re-declare the MODEL_CACHE type annotation on the rag_core module so
# tests that inspect ``rag_core.__annotations__["MODEL_CACHE"]`` (e.g.
# tests/test_finetuned_ablation_baseline_invariant.py for the #434
# 3-tuple key shape) keep seeing the contract after the move. This is
# a pure annotation, not a rebinding — the imported MODEL_CACHE object
# above is the canonical one in rag_embedding.
MODEL_CACHE: dict[tuple[str, bool, str | None], Any]
# Text-processing primitives extracted to rag_text_processing (issue #545).
# Re-exported here so existing ``from rag_core import tokenize`` call sites
# keep working unchanged.
from rag_text_processing import (
    ENTITY_RE,
    QUERY_TYPE_TOP_K_DEFAULTS,
    TOKEN_RE,
    SENTENCE_RE,
    coerce_alias_values,
    coerce_string_list,
    compact_metadata_text,
    normalize_entity,
    normalize_metadata_token,
    normalize_section_path,
    ordered_unique,
    sentence_split,
    split_long_text_unit,
    tokenize,
)
# Metadata processing extracted to rag_metadata_processing (issue #557).
# Re-exported here so existing ``from rag_core import normalize_regions``
# call sites keep working unchanged.
from rag_metadata_processing import (
    WEAK_SECTION_HEADINGS,
    STRICT_METADATA_CONFIDENCE,
    REDUCED_METADATA_CONFIDENCE,
    best_metadata_doc_scores,
    best_metadata_phrase_similarity,
    coerce_metadata_targets,
    dedupe_metadata_matches,
    document_has_section_structure,
    fixed_parent_section,
    make_metadata_match,
    make_metadata_target,
    match_metadata_target,
    match_metadata_targets,
    metadata_aliases,
    metadata_ambiguity_details,
    metadata_explicit_aliases,
    metadata_filters_from_matches,
    metadata_matches_for_stage,
    metadata_tokens,
    normalize_document_sections,
    normalize_page_span,
    normalize_regions,
    split_section_text,
)
# Tracing / telemetry extracted to rag_tracing (issue #560).
# Re-exported here so existing ``from rag_core import redact_trace`` call
# sites (tests/test_fuzzy_retrieval.py, eval/scorers/) keep working.
from rag_tracing import (
    REDACTED_LIST_PLACEHOLDER,
    TRACE_SCHEMA_VERSION,
    _StageTimer,
    _attach_trace_diagnostics,
    build_planner_trace,
    build_query_rewrite_trace,
    build_result_trace,
    percentile,
    rate,
    redact_trace,
    strip_internal_scores,
    summarize_stage_attempt,
)
# Clarification path extracted to rag_clarification (issue #563).
# Re-exported here so orchestration callers keep working unchanged.
from rag_clarification import (
    clarification_answer,
    make_context_clarification_result,
    make_metadata_clarification_result,
    metadata_clarification_answer,
)

from rag_conversation_state import (
    AMBIGUOUS_CONFIDENCE_DELTA,
    CONTEXT_RESOLUTION_THRESHOLD,
    CONVERSATION_STATE_SCHEMA_VERSION,
    MAX_CONVERSATION_TURNS,
    empty_conversation_state,
    normalize_conversation_state,
)

# ADR 0003 answer-contract schema constants live in rag_answer_schema.py
# as of issue #417 (PR-E stage 4a). Re-exported here so external
# consumers (tests/test_demo_helpers, tests/test_governance,
# tests/test_answer_contract_snapshot) keep their existing
# ``from rag_core import ANSWER_STATUS_SUPPORTED, ANSWER_SCHEMA_VERSION``
# imports unchanged.
from rag_answer_schema import (
    ANSWER_SCHEMA_VERSION,
    ANSWER_STATUS_INSUFFICIENT,
    ANSWER_STATUS_PARTIAL,
    # Issue #759 — RAG senior-review critique #2: status_reason.code
    # constants + closed set, re-exported here to keep the
    # ``from rag_core import ...`` import path consumers expect.
    ANSWER_STATUS_REASON_CONTEXT_CLARIFICATION,
    ANSWER_STATUS_REASON_INSUFFICIENT_EVIDENCE,
    ANSWER_STATUS_REASON_METADATA_AMBIGUITY_CLARIFICATION,
    ANSWER_STATUS_REASON_PARTIAL_COMPARISON,
    ANSWER_STATUS_REASON_PARTIAL_TOPIC_GROUNDING,
    ANSWER_STATUS_REASON_VERIFIED,
    ANSWER_STATUS_SUPPORTED,
    KNOWN_ANSWER_STATUS_REASON_CODES,
)

# Ingestion + chunking + index I/O extracted to rag_indexing (ADR 0045 G3, issue #858).
# Re-exported here so existing `from rag_core import build_index_payload` /
# `DEFAULT_CHUNK_MAX_CHARS` / `INDEX_FILENAME` call sites keep working
# unchanged. Bodies live in rag_indexing now; this is a structural
# relocation only and is byte-identical for the naive_baseline preset
# (ADR 0001).
from rag_indexing import (
    DEFAULT_CHUNK_MAX_CHARS,
    DEFAULT_CHUNK_OVERLAP_SENTENCES,
    INDEX_FILENAME,
    INDEX_SCHEMA_VERSION,
    VALID_CHUNKING_STRATEGIES,
    build_chunk_records,
    build_chunks,
    build_index_payload,
    build_index_payload_from_documents,
    known_entities,
    load_index,
    load_raw_documents,
    make_chunk,
    metadata_targets,
    normalize_json_document,
    normalize_text_document,
    resolve_chunking_strategy,
    validate_chunking_options,
    write_index,
)

# Hard cap on the per-query agent loop. ``metadata_stage_sequence`` today
# returns at most ["strict", "reduced", "relaxed"] (3 stages). This constant
# pins the contract — any future addition to the stage list that pushes
# past 3 must update this value and explain why in the PR description.
MAX_AGENT_ITERATIONS = 3

# M2 (#207): vectors live in a sidecar .npy so the JSON stays small and a
# future VectorStore abstraction (#176) can swap in alternate backends
# without touching the chunk-metadata payload.
EMBEDDINGS_FILENAME = "embeddings.npy"


@dataclass(frozen=True)
class QueryParams:
    """Bundle of pipeline configuration kwargs for ``run_rag_query`` (issue #260).

    Additive, non-breaking signature extension. Existing callers using
    individual kwargs (``top_k=...``, ``rerank=...``, etc.) keep working
    unchanged. New callers can pass a single ``params=QueryParams(...)``
    bundle instead.

    Per-call inputs (``context_entities``, ``conversation_state``) stay
    separate kwargs on ``run_rag_query`` — they vary per turn, not per
    pipeline configuration. The return contract (ADR 0003) is unchanged.
    """

    top_k: int | None = None
    metadata_first: bool | None = None
    rerank: bool | None = None
    verifier_retry: bool | None = None
    retrieval_mode: str | None = None
    retrieval_backend: str | None = None
    pipeline: str | None = None
    prompt_profile: str | None = None
    comparison_balance: dict[str, Any] | None = None
    rrf_k: int | None = None
    bm25_stopword_profile: str | None = None
    bm25_tokenizer: str | None = None


def retrieve(
    index: dict[str, Any],
    query: str,
    analysis: dict[str, Any],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    scored = retrieve_candidates(index, query, analysis, plan)
    return apply_fusion_and_reranking(scored, index, query, analysis, plan)






def metadata_stage_sequence(
    analysis: dict[str, Any],
    metadata_first: bool = True,
    verifier_retry: bool = True,
) -> list[str]:
    if not metadata_first:
        return ["relaxed"]

    filters_by_stage = analysis.get("metadata_filters_by_stage") or {}
    strict_filters = filters_by_stage.get("strict") or {}
    reduced_filters = filters_by_stage.get("reduced") or {}
    stages = []
    if strict_filters:
        stages.append("strict")
    if reduced_filters and reduced_filters != strict_filters:
        stages.append("reduced")
    if not stages:
        return ["relaxed", "relaxed"] if verifier_retry else ["relaxed"]
    if verifier_retry:
        stages.append("relaxed")
    return stages


_PROCESS_WARM = False


def update_conversation_state(
    conversation_state: dict[str, Any],
    original_query: str,
    resolved_query: str,
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
    context_resolution: dict[str, Any],
) -> dict[str, Any]:
    active_doc_ids = ordered_unique(
        [
            *coerce_string_list(analysis.get("matched_doc_ids")),
            *(item.get("doc_id", "") for item in evidence),
        ]
    )
    active_agencies = ordered_unique(
        [
            *coerce_string_list(analysis.get("entities")),
            *(item.get("agency", "") for item in evidence),
        ]
    )
    active_projects = ordered_unique(
        [
            *coerce_string_list(analysis.get("matched_projects")),
            *(item.get("project", "") for item in evidence),
        ]
    )
    active_topics = coerce_string_list(analysis.get("topics"))
    active_candidates = [
        {
            "doc_id": doc_id,
            "agency": next((item.get("agency", "") for item in evidence if item.get("doc_id") == doc_id), ""),
            "project": next((item.get("project", "") for item in evidence if item.get("doc_id") == doc_id), ""),
        }
        for doc_id in active_doc_ids
    ]

    if not (active_doc_ids or active_agencies or active_projects):
        return conversation_state

    metadata_confidence = float(analysis.get("metadata_confidence") or 0.0)
    resolution_confidence = float(context_resolution.get("confidence") or 0.0)
    confidence = max(metadata_confidence, resolution_confidence, 0.85)
    if analysis.get("metadata_ambiguous"):
        confidence = min(confidence, 0.65)

    turns = list(conversation_state.get("turns") or [])
    turns.append(
        {
            "turn": len(turns) + 1,
            "query": original_query,
            "resolved_query": resolved_query,
            "active_agencies": active_agencies,
            "active_projects": active_projects,
            "active_topics": active_topics,
            "active_doc_ids": active_doc_ids,
            "context_resolution": {
                "status": context_resolution.get("status"),
                "source": context_resolution.get("source"),
                "confidence": context_resolution.get("confidence"),
                "reason": context_resolution.get("reason", ""),
                "context_entities": context_resolution.get("context_entities", []),
                "context_projects": context_resolution.get("context_projects", []),
                "active_doc_ids": context_resolution.get("active_doc_ids", []),
            },
        }
    )

    return {
        "schema_version": CONVERSATION_STATE_SCHEMA_VERSION,
        "active_agencies": active_agencies,
        "active_projects": active_projects,
        "active_topics": active_topics,
        "active_doc_ids": active_doc_ids,
        "active_candidates": active_candidates,
        "confidence": round(float(confidence), 3),
        "ambiguous": bool(analysis.get("metadata_ambiguous")),
        "turns": turns[-MAX_CONVERSATION_TURNS:],
    }


@dataclass
class _RunContext:
    """Mutable per-query state threaded through the ``run_rag_query`` phase functions.

    ADR 0022 stage 2 decomposes ``run_rag_query`` into
    :func:`_phase_analyze` / :func:`_phase_retrieve_loop` /
    :func:`_phase_build_answer` so the LangGraph orchestrator in
    :mod:`rag_graph_agentic_full` can call the same phase code that the
    direct path runs. JSON-identity vs the direct path therefore holds
    by construction. Underscore-prefixed because
    :mod:`rag_graph_agentic_full` is the only intended consumer.
    """

    index: dict[str, Any]
    query: str
    context_entities: list[str] | None
    top_k: int | None
    requested_top_k: int | None
    metadata_first: bool
    rerank: bool
    rerank_cross_encoder: bool
    verifier_retry: bool
    retrieval_mode: str
    retrieval_backend: str
    pipeline_name: str
    prompt_profile: str
    rrf_k: int
    bm25_stopword_profile: str
    bm25_tokenizer: str
    resolved_comparison_balance: Any
    state: dict[str, Any]
    targets: list[dict[str, Any]]
    query_hash: str
    cold_start: bool
    started: float
    stage_timings: dict[str, float]
    trace_backend_obj: Any
    trace_backend_name: str
    trace_unavailable_reason: Any
    trace_error: Any
    trace_handle: Any
    retrieval_query: str = ""
    effective_context_entities: list[str] | None = None
    context_resolution: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    stage_sequence: list[Any] | None = None
    stage_attempts: list[dict[str, Any]] | None = None
    retry_count: int = 0
    plan: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] | None = None
    verified: bool = False
    verification_reasons: list[str] | None = None
    retrieved_chunk_ids: list[str] | None = None


def _build_run_context(
    index: dict[str, Any],
    query: str,
    *,
    top_k: int | None,
    context_entities: list[str] | None,
    metadata_first: bool | None,
    rerank: bool | None,
    rerank_cross_encoder: bool | None = None,
    verifier_retry: bool | None,
    retrieval_mode: str | None,
    retrieval_backend: str | None,
    pipeline: str | None,
    prompt_profile: str | None,
    conversation_state: dict[str, Any] | None,
    comparison_balance: dict[str, Any] | None,
    rrf_k: int | None,
    bm25_stopword_profile: str | None,
    bm25_tokenizer: str | None = None,
    params: QueryParams | None = None,
) -> _RunContext:
    """Normalize raw ``run_rag_query`` inputs into a :class:`_RunContext`.

    Handles ``params=`` bundle normalization, pipeline-preset resolution,
    the ``_PROCESS_WARM`` cold-start flag, query hashing, the
    ``query_start`` log event, and trace-backend startup. Splitting this
    out of ``run_rag_query`` lets the LangGraph orchestrator
    (ADR 0022 stage 2) build the context once and pass it through the
    three graph nodes.
    """
    if params is not None:
        legacy_pipeline_kwargs = {
            "top_k": top_k,
            "metadata_first": metadata_first,
            "rerank": rerank,
            "verifier_retry": verifier_retry,
            "retrieval_mode": retrieval_mode,
            "retrieval_backend": retrieval_backend,
            "pipeline": pipeline,
            "prompt_profile": prompt_profile,
            "comparison_balance": comparison_balance,
            "rrf_k": rrf_k,
            "bm25_stopword_profile": bm25_stopword_profile,
            "bm25_tokenizer": bm25_tokenizer,
        }
        conflicting = sorted(k for k, v in legacy_pipeline_kwargs.items() if v is not None)
        if conflicting:
            raise ValueError(
                "run_rag_query: cannot mix params= with explicit pipeline kwargs; "
                f"set them on the QueryParams instance instead. Conflicting kwargs: {conflicting}"
            )
        top_k = params.top_k
        metadata_first = params.metadata_first
        rerank = params.rerank
        verifier_retry = params.verifier_retry
        retrieval_mode = params.retrieval_mode
        retrieval_backend = params.retrieval_backend
        pipeline = params.pipeline
        prompt_profile = params.prompt_profile
        comparison_balance = params.comparison_balance
        rrf_k = params.rrf_k
        bm25_stopword_profile = params.bm25_stopword_profile
        bm25_tokenizer = params.bm25_tokenizer

    pipeline_source: dict[str, Any] = {"pipeline": pipeline or DEFAULT_RAG_PIPELINE_NAME}
    for key, value in (
        ("top_k", top_k),
        ("metadata_first", metadata_first),
        ("rerank", rerank),
        ("rerank_cross_encoder", rerank_cross_encoder),
        ("verifier_retry", verifier_retry),
        ("retrieval_mode", retrieval_mode),
        ("retrieval_backend", retrieval_backend),
        ("prompt_profile", prompt_profile),
        ("rrf_k", rrf_k),
        ("bm25_stopword_profile", bm25_stopword_profile),
        ("bm25_tokenizer", bm25_tokenizer),
    ):
        if value is not None:
            pipeline_source[key] = value
    if comparison_balance is not None:
        pipeline_source["comparison_balance"] = comparison_balance
    pipeline_config = resolve_pipeline_config(
        pipeline_source,
        default_pipeline=DEFAULT_RAG_PIPELINE_NAME,
    )
    resolved_top_k = pipeline_config["top_k"]
    requested_top_k = resolved_top_k
    metadata_first_val = bool(pipeline_config["metadata_first"])
    rerank_val = bool(pipeline_config["rerank"])
    rerank_cross_encoder_val = bool(pipeline_config.get("rerank_cross_encoder"))
    verifier_retry_val = bool(pipeline_config["verifier_retry"])
    retrieval_mode_val = str(pipeline_config["retrieval_mode"])
    retrieval_backend_val = str(pipeline_config["retrieval_backend"])
    pipeline_name = str(pipeline_config["pipeline"])
    prompt_profile_val = str(pipeline_config["prompt_profile"])
    rrf_k_val = int(pipeline_config["rrf_k"])
    bm25_stopword_profile_val = str(pipeline_config["bm25_stopword_profile"])
    bm25_tokenizer_val = str(pipeline_config["bm25_tokenizer"])
    resolved_comparison_balance = pipeline_config.get("comparison_balance")

    global _PROCESS_WARM
    cold_start = not _PROCESS_WARM
    if cold_start:
        _PROCESS_WARM = True

    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
    log_query_event(
        _LOGGER,
        "query_start",
        query_hash=query_hash,
        query_length=len(query),
        pipeline=pipeline_name,
        prompt_profile=prompt_profile_val,
        retrieval_backend=retrieval_backend_val,
        retrieval_mode=retrieval_mode_val,
        top_k=requested_top_k,
        cold_start=cold_start,
    )

    started = time.perf_counter()
    stage_timings: dict[str, float] = {}
    state = normalize_conversation_state(conversation_state)
    targets = metadata_targets(index)

    trace_backend_obj, trace_backend_name, trace_unavailable_reason = resolve_trace_backend()
    trace_error: str | None = None
    trace_handle: Any = None
    if trace_backend_name != "none":
        try:
            trace_handle = trace_backend_obj.start_trace(
                query,
                {
                    "pipeline": pipeline_name,
                    "prompt_profile": prompt_profile_val,
                    "embedding_backend": index.get("embedding", {}).get("backend"),
                    "retrieval_backend": retrieval_backend_val,
                    "retrieval_mode": retrieval_mode_val,
                    "metadata_first": metadata_first_val,
                    "rerank": rerank_val,
                    "verifier_retry": verifier_retry_val,
                    "cold_start": cold_start,
                },
            )
        except Exception as exc:
            trace_error = f"start_trace:{type(exc).__name__}:{str(exc)[:120]}"
            trace_handle = None
            # Issue #784 — RAG senior-review critique #4: trace_error
            # was previously only captured into the per-request
            # diagnostics dict, so an outage of the configured trace
            # backend (LangSmith down, mis-set token, schema drift)
            # produced no operator-visible signal. Emit a warning so
            # aggregate log inspection / alerting can pick it up
            # without scraping every diagnostics block.
            _LOGGER.warning(
                "trace_start_failed backend=%s error=%s",
                trace_backend_name,
                trace_error,
            )

    return _RunContext(
        index=index,
        query=query,
        context_entities=context_entities,
        top_k=resolved_top_k,
        requested_top_k=requested_top_k,
        metadata_first=metadata_first_val,
        rerank=rerank_val,
        rerank_cross_encoder=rerank_cross_encoder_val,
        verifier_retry=verifier_retry_val,
        retrieval_mode=retrieval_mode_val,
        retrieval_backend=retrieval_backend_val,
        pipeline_name=pipeline_name,
        prompt_profile=prompt_profile_val,
        rrf_k=rrf_k_val,
        bm25_stopword_profile=bm25_stopword_profile_val,
        bm25_tokenizer=bm25_tokenizer_val,
        resolved_comparison_balance=resolved_comparison_balance,
        state=state,
        targets=targets,
        query_hash=query_hash,
        cold_start=cold_start,
        started=started,
        stage_timings=stage_timings,
        trace_backend_obj=trace_backend_obj,
        trace_backend_name=trace_backend_name,
        trace_unavailable_reason=trace_unavailable_reason,
        trace_error=trace_error,
        trace_handle=trace_handle,
    )


def _phase_analyze(ctx: _RunContext) -> dict[str, Any] | None:
    """Run query analysis + context resolution + ambiguity check (ADR 0022 stage 2).

    Returns a final result dict if the query short-circuits with a
    context-clarification or metadata-ambiguity reply, otherwise ``None``
    after mutating ``ctx`` with the analysis outputs that
    :func:`_phase_retrieve_loop` and :func:`_phase_build_answer` consume.
    """
    with _StageTimer(ctx.stage_timings, "query_analysis_ms", trace=ctx.trace_handle, attrs={"iteration": 1}):
        initial_analysis = analyze_query(ctx.query, ctx.targets)
    with _StageTimer(ctx.stage_timings, "context_resolution_ms", trace=ctx.trace_handle):
        retrieval_query, effective_context_entities, context_resolution = resolve_conversation_context(
            ctx.query,
            initial_analysis,
            ctx.state,
            context_entities=ctx.context_entities,
        )
    if context_resolution["status"] == "needs_clarification":
        result = make_context_clarification_result(
            ctx.index,
            ctx.query,
            initial_analysis,
            ctx.state,
            context_resolution,
            ctx.started,
            ctx.metadata_first,
            ctx.rerank,
            ctx.verifier_retry,
            ctx.retrieval_mode,
            ctx.retrieval_backend,
            ctx.pipeline_name,
            ctx.prompt_profile,
            stage_timings=ctx.stage_timings,
            cold_start=ctx.cold_start,
            rrf_k=ctx.rrf_k,
            bm25_stopword_profile=ctx.bm25_stopword_profile,
        )
        _attach_trace_diagnostics(
            result,
            ctx.trace_handle,
            ctx.trace_backend_name,
            ctx.trace_unavailable_reason,
            ctx.trace_error,
        )
        return result

    with _StageTimer(ctx.stage_timings, "query_analysis_ms", trace=ctx.trace_handle, attrs={"iteration": 2}):
        analysis = analyze_query(
            retrieval_query,
            ctx.targets,
            context_entities=effective_context_entities,
        )
    if context_resolution["source"] in {"conversation_state", "context_entities"}:
        analysis["query_type"] = "follow_up"
        analysis["context_used"] = True
    analysis["context_resolution"] = context_resolution
    if ctx.trace_handle is not None:
        try:
            ctx.trace_handle.set_tag("query_type", str(analysis.get("query_type") or ""))
        except Exception as exc:
            # Issue #784 — RAG senior-review critique #4: tag drops
            # used to be a bare ``pass``. The ``trace_handle is not
            # None`` guard above means start_trace already succeeded,
            # so a set_tag failure here is rare in steady state and
            # worth logging each time (e.g. LangSmith schema drift,
            # tag-name length limits). The tag is still dropped so
            # the request keeps flowing.
            _LOGGER.warning(
                "trace_set_tag_failed tag=%s error=%s:%s",
                "query_type",
                type(exc).__name__,
                str(exc)[:120],
            )
    if analysis.get("metadata_ambiguous") and analysis.get("query_type") != "comparison":
        result = make_metadata_clarification_result(
            ctx.index,
            ctx.query,
            retrieval_query,
            analysis,
            ctx.state,
            context_resolution,
            ctx.started,
            ctx.metadata_first,
            ctx.rerank,
            ctx.verifier_retry,
            ctx.retrieval_mode,
            ctx.retrieval_backend,
            ctx.pipeline_name,
            ctx.prompt_profile,
            stage_timings=ctx.stage_timings,
            cold_start=ctx.cold_start,
            rrf_k=ctx.rrf_k,
            bm25_stopword_profile=ctx.bm25_stopword_profile,
        )
        _attach_trace_diagnostics(
            result,
            ctx.trace_handle,
            ctx.trace_backend_name,
            ctx.trace_unavailable_reason,
            ctx.trace_error,
        )
        return result

    stage_sequence = metadata_stage_sequence(
        analysis,
        metadata_first=ctx.metadata_first,
        verifier_retry=ctx.verifier_retry,
    )
    if len(stage_sequence) > MAX_AGENT_ITERATIONS:
        raise RuntimeError(
            f"stage_sequence length {len(stage_sequence)} exceeds "
            f"MAX_AGENT_ITERATIONS={MAX_AGENT_ITERATIONS}; "
            "update MAX_AGENT_ITERATIONS and revisit the loop contract."
        )

    ctx.retrieval_query = retrieval_query
    ctx.effective_context_entities = effective_context_entities
    ctx.context_resolution = context_resolution
    ctx.analysis = analysis
    ctx.stage_sequence = stage_sequence
    return None


def _phase_retrieve_loop(ctx: _RunContext) -> None:
    """Run the metadata-stage retry loop (ADR 0022 stage 2).

    Mutates ``ctx`` with ``stage_attempts``, ``retry_count``, ``plan``,
    ``evidence``, ``verified``, ``verification_reasons``,
    ``retrieved_chunk_ids``.
    """
    stage_attempts: list[dict[str, Any]] = []
    retry_count = 0
    plan: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    verified = False
    verification_reasons: list[str] = []

    stage_sequence = ctx.stage_sequence or []
    analysis = ctx.analysis or {}
    for attempt_index, stage in enumerate(stage_sequence):
        attempt_top_k = ctx.top_k
        top_k_reason = None
        if ctx.requested_top_k is not None:
            top_k_reason = "pipeline_or_explicit_override"
        if attempt_index > 0:
            attempt_top_k = max(ctx.top_k or 0, 8)
            top_k_reason = "retry_expansion"
        attempt_timings: dict[str, float] = {}
        with _StageTimer(
            attempt_timings,
            "retrieve_ms",
            trace=ctx.trace_handle,
            attrs={"attempt_index": attempt_index, "stage": str(stage or ""), "top_k": attempt_top_k or 0},
        ):
            plan = make_plan(
                analysis,
                top_k=attempt_top_k,
                top_k_reason=top_k_reason,
                stage=stage,
                metadata_first=ctx.metadata_first,
                rerank=ctx.rerank,
                rerank_cross_encoder=ctx.rerank_cross_encoder,
                verifier_retry=ctx.verifier_retry,
                retrieval_mode=ctx.retrieval_mode,
                retrieval_backend=ctx.retrieval_backend,
                pipeline=ctx.pipeline_name,
                prompt_profile=ctx.prompt_profile,
                comparison_balance=ctx.resolved_comparison_balance,
                rrf_k=ctx.rrf_k,
                bm25_stopword_profile=ctx.bm25_stopword_profile,
                bm25_tokenizer=ctx.bm25_tokenizer,
            )
            evidence = retrieve(ctx.index, ctx.retrieval_query, analysis, plan)
        with _StageTimer(
            attempt_timings,
            "verify_ms",
            trace=ctx.trace_handle,
            attrs={"attempt_index": attempt_index, "verifier_retry": ctx.verifier_retry},
        ):
            if ctx.verifier_retry:
                is_last_attempt = attempt_index == len(stage_sequence) - 1
                verified, verification_reasons = verify_evidence(
                    analysis,
                    evidence,
                    allow_partial_topic=is_last_attempt,
                )
            else:
                verified = bool(evidence)
                verification_reasons = [] if verified else ["no_evidence"]
        stage_attempts.append(
            summarize_stage_attempt(plan, verified, verification_reasons, timings=attempt_timings)
        )
        if verified:
            break
        if attempt_index < len(stage_sequence) - 1:
            retry_count += 1

    retrieved_chunk_ids: list[str] = [
        str(item.get("chunk_id") or "") for item in evidence if item.get("chunk_id")
    ]

    if verified or analysis.get("query_type") == "comparison":
        evidence = select_supporting_evidence(analysis, evidence)
    else:
        evidence = []

    ctx.stage_attempts = stage_attempts
    ctx.retry_count = retry_count
    ctx.plan = plan
    ctx.evidence = evidence
    ctx.verified = verified
    ctx.verification_reasons = verification_reasons
    ctx.retrieved_chunk_ids = retrieved_chunk_ids


def _phase_build_answer(ctx: _RunContext) -> dict[str, Any]:
    """Build the final answer and result dict (ADR 0022 stage 2).

    Reads phase-1/2 outputs from ``ctx``, writes the ``query_complete``
    log event, attaches trace diagnostics, and returns the result dict
    in the same key order as the legacy ``run_rag_query`` body — the
    JSON-identity contract pinned by
    ``tests/test_langgraph_orchestrator_regression.py``.
    """
    analysis = ctx.analysis or {}
    evidence = ctx.evidence or []
    verification_reasons = ctx.verification_reasons or []
    plan = ctx.plan or {}
    stage_attempts = ctx.stage_attempts or []

    with _StageTimer(ctx.stage_timings, "answer_generation_ms", trace=ctx.trace_handle):
        answer, answer_text, abstained = generate_answer(
            ctx.query,
            analysis,
            evidence,
            ctx.verified,
            verification_reasons,
        )
    synthesis_meta: dict[str, Any] | None = None
    if ctx.prompt_profile == "llm_synthesis" and not abstained:
        with _StageTimer(ctx.stage_timings, "synthesis_ms", trace=ctx.trace_handle, attrs={"prompt_profile": ctx.prompt_profile}):
            synthesized, synthesis_meta = synthesize_answer(
                ctx.query, analysis, answer, evidence
            )
        if synthesized is not None:
            answer = synthesized
            answer_text = synthesized.get("answer_text", answer_text)
    next_state = update_conversation_state(
        ctx.state,
        ctx.query,
        ctx.retrieval_query,
        analysis,
        evidence,
        ctx.context_resolution,
    )
    latency_ms = (time.perf_counter() - ctx.started) * 1000
    stage_latency = {
        "query_analysis_ms": round(ctx.stage_timings.get("query_analysis_ms", 0.0), 2),
        "context_resolution_ms": round(ctx.stage_timings.get("context_resolution_ms", 0.0), 2),
        "answer_generation_ms": round(ctx.stage_timings.get("answer_generation_ms", 0.0), 2),
    }
    if "synthesis_ms" in ctx.stage_timings:
        stage_latency["synthesis_ms"] = round(ctx.stage_timings.get("synthesis_ms", 0.0), 2)
    metadata_resolution = metadata_resolution_diagnostics(
        ctx.retrieval_query,
        analysis,
        selected_stage=str(plan.get("filter_stage") or ""),
    )
    result_trace = build_result_trace(
        ctx.query,
        ctx.retrieval_query,
        analysis,
        plan,
        metadata_resolution,
        ctx.context_resolution,
        ctx.stage_sequence,
        stage_attempts,
        answer,
        stage_latencies_ms=stage_latency,
    )
    diagnostics: dict[str, Any] = {
        "latency_ms": round(latency_ms, 2),
        "retry_count": ctx.retry_count,
        "abstained": abstained,
        "answer_status": answer["status"],
        "answer_query_type": answer["query_type"],
        "claim_count": len(answer["claims"]),
        "citation_count": sum(len(claim.get("citations") or []) for claim in answer["claims"]),
        "verification_reasons": (answer.get("status_reason") or {}).get("verification_reasons") or verification_reasons,
        "verification_topics": verification_topics(analysis),
        "filter_stage_attempts": stage_attempts,
        "retrieved_chunk_ids": ctx.retrieved_chunk_ids,
        "final_relaxation_reason": stage_attempts[-2]["verification_reasons"] if ctx.retry_count and len(stage_attempts) >= 2 else [],
        "context_resolution": ctx.context_resolution,
        "metadata_resolution": metadata_resolution,
        "selected_top_k": plan.get("top_k"),
        "embedding_backend": ctx.index.get("embedding", {}).get("backend"),
        "embedding_model": ctx.index.get("embedding", {}).get("model"),
        "metadata_first": ctx.metadata_first,
        "rerank": ctx.rerank,
        "verifier_retry": ctx.verifier_retry,
        "retrieval_mode": ctx.retrieval_mode,
        "retrieval_backend": ctx.retrieval_backend,
        "rrf_k": int(ctx.rrf_k),
        "bm25_stopword_profile": ctx.bm25_stopword_profile,
        "pipeline": ctx.pipeline_name,
        "prompt_profile": ctx.prompt_profile,
        "cold_start": ctx.cold_start,
        "stage_latency": stage_latency,
        "synthesis": synthesis_meta,
    }
    result = {
        "mode": "rag",
        "query": ctx.query,
        "resolved_query": ctx.retrieval_query,
        "analysis": analysis,
        "plan": plan,
        "answer": answer,
        "answer_text": answer_text,
        "evidence": strip_internal_scores(evidence),
        "trace": result_trace,
        "conversation_state": next_state,
        "diagnostics": diagnostics,
    }
    _attach_trace_diagnostics(
        result,
        ctx.trace_handle,
        ctx.trace_backend_name,
        ctx.trace_unavailable_reason,
        ctx.trace_error,
    )
    log_query_event(
        _LOGGER,
        "query_complete",
        query_hash=ctx.query_hash,
        status=answer["status"],
        query_type=answer["query_type"],
        latency_ms=round(latency_ms, 2),
        retry_count=ctx.retry_count,
        abstained=abstained,
        claim_count=len(answer["claims"]),
        citation_count=diagnostics["citation_count"],
        pipeline=ctx.pipeline_name,
        cold_start=ctx.cold_start,
        trace_backend=ctx.trace_backend_name,
    )
    return result


def run_rag_query(
    index: dict[str, Any],
    query: str,
    top_k: int | None = None,
    context_entities: list[str] | None = None,
    metadata_first: bool | None = None,
    rerank: bool | None = None,
    rerank_cross_encoder: bool | None = None,
    verifier_retry: bool | None = None,
    retrieval_mode: str | None = None,
    retrieval_backend: str | None = None,
    pipeline: str | None = None,
    prompt_profile: str | None = None,
    conversation_state: dict[str, Any] | None = None,
    comparison_balance: dict[str, Any] | None = None,
    rrf_k: int | None = None,
    bm25_stopword_profile: str | None = None,
    bm25_tokenizer: str | None = None,
    *,
    params: QueryParams | None = None,
    _skip_graph: bool = False,
) -> dict[str, Any]:
    # ADR 0040 — agent_react preset dispatches to the ReAct orchestrator
    # unconditionally (pipeline-name routing takes priority over
    # BIDMATE_ORCHESTRATOR so the ReAct loop is always used when requested,
    # regardless of the env var). naive_baseline stays on the direct path
    # (ADR 0001); BIDMATE_PLANNER_BACKEND controls the planner backend.
    _requested_pipeline = str(
        (params.pipeline if params else None) or pipeline or ""
    )
    if not _skip_graph and _requested_pipeline in ("agent_react", "react"):
        from rag_graph_react import run_via_langgraph_react

        return run_via_langgraph_react(
            index,
            query,
            top_k=top_k,
            context_entities=context_entities,
            metadata_first=metadata_first,
            rerank=rerank,
            verifier_retry=verifier_retry,
            retrieval_mode=retrieval_mode,
            retrieval_backend=retrieval_backend,
            pipeline=_requested_pipeline,
            prompt_profile=prompt_profile,
            conversation_state=conversation_state,
            comparison_balance=comparison_balance,
            rrf_k=rrf_k,
            bm25_stopword_profile=bm25_stopword_profile,
            bm25_tokenizer=bm25_tokenizer,
            params=params,
        )

    # ADR 0022 — opt-in LangGraph orchestrator dispatch.
    # ``BIDMATE_ORCHESTRATOR=langgraph`` (default ``direct``) routes
    # through :func:`rag_graph_agentic_full.run_via_langgraph` which
    # builds the run context once and threads it through three nodes
    # (analyze / retrieve_loop / build_answer) — stage 2 of the
    # ADR-0022 migration. Each node calls the same ``_phase_*`` helper
    # the direct path runs, so JSON-identity vs the direct path holds
    # by construction (regression pinned by
    # ``tests/test_langgraph_orchestrator_regression.py``).
    # The ``_skip_graph`` kwarg forces the direct path even with the
    # env var set — kept as a private override for callers that need
    # deterministic dispatch independent of the environment. The
    # ``naive_baseline`` preset stays on the direct path (ADR 0001)
    # regardless of the env var.
    if (
        not _skip_graph
        and os.environ.get("BIDMATE_ORCHESTRATOR", "direct").strip().lower() == "langgraph"
        and (pipeline is None or pipeline != "naive_baseline")
        and (params is None or params.pipeline != "naive_baseline")
    ):
        from rag_graph_agentic_full import run_via_langgraph

        return run_via_langgraph(
            index,
            query,
            top_k=top_k,
            context_entities=context_entities,
            metadata_first=metadata_first,
            rerank=rerank,
            verifier_retry=verifier_retry,
            retrieval_mode=retrieval_mode,
            retrieval_backend=retrieval_backend,
            pipeline=pipeline,
            prompt_profile=prompt_profile,
            conversation_state=conversation_state,
            comparison_balance=comparison_balance,
            rrf_k=rrf_k,
            bm25_stopword_profile=bm25_stopword_profile,
            bm25_tokenizer=bm25_tokenizer,
            params=params,
        )

    ctx = _build_run_context(
        index,
        query,
        top_k=top_k,
        context_entities=context_entities,
        metadata_first=metadata_first,
        rerank=rerank,
        rerank_cross_encoder=rerank_cross_encoder,
        verifier_retry=verifier_retry,
        retrieval_mode=retrieval_mode,
        retrieval_backend=retrieval_backend,
        pipeline=pipeline,
        prompt_profile=prompt_profile,
        conversation_state=conversation_state,
        comparison_balance=comparison_balance,
        rrf_k=rrf_k,
        bm25_stopword_profile=bm25_stopword_profile,
        bm25_tokenizer=bm25_tokenizer,
        params=params,
    )

    early_result = _phase_analyze(ctx)
    if early_result is not None:
        return early_result

    _phase_retrieve_loop(ctx)
    return _phase_build_answer(ctx)


async def arun_rag_query(
    index: dict[str, Any],
    query: str,
    top_k: int | None = None,
    context_entities: list[str] | None = None,
    metadata_first: bool | None = None,
    rerank: bool | None = None,
    verifier_retry: bool | None = None,
    retrieval_mode: str | None = None,
    retrieval_backend: str | None = None,
    pipeline: str | None = None,
    prompt_profile: str | None = None,
    conversation_state: dict[str, Any] | None = None,
    comparison_balance: dict[str, Any] | None = None,
    rrf_k: int | None = None,
    bm25_stopword_profile: str | None = None,
    bm25_tokenizer: str | None = None,
) -> dict[str, Any]:
    """Async-aware entry point for the RAG pipeline (#173 Stage 1).

    Stage 1 (this PR): thin async wrapper that runs
    :func:`run_rag_query` on a worker thread via
    :func:`asyncio.to_thread` so async callers (FastAPI, future
    Streamlit-async hooks) do not block the event loop. The sync
    body and its output are byte-identical to ``run_rag_query`` —
    no behavior change.

    Stage 2 (deferred): fan-out the comparison-query per-target
    retrieval branches with :func:`asyncio.gather`. The async
    surface introduced here is the seam Stage 2 needs.
    """
    import asyncio

    return await asyncio.to_thread(
        run_rag_query,
        index,
        query,
        top_k=top_k,
        context_entities=context_entities,
        metadata_first=metadata_first,
        rerank=rerank,
        verifier_retry=verifier_retry,
        retrieval_mode=retrieval_mode,
        retrieval_backend=retrieval_backend,
        pipeline=pipeline,
        prompt_profile=prompt_profile,
        conversation_state=conversation_state,
        comparison_balance=comparison_balance,
        rrf_k=rrf_k,
        bm25_stopword_profile=bm25_stopword_profile,
        bm25_tokenizer=bm25_tokenizer,
    )


