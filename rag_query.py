"""Query analysis, context resolution, and planning.

Extracted from ``rag_core.py`` (PR-J3, issue #478) as the fourth slice
of the rag_core decomposition (after rag_retrieval PR-H1a/b,
rag_verifier PR-J1, rag_answer PR-J2). Owns the path from raw user
query to the ``plan`` dict that retrieval consumes.

Public functions:

- :func:`analyze_query` — parses the query into entities / topics /
  tokens / query_type / metadata_matches / matched_doc_ids.
- :func:`resolve_conversation_context` — fills implicit references
  using prior turns (``MAX_CONVERSATION_TURNS`` window,
  ``CONTEXT_RESOLUTION_THRESHOLD`` confidence floor).
- :func:`make_plan` — turns analysis + caller kwargs into the plan
  dict (preset config, top_k, retrieval_backend, comparison_balance,
  metadata filters).
- :func:`make_context_resolution` — context-resolution result shape.
- :func:`comparison_targets_for_analysis` — pair of (targets,
  target_field) consumed by retrieval comparison balance.

Query-inspection helpers:

- :func:`is_metadata_ambiguous` — true when metadata matches collide
  by confidence within ``AMBIGUOUS_CONFIDENCE_DELTA``.
- :func:`has_implicit_reference` — pattern match on
  ``IMPLICIT_REFERENCE_PATTERNS`` (e.g. "그 기관", "해당 사업").
- :func:`has_comparison_request` — pattern match on Korean
  comparison cue words ("차이", "비교", "각각", "대비").
- :func:`extract_requested_agencies` — list of explicit agencies
  named in the query.
- :func:`active_state_terms` / :func:`active_state_size` /
  :func:`inject_entities_into_query` — conversation-state helpers.

Metadata diagnostics:

- :func:`summarize_metadata_match` / :func:`metadata_resolution_diagnostics`
- :func:`query_type_default_top_k` — single_doc=4 / follow_up=6 /
  comparison=6 defaults.

Circular-import avoidance: ``rag_core`` symbols used by the block
(``tokenize``, ``ordered_unique``, ``normalize_entity``,
``normalize_metadata_token``, ``metadata_tokens``,
``compact_metadata_text``, ``match_metadata_targets``, and the
``QUERY_TYPE_TOP_K_DEFAULTS`` constant) are late-imported inside the
functions that need them. They serve many non-query call sites in
``rag_core`` (analysis path, indexing, claim builders, observability)
so they stay there.

JSON-identity guarantee: every function moves byte-for-byte. The
verifier / retriever / orchestration regression gates remain green —
``tests/test_naive_baseline_ranking_invariance.py`` (ADR 0001),
``tests/test_retrieval_loop_regression.py``,
``tests/test_langgraph_orchestrator_regression.py``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from korean_lexicon import (
    IMPLICIT_REFERENCE_PATTERNS,
    STOPWORDS,
    TOPIC_KEYWORDS,
)
from rag_conversation_state import CONTEXT_RESOLUTION_THRESHOLD
from rag_pipeline_presets import (
    DEFAULT_RAG_PIPELINE_NAME,
    RRF_K,
    VALID_BM25_STOPWORD_PROFILES,
    VALID_BM25_TOKENIZERS,
    VALID_RETRIEVAL_BACKENDS,
    VALID_RETRIEVAL_MODES,
    VALID_RRF_K_RANGE,
)
from text_normalize import normalize_text


def is_metadata_ambiguous(matches: list[dict[str, Any]], query_type: str) -> bool:
    from rag_core import metadata_ambiguity_details

    return bool(metadata_ambiguity_details(matches, query_type).get("ambiguous"))


def has_implicit_reference(query: str) -> bool:
    from rag_core import normalize_entity

    normalized_query = normalize_entity(query)
    return any(pattern in normalized_query for pattern in IMPLICIT_REFERENCE_PATTERNS)


def has_comparison_request(query: str) -> bool:
    from rag_core import normalize_entity

    comparison_terms = ("차이", "비교", "각각", "대비")
    return any(term in normalize_entity(query) for term in comparison_terms)


def extract_requested_agencies(query: str) -> list[str]:
    from rag_core import ENTITY_RE, normalize_metadata_token, ordered_unique

    agencies = []
    for match in ENTITY_RE.finditer(unicodedata.normalize("NFC", query)):
        token = normalize_metadata_token(match.group(1))
        if not token:
            continue
        if re.fullmatch(r"[a-z0-9]+", token):
            token = token.upper()
        agencies.append(f"기관 {token}")
    return ordered_unique(agencies)


def active_state_terms(state: dict[str, Any]) -> list[str]:
    from rag_core import coerce_string_list, ordered_unique

    terms = [
        *coerce_string_list(state.get("active_agencies")),
        *coerce_string_list(state.get("active_projects")),
    ]
    if terms:
        return ordered_unique(terms)
    return coerce_string_list(state.get("active_doc_ids"))


def active_state_size(state: dict[str, Any]) -> int:
    return max(
        len(state.get("active_agencies") or []),
        len(state.get("active_projects") or []),
        len(state.get("active_doc_ids") or []),
    )


def inject_entities_into_query(query: str, entities: list[str]) -> str:
    """Prepend resolved entities to the retrieval query (issue #71).

    Skips entities that already appear in the query (case-insensitive)
    so user-typed entities don't get duplicated. Order is preserved so
    deterministic reproduction of dense embeddings is unaffected when
    no augmentation is needed.
    """
    if not entities:
        return query
    lowered_query = query.lower()
    missing = [
        entity
        for entity in entities
        if entity and entity.lower() not in lowered_query
    ]
    if not missing:
        return query
    return " ".join([*missing, query])


def make_context_resolution(
    status: str,
    source: str,
    confidence: float,
    reason: str = "",
    resolved_query: str | None = None,
    context_entities: list[str] | None = None,
    context_projects: list[str] | None = None,
    active_doc_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "source": source,
        "confidence": round(float(confidence), 3),
        "reason": reason,
        "resolved_query": resolved_query,
        "context_entities": context_entities or [],
        "context_projects": context_projects or [],
        "active_doc_ids": active_doc_ids or [],
    }


def resolve_conversation_context(
    query: str,
    initial_analysis: dict[str, Any],
    conversation_state: dict[str, Any],
    context_entities: list[str] | None = None,
) -> tuple[str, list[str], dict[str, Any]]:
    from rag_core import coerce_string_list

    explicit_context = coerce_string_list(context_entities or [])
    if explicit_context:
        # Issue #71: prepend entities into the retrieval query string
        # so dense / lexical scoring picks up the entity anchor — the
        # same augmentation the conversation_state branch below
        # already performs. Without this, follow-ups like "그럼 일정은?"
        # carrying `context_entities=["기관 A"]` lost the entity in
        # token space (only the metadata match path saw it). Resolved
        # by injection so dense embedding and `lexical_similarity`
        # both gain the anchor. Real-data taxonomy C4-1.
        augmented_query = inject_entities_into_query(query, explicit_context)
        return (
            augmented_query,
            explicit_context,
            make_context_resolution(
                "resolved",
                "context_entities",
                1.0,
                resolved_query=augmented_query,
                context_entities=explicit_context,
            ),
        )

    if initial_analysis.get("matched_doc_ids"):
        return (
            query,
            [],
            make_context_resolution("not_needed", "query", 1.0, resolved_query=query),
        )

    if not has_implicit_reference(query):
        return (
            query,
            [],
            make_context_resolution("not_needed", "none", 0.0, resolved_query=query),
        )

    state_terms = active_state_terms(conversation_state)
    state_agencies = coerce_string_list(conversation_state.get("active_agencies"))
    state_projects = coerce_string_list(conversation_state.get("active_projects"))
    state_doc_ids = coerce_string_list(conversation_state.get("active_doc_ids"))
    if not state_terms:
        return (
            query,
            [],
            make_context_resolution(
                "needs_clarification",
                "conversation_state",
                0.0,
                reason="no_active_state",
                resolved_query=query,
                active_doc_ids=state_doc_ids,
            ),
        )

    state_confidence = float(conversation_state.get("confidence") or 0.0)
    if state_confidence < CONTEXT_RESOLUTION_THRESHOLD:
        return (
            query,
            [],
            make_context_resolution(
                "needs_clarification",
                "conversation_state",
                state_confidence,
                reason="weak_active_state",
                resolved_query=query,
                context_entities=state_agencies or state_terms,
                context_projects=state_projects,
                active_doc_ids=state_doc_ids,
            ),
        )

    if active_state_size(conversation_state) > 1 and not has_comparison_request(query):
        return (
            query,
            [],
            make_context_resolution(
                "needs_clarification",
                "conversation_state",
                state_confidence,
                reason="ambiguous_active_state",
                resolved_query=query,
                context_entities=state_agencies or state_terms,
                context_projects=state_projects,
                active_doc_ids=state_doc_ids,
            ),
        )

    resolved_query = inject_entities_into_query(query, state_terms)
    return (
        resolved_query,
        state_terms,
        make_context_resolution(
            "resolved",
            "conversation_state",
            state_confidence,
            resolved_query=resolved_query,
            context_entities=state_agencies or state_terms,
            context_projects=state_projects,
            active_doc_ids=state_doc_ids,
        ),
    )


def analyze_query(
    query: str,
    entities: list[Any],
    context_entities: list[str] | None = None,
) -> dict[str, Any]:
    from rag_core import (
        best_metadata_doc_scores,
        coerce_metadata_targets,
        match_metadata_targets,
        metadata_ambiguity_details,
        metadata_filters_from_matches,
        metadata_matches_for_stage,
        normalize_entity,
        ordered_unique,
        tokenize,
    )

    targets = coerce_metadata_targets(entities)
    normalized_query = normalize_entity(query)
    requested_agencies = extract_requested_agencies(normalized_query)
    metadata_matches = match_metadata_targets(normalized_query, targets)

    context_used = False
    if not metadata_matches and context_entities:
        context_matches = []
        for entity in context_entities:
            context_matches.extend(match_metadata_targets(entity, targets))
        if context_matches:
            context_used = True
            metadata_matches = dedupe_metadata_matches(context_matches)

    topics = []
    for keyword in TOPIC_KEYWORDS:
        if keyword.lower() in normalized_query.lower() and keyword not in topics:
            topics.append(keyword)
    for token in tokenize(normalized_query):
        if len(token) > 1 and token not in STOPWORDS:
            if any(token == topic.lower() for topic in topics):
                continue
            if not token.startswith("기관"):
                topics.append(token)

    # ADR 0007 / issue #170: add canonical-form tokens from Korean money/date
    # normalization so substring topic matching can bridge 5천만원 ↔ 50,000,000.
    # Strictly additive — existing tokens are kept; new tokens compete for the
    # topics[:8] cap on equal footing.
    canonical_query = normalize_text(normalized_query)
    if canonical_query != normalized_query:
        existing = {topic.lower() for topic in topics}
        for token in tokenize(canonical_query):
            if (
                len(token) > 1
                and token not in STOPWORDS
                and not token.startswith("기관")
                and token.lower() not in existing
            ):
                topics.append(token)
                existing.add(token.lower())

    comparison_terms = ("차이", "비교", "각각", "대비")
    comparison_joiners = ("와", "과", "및", ",", "/")
    reduced_matches = metadata_matches_for_stage(metadata_matches, "reduced")
    matched_doc_ids = ordered_unique(match["doc_id"] for match in reduced_matches)
    matched_agencies = ordered_unique(match["agency"] for match in reduced_matches)
    matched_projects = ordered_unique(match["project"] for match in reduced_matches)
    has_comparison_term = any(term in normalized_query for term in comparison_terms)
    has_multi_target_joiner = len(matched_agencies) > 1 and any(
        joiner in normalized_query for joiner in comparison_joiners
    )
    if has_comparison_term or has_multi_target_joiner:
        query_type = "comparison"
    elif context_used:
        query_type = "follow_up"
    else:
        query_type = "single_doc"
    analysis_entities = matched_agencies
    if query_type == "comparison":
        analysis_entities = ordered_unique([*requested_agencies, *matched_agencies])

    strict_matches = metadata_matches_for_stage(metadata_matches, "strict")
    strict_filters = metadata_filters_from_matches(strict_matches)
    reduced_filters = metadata_filters_from_matches(reduced_matches)
    ambiguity = metadata_ambiguity_details(metadata_matches, query_type)

    return {
        "query_type": query_type,
        "entities": analysis_entities,
        "requested_entities": requested_agencies,
        "missing_requested_entities": [
            entity for entity in requested_agencies if entity not in matched_agencies
        ],
        "topics": topics[:8],
        "context_entities": context_entities or [],
        "context_used": context_used,
        "tokens": tokenize(normalized_query),
        "metadata_matches": metadata_matches,
        "matched_doc_ids": matched_doc_ids,
        "matched_agencies": matched_agencies,
        "matched_projects": matched_projects,
        "metadata_confidence": round(max((m["confidence"] for m in metadata_matches), default=0.0), 3),
        "metadata_ambiguous": bool(ambiguity.get("ambiguous")),
        "metadata_ambiguity": ambiguity,
        "metadata_filters_by_stage": {
            "strict": strict_filters,
            "reduced": reduced_filters,
            "relaxed": {},
        },
        "metadata_doc_scores": best_metadata_doc_scores(reduced_matches),
    }


def comparison_targets_for_analysis(analysis: dict[str, Any]) -> tuple[list[str], str]:
    """Return (targets, target_field) for comparison balancing.

    Prefers matched doc_ids when ≥2 are present; otherwise falls back to matched
    agencies. Returns ([], "") when balancing is not applicable.
    """
    from rag_core import ordered_unique

    matched_doc_ids = list(analysis.get("matched_doc_ids") or [])
    if len(matched_doc_ids) >= 2:
        return ordered_unique(matched_doc_ids), "doc_id"
    entities = list(analysis.get("entities") or [])
    if len(entities) >= 2:
        return ordered_unique(entities), "agency"
    return [], ""


def summarize_metadata_match(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": match.get("doc_id", ""),
        "field": match.get("field", ""),
        "value": match.get("value", ""),
        "agency": match.get("agency", ""),
        "project": match.get("project", ""),
        "confidence": match.get("confidence", 0.0),
        "stage": match.get("stage", ""),
        "match_type": match.get("match_type", ""),
        "matched_terms": match.get("matched_terms", []),
    }


def metadata_resolution_diagnostics(
    query: str,
    analysis: dict[str, Any],
    *,
    selected_stage: str | None = None,
    decision: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    from rag_core import (
        coerce_string_list,
        compact_metadata_text,
        metadata_matches_for_stage,
        metadata_tokens,
        normalize_entity,
        ordered_unique,
    )

    matches = list(analysis.get("metadata_matches") or [])
    selected_by_stage: dict[str, list[dict[str, Any]]] = {}
    for stage in ("strict", "reduced"):
        selected_by_stage[stage] = [
            summarize_metadata_match(match)
            for match in metadata_matches_for_stage(matches, stage)
        ]
    selected_by_stage["relaxed"] = []

    selected_stage = selected_stage or ""
    selected_matches = selected_by_stage.get(selected_stage, [])
    ambiguity = dict(analysis.get("metadata_ambiguity") or {})
    ambiguous = bool(analysis.get("metadata_ambiguous"))
    if decision is None:
        decision = "clarify" if ambiguous and analysis.get("query_type") != "comparison" else "use_selected_candidates"

    return {
        "normalized_query": normalize_entity(query),
        "normalized_query_compact": compact_metadata_text(query),
        "normalized_query_tokens": metadata_tokens(query),
        "candidate_count": len(matches),
        "candidates": [summarize_metadata_match(match) for match in matches],
        "selected_stage": selected_stage,
        "selected_candidates_by_stage": selected_by_stage,
        "selected_candidates": selected_matches,
        "selected_doc_ids": ordered_unique(match.get("doc_id", "") for match in selected_matches),
        "matched_doc_ids": coerce_string_list(analysis.get("matched_doc_ids")),
        "ambiguity": {
            **ambiguity,
            "ambiguous": ambiguous,
            "decision": decision,
            "decision_reason": reason or ambiguity.get("reason", ""),
        },
    }


def query_type_default_top_k(query_type: str) -> int:
    from rag_core import QUERY_TYPE_TOP_K_DEFAULTS

    return QUERY_TYPE_TOP_K_DEFAULTS.get(query_type, QUERY_TYPE_TOP_K_DEFAULTS["single_doc"])


def make_plan(
    analysis: dict[str, Any],
    relaxed: bool = False,
    top_k: int | None = None,
    top_k_reason: str | None = None,
    stage: str | None = None,
    metadata_first: bool = True,
    rerank: bool = True,
    verifier_retry: bool = True,
    retrieval_mode: str = "flat",
    retrieval_backend: str = "dense",
    pipeline: str = DEFAULT_RAG_PIPELINE_NAME,
    prompt_profile: str = "structured_grounded_claims",
    comparison_balance: dict[str, Any] | None = None,
    rrf_k: int = RRF_K,
    bm25_stopword_profile: str = "shared",
    bm25_tokenizer: str = "regex",
) -> dict[str, Any]:
    from rag_core import QUERY_TYPE_TOP_K_DEFAULTS

    if retrieval_mode not in VALID_RETRIEVAL_MODES:
        choices = ", ".join(sorted(VALID_RETRIEVAL_MODES))
        raise ValueError(f"retrieval_mode must be one of: {choices}")
    if retrieval_backend not in VALID_RETRIEVAL_BACKENDS:
        choices = ", ".join(sorted(VALID_RETRIEVAL_BACKENDS))
        raise ValueError(f"retrieval_backend must be one of: {choices}")
    rrf_lo, rrf_hi = VALID_RRF_K_RANGE
    if int(rrf_k) < rrf_lo or int(rrf_k) > rrf_hi:
        raise ValueError(f"rrf_k must be in [{rrf_lo}, {rrf_hi}].")
    if bm25_stopword_profile not in VALID_BM25_STOPWORD_PROFILES:
        choices = ", ".join(sorted(VALID_BM25_STOPWORD_PROFILES))
        raise ValueError(f"bm25_stopword_profile must be one of: {choices}")
    if bm25_tokenizer not in VALID_BM25_TOKENIZERS:
        choices = ", ".join(sorted(VALID_BM25_TOKENIZERS))
        raise ValueError(f"bm25_tokenizer must be one of: {choices}")
    query_type = str(analysis.get("query_type") or "single_doc")
    default_top_k = query_type_default_top_k(query_type)
    budget_reason = top_k_reason or (
        "explicit_override" if top_k is not None else f"{query_type}_default"
    )

    targets, target_field = comparison_targets_for_analysis(analysis)
    balance_enabled = bool(
        comparison_balance
        and comparison_balance.get("enabled")
        and analysis.get("query_type") == "comparison"
        and len(targets) >= 2
    )
    if balance_enabled and analysis.get("query_type") == "comparison":
        k_per_target = int(comparison_balance.get("k_per_target", 3))
        headroom = int(comparison_balance.get("headroom", 2))
        max_top_k = int(comparison_balance.get("max_top_k", 12))
        adaptive = k_per_target * len(targets) + headroom
        default_top_k = max(default_top_k, min(max_top_k, adaptive))
        if top_k is None:
            budget_reason = "comparison_coverage_adaptive"

    if relaxed:
        stage = "relaxed"
    if not metadata_first:
        stage = "relaxed"
    stage = stage or "strict"
    if stage == "relaxed":
        filters = {}
    else:
        filters_by_stage = analysis.get("metadata_filters_by_stage") or {}
        filters = filters_by_stage.get(stage) or {}
        if not filters and not filters_by_stage:
            filters = {"agencies": analysis.get("entities", [])}
    scoring = "dense"
    if rerank and metadata_first:
        scoring = "dense + lexical + metadata rerank"
    elif rerank:
        scoring = "dense + lexical rerank"
    if retrieval_backend == "hybrid":
        scoring = f"hybrid (bm25 + {scoring}) rrf"
    elif retrieval_backend == "m3":
        # Issue #151 — BGE-M3 dense + sparse + ColBERT multi-vector fused
        # via N-way RRF. Opt-in measurement spike; see
        # ``docs/m3-multichannel-spike.md``.
        scoring = "m3 (dense + sparse + colbert) rrf"
    plan: dict[str, Any] = {
        "strategy": scoring if not metadata_first else f"metadata-first {scoring}",
        "pipeline": pipeline,
        "prompt_profile": prompt_profile,
        "filter_stage": stage,
        "metadata_first": metadata_first,
        "rerank": rerank,
        "verifier_retry": verifier_retry,
        "retrieval_mode": retrieval_mode,
        "retrieval_backend": retrieval_backend,
        "rrf_k": int(rrf_k),
        "bm25_stopword_profile": bm25_stopword_profile,
        "bm25_tokenizer": bm25_tokenizer,
        "metadata_filters": filters,
        "top_k": top_k or default_top_k,
        "retrieval_budget": {
            "selected_top_k": top_k or default_top_k,
            "query_type": query_type,
            "reason": budget_reason,
            "defaults": dict(QUERY_TYPE_TOP_K_DEFAULTS),
        },
        "relaxed": stage == "relaxed",
        "retry_policy": "try strict metadata filters, then reduced fuzzy filters, then relaxed retrieval",
    }
    if comparison_balance is not None:
        plan["comparison_balance"] = dict(comparison_balance)
    if targets:
        plan["comparison_targets"] = targets
        plan["comparison_target_field"] = target_field
    return plan


