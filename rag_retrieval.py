"""Retrieval pipeline: candidate generation, fusion, and rerank.

Extracted from ``rag_core.py`` across two slices:

- PR-H1a (issue #459): :func:`apply_fusion_and_reranking` and helpers
  (post-candidate-scoring path).
- PR-H1b (issue #461): :func:`retrieve_candidates` (candidate generation),
  the four similarity primitives (``embed_query_for_index``,
  ``dense_similarity``, ``lexical_similarity``, ``metadata_similarity``),
  and the BM25 corpus / scoring helpers
  (``_strip_bm25_extra_suffixes`` / ``_apply_bm25_extra_filter`` /
  ``_chunk_tokens_for_bm25`` / ``get_or_build_bm25`` /
  ``bm25_scores_for_index``).

Public functions:

- :func:`retrieve_candidates` — pre-fusion phase: filter + per-chunk
  dense / lexical / metadata / BM25 / m3 scoring. Mutates ``plan`` with
  ``candidate_count``, ``total_chunks``, ``filter_fallback_used``.
- :func:`apply_fusion_and_reranking` — RRF fusion (`hybrid` 2-way,
  `m3` 3-way), optional cross-encoder rerank dispatch (via
  ``rag_reranker.default_reranker``), then either hierarchical
  reassembly or comparison-balanced top-k.
- :func:`apply_comparison_balance` — coverage-aware top-k that
  guarantees ``min_per_target`` items per comparison target before
  filling by global score. No-op for non-comparison queries.
- :func:`reassemble_parent_sections` — hierarchical mode that promotes
  the best child chunk per parent section into a single result.
- :func:`embed_query_for_index` — backend-dispatched query embedding.
- :func:`dense_similarity`, :func:`lexical_similarity`,
  :func:`metadata_similarity` — per-chunk scoring primitives.
- :func:`bm25_scores_for_index`, :func:`get_or_build_bm25` — BM25
  index-side surface (lazy build + per-profile cache, issue #150).

Internal helpers :func:`_coverage_counts`,
:func:`_strip_bm25_extra_suffixes`, :func:`_apply_bm25_extra_filter`,
:func:`_chunk_tokens_for_bm25` are module-private (underscore
preserved from the rag_core layout).

Circular-import avoidance: ``rag_core`` symbols that this module's
functions need (``tokenize``, ``DEFAULT_EMBEDDING_MODEL`` /
``DEFAULT_HASH_DIM``, ``embed_texts`` / ``hashing_embeddings``,
``normalize_regions`` / ``normalize_page_span``) are late-imported at
function-call time. These helpers serve many non-retrieval call sites
in ``rag_core`` (ingestion path, evidence building, partial-topic
grounding, ...), so they stay there; the late-import idiom keeps this
module a true leaf of the dependency graph from rag_core's
perspective while still allowing reuse.

JSON-identity guarantee: every function is moved byte-for-byte from
``rag_core``. ``tests/test_naive_baseline_ranking_invariance.py``,
``tests/test_retrieval_loop_regression.py``, and
``tests/test_langgraph_orchestrator_regression.py`` are the regression
gates.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

import numpy as np

from korean_lexicon import BM25_EXTRA_PARTICLE_SUFFIXES, BM25_EXTRA_STOPWORDS
from rag_pipeline_presets import RRF_K, VALID_BM25_STOPWORD_PROFILES
from rag_query_expansion import default_expander

try:  # noqa: SIM105 — import errors must keep _BM25Okapi defined
    from rank_bm25 import BM25Okapi as _BM25Okapi
except ImportError:
    _BM25Okapi = None  # type: ignore[assignment]


def apply_fusion_and_reranking(
    scored: list[dict[str, Any]],
    index: dict[str, Any],
    query: str,
    analysis: dict[str, Any],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fuse, sort, optionally cross-encoder rerank, then apply top-k.
    Takes the pre-fusion list from ``retrieve_candidates`` and returns
    the final ranked evidence. Mutates ``plan`` with
    ``rerank_cross_encoder_meta`` only when the cross-encoder stage
    runs (unchanged behavior)."""
    retrieval_backend = str(plan.get("retrieval_backend", "dense"))
    # RRF channel selection by backend. ``hybrid`` stays 2-way (dense +
    # bm25) — bit-identical to ADR 0010. ``m3`` is 3-way (dense + m3_sparse
    # + m3_colbert) per issue #151 measurement spike. Both share the
    # same N-way RRF + normalization math below.
    rrf_channel_keys: tuple[str, ...] = ()
    if retrieval_backend == "hybrid":
        rrf_channel_keys = ("dense", "bm25")
    elif retrieval_backend == "m3":
        rrf_channel_keys = ("dense", "m3_sparse", "m3_colbert")
    if rrf_channel_keys and scored:
        # Stable rank-by-channel: sort by (channel_score desc, chunk_id) so
        # ties resolve deterministically. Same idiom as the ADR 0010
        # hybrid path it replaces.
        channel_ranks: dict[str, dict[str, int]] = {}
        for key in rrf_channel_keys:
            ordered = sorted(
                scored,
                key=lambda it, k=key: (it["score_parts"].get(k, 0.0), it["chunk_id"]),
                reverse=True,
            )
            channel_ranks[key] = {it["chunk_id"]: rank for rank, it in enumerate(ordered)}
        # Raw N-way RRF tops out at N/k. Normalize to [0,1] so the
        # verifier's score floor (rag_core.py:2254, threshold 0.18 tuned
        # for the dense+lexical fusion) keeps working for every backend
        # without per-backend branches. ``rrf_k`` is plan-time
        # configurable per issue #149; default still ``RRF_K = 60``.
        rrf_k = int(plan.get("rrf_k", RRF_K))
        rrf_norm = rrf_k / float(len(rrf_channel_keys))
        for item in scored:
            cid = item["chunk_id"]
            rrf = sum(1.0 / (rrf_k + ranks[cid]) for ranks in channel_ranks.values())
            item["score"] = round(float(rrf * rrf_norm), 6)
            item["score_parts"]["rank_rrf"] = round(float(rrf * rrf_norm), 6)

    scored.sort(key=lambda item: item["score"], reverse=True)
    if plan.get("rerank_cross_encoder"):
        from rag_reranker import default_reranker

        top_n = min(30, max(int(plan["top_k"] or 10) * 3, int(plan["top_k"] or 10)))
        scored, rerank_meta = default_reranker().rerank(query, scored, top_n=top_n)
        plan["rerank_cross_encoder_meta"] = rerank_meta
    top_k = int(plan["top_k"])
    if plan.get("retrieval_mode") == "hierarchical":
        return reassemble_parent_sections(index, scored, top_k, plan, analysis)
    return apply_comparison_balance(scored, analysis, plan, top_k)


