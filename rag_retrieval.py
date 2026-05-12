"""Post-retrieval fusion, comparison balance, and hierarchical reassembly.

Extracted from ``rag_core.py`` (PR-H1a, issue #459) as the first slice of the
``retrieve_candidates`` → ``apply_fusion_and_reranking`` boundary
decomposition that the PR-E series has been driving. The module owns the
*post-candidate-scoring* path: it takes the pre-fusion list emitted by
``rag_core.retrieve_candidates`` and returns the final ranked evidence
that the verifier consumes.

Public functions:

- :func:`apply_fusion_and_reranking` — RRF fusion (`hybrid` 2-way,
  `m3` 3-way), optional cross-encoder rerank dispatch (via
  ``rag_reranker.default_reranker``), then either hierarchical
  reassembly or comparison-balanced top-k.
- :func:`apply_comparison_balance` — coverage-aware top-k that
  guarantees ``min_per_target`` items per comparison target before
  filling by global score. No-op for non-comparison queries.
- :func:`reassemble_parent_sections` — hierarchical mode that promotes
  the best child chunk per parent section into a single result.

Internal helper :func:`_coverage_counts` is module-private (leading
underscore preserved from the rag_core layout).

Circular-import avoidance: ``comparison_targets_for_analysis``,
``normalize_regions``, and ``normalize_page_span`` are late-imported
from ``rag_core`` inside the functions that use them. These helpers
are used in many rag_core call sites (not retrieval-specific) so they
stay in rag_core; the late-import idiom keeps this module a true leaf
of the dependency graph.

JSON-identity guarantee: the four functions are moved without behavior
change. ``tests/test_naive_baseline_ranking_invariance.py`` and
``tests/test_retrieval_loop_regression.py`` are the regression gates.
"""

from __future__ import annotations

from typing import Any

from rag_pipeline_presets import RRF_K


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