def _coverage_counts(
    items: list[dict[str, Any]],
    targets: list[str],
    target_field: str,
) -> dict[str, int]:
    counts = {target: 0 for target in targets}
    for item in items:
        value = item.get(target_field)
        if value in counts:
            counts[value] += 1
    return counts


def apply_comparison_balance(
    scored: list[dict[str, Any]],
    analysis: dict[str, Any],
    plan: dict[str, Any],
    top_k: int,
) -> list[dict[str, Any]]:
    """Apply coverage-aware top-k cut for comparison queries.

    For non-comparison queries or when fewer than two targets are matched, this
    is a no-op equivalent to ``scored[:top_k]``. When enabled, it guarantees up
    to ``min_per_target`` top-scoring items per comparison target before
    filling the remainder by global score. Records ``comparison_coverage``
    diagnostics on the plan dict either way (so observability is consistent
    across enabled/disabled states).
    """
    # Late-import to avoid circular dependency: rag_core imports this
    # module's public functions, and comparison_targets_for_analysis
    # lives in rag_core because it is also called from
    # rag_core.retrieve_candidates (kept there in PR-H1a).
    from rag_core import comparison_targets_for_analysis

    targets, target_field = comparison_targets_for_analysis(analysis)
    is_comparison = analysis.get("query_type") == "comparison" and len(targets) >= 2

    balance_config = plan.get("comparison_balance") or {}
    enabled = bool(balance_config.get("enabled")) and is_comparison

    if not is_comparison:
        return scored[:top_k]

    before = _coverage_counts(scored, targets, target_field)

    if not enabled:
        selected = scored[:top_k]
        plan["comparison_coverage"] = {
            "targets": targets,
            "target_field": target_field,
            "before": before,
            "after": _coverage_counts(selected, targets, target_field),
            "balanced": False,
        }
        return selected

    min_per_target = max(1, int(balance_config.get("min_per_target", 1)))
    if len(targets) > 0:
        max_min = max(1, top_k // len(targets))
        effective_min = min(min_per_target, max_min)
    else:
        effective_min = min_per_target

    selected_ids: set[str] = set()
    selected: list[dict[str, Any]] = []
    for target in targets:
        picks = 0
        for item in scored:
            if picks >= effective_min:
                break
            if item.get("chunk_id") in selected_ids:
                continue
            if item.get(target_field) == target:
                selected.append(item)
                selected_ids.add(item.get("chunk_id"))
                picks += 1

    for item in scored:
        if len(selected) >= top_k:
            break
        if item.get("chunk_id") in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(item.get("chunk_id"))

    selected.sort(key=lambda item: item["score"], reverse=True)
    selected = selected[:top_k]

    plan["comparison_coverage"] = {
        "targets": targets,
        "target_field": target_field,
        "before": before,
        "after": _coverage_counts(selected, targets, target_field),
        "balanced": True,
        "min_per_target": effective_min,
    }
    return selected


def reassemble_parent_sections(
    index: dict[str, Any],
    scored_chunks: list[dict[str, Any]],
    top_k: int,
    plan: dict[str, Any],
    analysis: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # Late-import to avoid circular dependency: rag_core uses
    # normalize_regions / normalize_page_span in many non-retrieval
    # call sites (ingestion path, evidence building, ...), so they
    # stay in rag_core.
    from rag_core import normalize_regions, normalize_page_span

    parent_by_id = {
        str(section.get("section_id")): section
        for section in index.get("parent_sections", [])
        if section.get("section_id")
    }
    best_by_parent: dict[str, dict[str, Any]] = {}
    child_ids_by_parent: dict[str, list[str]] = {}

    for chunk in scored_chunks:
        parent_id = str(
            chunk.get("parent_section_id") or chunk.get("section_id") or chunk.get("chunk_id")
        )
        child_ids_by_parent.setdefault(parent_id, []).append(chunk["chunk_id"])
        current = best_by_parent.get(parent_id)
        if current is None or chunk["score"] > current["score"]:
            best_by_parent[parent_id] = chunk

    plan["parent_candidate_count"] = len(best_by_parent)

    reassembled = []
    for parent_id, best_chunk in best_by_parent.items():
        parent = parent_by_id.get(parent_id)
        if not parent:
            item = dict(best_chunk)
            item["retrieval_mode"] = "hierarchical_fallback"
            item["child_chunk_ids"] = child_ids_by_parent.get(parent_id, [])
            reassembled.append(item)
            continue

        item = {
            **best_chunk,
            "section_id": parent.get("section_id"),
            "parent_section_id": parent_id,
            "section": parent.get("section", best_chunk.get("section", "")),
            "section_path": parent.get("section_path") or best_chunk.get("section_path") or [],
            "text": parent.get("text", best_chunk.get("text", "")),
            "chunking_strategy": parent.get("chunking_strategy", best_chunk.get("chunking_strategy", "")),
            "retrieval_mode": "hierarchical",
            "child_chunk_ids": child_ids_by_parent.get(parent_id, []),
        }
        parent_regions = normalize_regions(parent.get("regions"))
        parent_page_span = normalize_page_span(parent.get("page_span"), parent_regions)
        if parent_regions:
            item["regions"] = parent_regions
        if parent_page_span:
            item["page_span"] = parent_page_span
        reassembled.append(item)

    reassembled.sort(key=lambda item: item["score"], reverse=True)
    if analysis is not None:
        return apply_comparison_balance(reassembled, analysis, plan, top_k)
    return reassembled[:top_k]
def retrieve_candidates(
    index: dict[str, Any],
    query: str,
    analysis: dict[str, Any],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Filter + per-chunk dense / lexical / metadata / BM25 scoring; the
    pre-fusion phase of ``retrieve``. Split out so future Phase 3
    multi-query / HyDE work can fan out this phase without piling onto
    the fusion+rerank tail. Mutates ``plan`` with ``candidate_count``,
    ``total_chunks``, ``filter_fallback_used`` (unchanged order)."""
    # Late-import region helpers — they serve many non-retrieval call
    # sites in rag_core (ingestion, evidence builder, partial-topic
    # grounding) so they stay there. Late-import avoids the circular
    # ``rag_retrieval ← rag_core ← rag_retrieval`` chain.
    from rag_core import normalize_page_span, normalize_regions

    chunks = index["chunks"]
    filters = plan.get("metadata_filters") or {}
    doc_ids = set(filters.get("doc_ids") or [])
    agencies = set(filters.get("agencies") or [])
    projects = set(filters.get("projects") or [])
    candidates = [
        c
        for c in chunks
        if (
            (doc_ids and c.get("doc_id") in doc_ids)
            or (not doc_ids and agencies and c.get("agency") in agencies)
            or (not doc_ids and projects and c.get("project") in projects)
            or not (doc_ids or agencies or projects)
        )
    ]
    plan["candidate_count"] = len(candidates)
    plan["total_chunks"] = len(chunks)
    plan["filter_fallback_used"] = False
    if not candidates:
        candidates = chunks
        plan["candidate_count"] = len(candidates)
        plan["filter_fallback_used"] = True

    embedding_config = index.get("embedding", {})
    # #396 / ADR 0023 — pluggable query expansion. Default is the
    # ``IdentityExpander`` so ``naive_baseline`` and any preset without
    # an explicit ``query_expansion`` knob produce a bit-identical
    # ``embed_query_for_index`` call (ADR 0001 golden invariant).
    # HyDE replaces ONLY the dense embedding input — the BM25 / lexical /
    # metadata paths below consume ``analysis.tokens`` (computed
    # upstream from the raw ``query``), so they remain invariant.
    expander = default_expander(plan)
    embed_text, expansion_meta = expander.expand(query, plan=plan)
    plan["query_expansion_meta"] = expansion_meta
    query_embedding = embed_query_for_index(embed_text, embedding_config)
    query_tokens = set(analysis.get("tokens", []))
    query_topics = analysis.get("topics", [])
    retrieval_backend = str(plan.get("retrieval_backend", "dense"))

    bm25_score_by_chunk: dict[str, float] = {}
    if retrieval_backend == "hybrid":
        bm25_score_by_chunk = bm25_scores_for_index(
            index,
            list(query_tokens),
            stopword_profile=str(plan.get("bm25_stopword_profile", "shared")),
        )

    # Issue #151 — BGE-M3 multi-channel spike. Lazy: only entered when
    # the caller opted into ``retrieval_backend = "m3"``. Default ``dense``
    # and ``hybrid`` paths skip the import + forward pass entirely
    # (ADR 0001 bit-identical invariant; public CI never installs the
    # FlagEmbedding dep). Cache is per-index, in-memory only — no schema
    # change to ``index.json`` for the spike.
    m3_sparse_by_chunk: dict[str, float] = {}
    m3_colbert_by_chunk: dict[str, float] = {}
    if retrieval_backend == "m3":
        from rag_m3 import compute_m3_index_cache, get_m3_encoder

        encoder = get_m3_encoder()
        cache = index.get("_m3_cache")
        if cache is None:
            cache = compute_m3_index_cache(encoder, chunks)
            index["_m3_cache"] = cache
        query_m3 = encoder.encode([query])
        q_sparse = query_m3.sparse[0] if query_m3.sparse else {}
        q_colbert = query_m3.colbert[0] if query_m3.colbert else np.zeros((0, 0), dtype=np.float32)
        # Score every chunk against the query on the two new channels.
        # Dense score is reused from the existing ``raw_cosine_by_idx``
        # path below — BGE-M3 dense vectors aren't re-routed through the
        # vector store for the spike; the chunk's existing dense channel
        # (whatever embedding backend built the index) plays the role of
        # the "dense rank". A follow-up PR can swap the dense channel
        # for BGE-M3's if the spike justifies it.
        for chunk_idx, chunk in enumerate(chunks):
            chunk_id = str(chunk.get("chunk_id"))
            m3_sparse_by_chunk[chunk_id] = encoder.sparse_score(
                q_sparse, cache.sparse[chunk_idx] if chunk_idx < len(cache.sparse) else {}
            )
            colbert_vec = (
                cache.colbert[chunk_idx]
                if chunk_idx < len(cache.colbert)
                else np.zeros((0, 0), dtype=np.float32)
            )
            m3_colbert_by_chunk[chunk_id] = encoder.colbert_score(q_colbert, colbert_vec)

    vector_store = index.get("_vector_store")
    # #176 Stage 2c: drive dense scoring through ``VectorStore.query``
    # instead of looping ``store.get(idx)`` + ``dense_similarity`` per
    # chunk. On the default in-memory backend the math is identical
    # (numpy dot on the same L2-normalized matrix, then the same
    # ``(cosine + 1) / 2`` affine clamp). On the Qdrant backend the
    # query is delegated to the Qdrant collection — ranking parity to
    # the in-memory backend is asserted by
    # ``tests/test_vector_store_qdrant.py::test_qdrant_query_matches_in_memory_top_k_ranking``
    # (PR #296, 1e-5 tolerance). Inline-embedding fixtures fall back
    # to the per-chunk ``dense_similarity`` path below.
    raw_cosine_by_idx: dict[int, float] = {}
    if vector_store is not None and len(vector_store) > 0:
        for idx, raw in vector_store.query(query_embedding, top_k=len(vector_store)):
            raw_cosine_by_idx[int(idx)] = float(raw)
    scored = []
    for chunk in candidates:
        embedding_idx = chunk.get("embedding_idx")
        if (
            vector_store is not None
            and embedding_idx is not None
            and int(embedding_idx) in raw_cosine_by_idx
        ):
            raw = raw_cosine_by_idx[int(embedding_idx)]
            # Mirror ``dense_similarity``'s affine clamp so the verifier
            # score floor (rag_core.py:2254, threshold tuned for
            # ``(cosine + 1) / 2``) keeps working byte-identically.
            dense_score = max(0.0, min(1.0, (raw + 1.0) / 2.0))
        else:
            # Defensive fallback: a chunk dict produced outside the normal
            # load_index path (e.g., a hand-crafted test fixture) may still
            # carry an inline embedding. Keeps tests/test_partial_topic_*.py
            # style fixtures working without forcing a sidecar.
            chunk_vec = chunk.get("embedding")
            dense_score = dense_similarity(query_embedding, chunk_vec)
        lexical_score = lexical_similarity(query_tokens, query_topics, chunk)
        metadata_score = metadata_similarity(analysis, chunk)
        chunk_id_str = str(chunk.get("chunk_id"))
        bm25_score = float(bm25_score_by_chunk.get(chunk_id_str, 0.0))
        m3_sparse_score = float(m3_sparse_by_chunk.get(chunk_id_str, 0.0))
        m3_colbert_score = float(m3_colbert_by_chunk.get(chunk_id_str, 0.0))
        if retrieval_backend in ("hybrid", "m3"):
            # RRF backends defer scoring to ``apply_fusion_and_reranking``
            # — the per-chunk score here is a placeholder. The
            # diagnostic ``score_parts`` keys carry the channel-level
            # signals for the fusion stage to rank on.
            score = 0.0
        elif not plan.get("rerank", True):
            score = dense_score
        elif not plan.get("metadata_first", True):
            score = (0.70 * dense_score) + (0.30 * lexical_score)
        else:
            score = (0.60 * dense_score) + (0.25 * lexical_score) + (0.15 * metadata_score)
        score_parts: dict[str, float] = {
            "dense": round(float(dense_score), 4),
            "lexical": round(float(lexical_score), 4),
            "metadata": round(float(metadata_score), 4),
            "bm25": round(float(bm25_score), 4),
        }
        if retrieval_backend == "m3":
            # Diagnostic-only; consumed by N-way RRF downstream. Score
            # ranges: sparse ≥ 0 (SPLADE dot), colbert ∈ [0, T_q]
            # (max-sim sum). Rounded for log stability.
            score_parts["m3_sparse"] = round(float(m3_sparse_score), 4)
            score_parts["m3_colbert"] = round(float(m3_colbert_score), 4)
        item = {
            "doc_id": chunk["doc_id"],
            "chunk_id": chunk["chunk_id"],
            "title": chunk["title"],
            "agency": chunk.get("agency", ""),
            "project": chunk.get("project", ""),
            "metadata": chunk.get("metadata", {}),
            "section": chunk["section"],
            "section_id": chunk.get("section_id"),
            "parent_section_id": chunk.get("parent_section_id") or chunk.get("section_id"),
            "section_path": chunk.get("section_path") or [chunk.get("section", "")],
            "chunk_seq_in_section": chunk.get("chunk_seq_in_section"),
            "total_chunks_in_section": chunk.get("total_chunks_in_section"),
            "chunking_strategy": chunk.get("chunking_strategy", "legacy"),
            "retrieval_mode": "flat",
            "text": chunk["text"],
            "score": round(float(score), 4),
            "score_parts": score_parts,
        }
        regions = normalize_regions(chunk.get("regions"))
        page_span = normalize_page_span(chunk.get("page_span"), regions)
        if regions:
            item["regions"] = regions
        if page_span:
            item["page_span"] = page_span
        scored.append(item)
    return scored



def embed_query_for_index(query: str, embedding_config: dict[str, Any]) -> np.ndarray:
    # Late-import the embedding constants + backend dispatchers from
    # rag_core. They are also used by the index-build path, so they
    # stay there as the canonical home; this function just reads them.
    from rag_core import (
        DEFAULT_EMBEDDING_MODEL,
        DEFAULT_HASH_DIM,
        embed_texts,
        hashing_embeddings,
    )

    backend = str(embedding_config.get("backend") or "hashing")
    model = str(embedding_config.get("model") or DEFAULT_EMBEDDING_MODEL)
    dimension = int(embedding_config.get("dimension") or DEFAULT_HASH_DIM)
    if backend == "sentence-transformers":
        try:
            return embed_texts(
                [query],
                model_name=model,
                backend="sentence-transformers",
                local_only=True,
            ).vectors[0]
        except Exception:
            return hashing_embeddings([query], dimension)[0]
    if backend == "openai":
        try:
            return embed_texts([query], model_name=model, backend="openai").vectors[0]
        except Exception:
            return hashing_embeddings([query], dimension)[0]
    return hashing_embeddings([query], dimension)[0]


def dense_similarity(query_vector: np.ndarray, chunk_vector: Any) -> float:
    if chunk_vector is None:
        return 0.0
    doc_vector = np.asarray(chunk_vector, dtype=np.float32)
    if doc_vector.shape != query_vector.shape:
        return 0.0
    score = float(np.dot(query_vector, doc_vector))
    return max(0.0, min(1.0, (score + 1.0) / 2.0))


def _strip_bm25_extra_suffixes(token: str) -> str:
    """Strip ``BM25_EXTRA_PARTICLE_SUFFIXES`` greedily from a pure-Hangul token.

    Mirrors :func:`normalize_metadata_token`'s suffix-stripping loop but
    against the BM25-only extension list (issue #150). Returns the
    original token unchanged for non-Hangul tokens.
    """
    if not re.fullmatch(r"[가-힣]+", token):
        return token
    changed = True
    while changed:
        changed = False
        for suffix in BM25_EXTRA_PARTICLE_SUFFIXES:
            if len(token) > len(suffix) + 1 and token.endswith(suffix):
                token = token[: -len(suffix)]
                changed = True
                break
    return token


def _apply_bm25_extra_filter(tokens: Iterable[str]) -> list[str]:
    """Apply the BM25-extra particle suffix strip + stopword filter (issue #150).

    Called only from the BM25 corpus-build and query-side paths under
    ``bm25_stopword_profile = "bm25_extra"``. Never touches the tokens
    cached on chunks at index time, so the dense + Jaccard lexical
    scoring paths stay bit-stable (issue #150 acceptance criterion).
    """
    out: list[str] = []
    for token in tokens:
        stripped = _strip_bm25_extra_suffixes(str(token))
        if stripped and stripped not in BM25_EXTRA_STOPWORDS:
            out.append(stripped)
    return out


def _chunk_tokens_for_bm25(
    chunk: dict[str, Any],
    stopword_profile: str = "shared",
) -> list[str]:
    # Late-import the regex-based tokenizer from rag_core. ``tokenize``
    # serves many non-retrieval surfaces (ingestion-time chunk token
    # cache, query analyzer, partial-topic check, ...) so it stays in
    # rag_core; this module's BM25 surface uses it only as a fallback
    # when the chunk doesn't carry a pre-computed token list.
    from rag_core import tokenize

    tokens = chunk.get("tokens")
    if isinstance(tokens, list) and tokens:
        base = [str(t) for t in tokens]
    else:
        section_path = chunk.get("section_path") or [chunk.get("section", "")]
        text = " ".join(
            [
                chunk.get("title", ""),
                chunk.get("agency", ""),
                chunk.get("project", ""),
                " > ".join(section_path),
                chunk.get("text", ""),
            ]
        )
        base = tokenize(text)
    if stopword_profile == "bm25_extra":
        base = _apply_bm25_extra_filter(base)
    return base


def get_or_build_bm25(
    index: dict[str, Any],
    stopword_profile: str = "shared",
) -> tuple[Any, list[str]]:
    """Lazy-build and cache a BM25Okapi index over chunk tokens.

    Returns the cached ``(bm25, chunk_ids)`` tuple keyed by
    ``stopword_profile`` (issue #150). The ``shared`` profile uses the
    common tokens cached on each chunk; the ``bm25_extra`` profile
    applies :func:`_apply_bm25_extra_filter` (strips the BM25-only
    extension particle set and drops short BM25-only stopwords) before
    constructing BM25Okapi. Each profile gets its own ``BM25Okapi``
    instance inside ``index["_bm25_by_profile"]`` so the IDF
    distribution stays consistent between corpus build and query side.

    For back-compat the ``shared`` build is mirrored at
    ``index["_bm25"]`` / ``index["_bm25_chunk_ids"]`` so any external
    code that inspected those keys keeps working.

    Raises RuntimeError if the optional ``rank_bm25`` dependency is
    missing — the caller must gate on ``retrieval_backend == "hybrid"``.
    """
    if _BM25Okapi is None:
        raise RuntimeError(
            "retrieval_backend='hybrid' requires the 'rank_bm25' package "
            "(install via requirements.txt)."
        )
    if stopword_profile not in VALID_BM25_STOPWORD_PROFILES:
        choices = ", ".join(sorted(VALID_BM25_STOPWORD_PROFILES))
        raise ValueError(f"bm25_stopword_profile must be one of: {choices}")
    profile_cache = index.setdefault("_bm25_by_profile", {})
    entry = profile_cache.get(stopword_profile)
    if isinstance(entry, tuple) and len(entry) == 2:
        return entry  # type: ignore[return-value]
    chunks = index.get("chunks") or []
    corpus = [_chunk_tokens_for_bm25(c, stopword_profile) for c in chunks]
    # rank_bm25 requires at least one non-empty document. If the corpus
    # is entirely empty (degenerate test fixture) substitute a single
    # placeholder token so BM25Okapi doesn't divide by zero.
    if not any(corpus):
        corpus = [["__empty__"] for _ in chunks] or [["__empty__"]]
    bm25 = _BM25Okapi(corpus)
    chunk_ids = [str(c.get("chunk_id")) for c in chunks]
    profile_cache[stopword_profile] = (bm25, chunk_ids)
    if stopword_profile == "shared":
        # Back-compat: legacy callers may still inspect ``_bm25`` /
        # ``_bm25_chunk_ids``. Mirror the shared-profile entry there
        # without exposing the per-profile dict to them.
        index["_bm25"] = bm25
        index["_bm25_chunk_ids"] = chunk_ids
    return bm25, chunk_ids


def bm25_scores_for_index(
    index: dict[str, Any],
    query_tokens: list[str],
    stopword_profile: str = "shared",
) -> dict[str, float]:
    """Return a ``chunk_id -> bm25_score`` map across all chunks in the
    index for the given ``stopword_profile``. Callers filter to their
    candidate slice. Empty query tokens (or tokens that the
    ``bm25_extra`` filter strips to empty) yield an all-zero map.
    """
    chunks = index.get("chunks") or []
    if not query_tokens:
        return {str(c.get("chunk_id")): 0.0 for c in chunks}
    effective_tokens = list(query_tokens)
    if stopword_profile == "bm25_extra":
        effective_tokens = _apply_bm25_extra_filter(effective_tokens)
        if not effective_tokens:
            return {str(c.get("chunk_id")): 0.0 for c in chunks}
    bm25, chunk_ids = get_or_build_bm25(index, stopword_profile)
    raw = bm25.get_scores(effective_tokens)
    return {chunk_id: float(score) for chunk_id, score in zip(chunk_ids, raw)}


def lexical_similarity(query_tokens: set[str], topics: list[str], chunk: dict[str, Any]) -> float:
    # Late-import tokenize (rag_core) — also used as a fallback when
    # the chunk does not carry pre-computed tokens. Same rationale as
    # ``_chunk_tokens_for_bm25``: tokenize is multi-surface in rag_core.
    from rag_core import tokenize

    if not query_tokens and not topics:
        return 0.0
    section_path = chunk.get("section_path") or [chunk.get("section", "")]
    chunk_text = " ".join(
        [
            chunk.get("title", ""),
            chunk.get("agency", ""),
            chunk.get("project", ""),
            " > ".join(section_path),
            chunk.get("text", ""),
        ]
    ).lower()
    chunk_tokens = set(chunk.get("tokens") or tokenize(chunk_text))
    overlap = len(query_tokens & chunk_tokens) / max(1, len(query_tokens))
    topic_hits = sum(1 for topic in topics if topic.lower() in chunk_text)
    topic_score = topic_hits / max(1, len(topics))
    return min(1.0, (0.55 * overlap) + (0.45 * topic_score))


def metadata_similarity(analysis: dict[str, Any], chunk: dict[str, Any]) -> float:
    doc_scores = analysis.get("metadata_doc_scores") or {}
    doc_id = chunk.get("doc_id")
    if doc_id in doc_scores:
        return float(doc_scores[doc_id])
    entities = analysis.get("entities") or []
    if not entities:
        return 0.0
    return 1.0 if chunk.get("agency") in entities else 0.0
