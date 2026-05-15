"""Per-case orchestrator combining citation / alignment / format / chunk scorers."""
from __future__ import annotations

from typing import Any

from eval.scorers._shared import (
    answer_to_text,
    canonical_query_type,
    contains_all_terms,
    hardcase_categories,
    retry_trigger_reasons,
)
from eval.scorers.alignment import score_claim_citation_alignment
from eval.scorers.chunk_metrics import (
    CHUNK_METRIC_KS,
    chunk_mrr,
    chunk_ndcg_at_k,
    chunk_recall_at_k,
)
from eval.scorers.citation import score_citation_grounding
from eval.scorers.format import score_answer_format


def score_case(
    case: dict[str, Any],
    prediction: dict[str, Any],
    answer_policy: dict[str, Any] | None = None,
    *,
    gold_chunk_ids: list[str] | None = None,
) -> dict[str, Any]:
    answerable = bool(case.get("answerable", True))
    query_type = canonical_query_type(case.get("query_type"))
    expected_doc_ids = set(case.get("expected_doc_ids") or [])
    expected_terms = [str(term) for term in case.get("expected_terms") or []]
    expected_citation_terms = [
        str(term) for term in case.get("expected_citation_terms") or expected_terms
    ]
    evidence = prediction.get("evidence") or []
    evidence_doc_ids = {item.get("doc_id") for item in evidence}
    answer = answer_to_text(prediction)
    evidence_text = " ".join(str(item.get("text") or "") for item in evidence)
    combined_text = " ".join([answer, evidence_text])
    diagnostics = prediction.get("diagnostics") or {}
    plan = prediction.get("plan") or {}
    analysis = prediction.get("analysis") or {}
    context_resolution = diagnostics.get("context_resolution") or {}
    metadata_resolution = diagnostics.get("metadata_resolution") or {}
    ambiguity = metadata_resolution.get("ambiguity") or {}
    abstained = bool(diagnostics.get("abstained"))
    answer_format = score_answer_format(case, prediction, answer_policy)
    citation_grounding = score_citation_grounding(case, prediction)
    claim_alignment = score_claim_citation_alignment(case, prediction)

    citation_doc_precision = 0.0
    if evidence_doc_ids:
        citation_doc_precision = len(evidence_doc_ids & expected_doc_ids) / len(evidence_doc_ids)
    citation_term_match = (
        contains_all_terms(evidence_text, expected_citation_terms)
        if expected_citation_terms
        else bool(evidence)
    )

    comparison_target_recall: float | None = None
    comparison_pool_recall: float | None = None
    if query_type == "comparison" and len(expected_doc_ids) >= 2:
        covered = expected_doc_ids & evidence_doc_ids
        comparison_target_recall = len(covered) / len(expected_doc_ids)
        coverage_after = (
            ((prediction.get("plan") or {}).get("comparison_coverage") or {}).get("after") or {}
        )
        pool_doc_ids = {doc_id for doc_id, count in coverage_after.items() if count > 0}
        if pool_doc_ids:
            comparison_pool_recall = (
                len(expected_doc_ids & pool_doc_ids) / len(expected_doc_ids)
            )

    if answerable:
        doc_match = expected_doc_ids.issubset(evidence_doc_ids)
        term_match = contains_all_terms(combined_text, expected_terms)
        accuracy = 1.0 if doc_match and term_match and not abstained else 0.0
        groundedness = 1.0 if term_match and evidence and not abstained else 0.0
        citation_precision = citation_doc_precision if citation_term_match else 0.0
        abstention = None
    else:
        doc_match = not evidence
        term_match = abstained
        accuracy = None
        groundedness = 1.0 if abstained and not evidence else 0.0
        citation_precision = 1.0 if abstained and not evidence else 0.0
        abstention = 1.0 if abstained else 0.0

    retrieved_chunk_ids = [
        str(chunk_id)
        for chunk_id in diagnostics.get("retrieved_chunk_ids") or []
        if chunk_id
    ]
    gold_for_chunks = [str(item) for item in gold_chunk_ids or [] if item]
    chunk_metrics: dict[str, float | None] = {
        f"chunk_recall_at_{k}": chunk_recall_at_k(retrieved_chunk_ids, gold_for_chunks, k)
        for k in CHUNK_METRIC_KS
    }
    chunk_metrics["chunk_mrr"] = chunk_mrr(retrieved_chunk_ids, gold_for_chunks)
    chunk_metrics["chunk_ndcg_at_10"] = chunk_ndcg_at_k(retrieved_chunk_ids, gold_for_chunks, 10)
    chunk_metrics["chunk_ndcg_at_20"] = chunk_ndcg_at_k(retrieved_chunk_ids, gold_for_chunks, 20)

    # Rerank delta (issue #767): isolated cross-encoder contribution on top of
    # the 60/25/15 dense+lexical+metadata blend. Both keys are None when the
    # rerank stage didn't run (e.g., rerank disabled in naive_baseline, or the
    # reranker fell back silently). Forward-compat: pre-#767 prediction dicts
    # have no `pre_rerank_top10` / `post_rerank_top10` keys → values stay None.
    rerank_meta = plan.get("rerank_cross_encoder_meta") or {}
    pre_top10 = [str(c) for c in rerank_meta.get("pre_rerank_top10") or [] if c]
    post_top10 = [str(c) for c in rerank_meta.get("post_rerank_top10") or [] if c]
    if pre_top10 and post_top10 and gold_for_chunks:
        pre_mrr = chunk_mrr(pre_top10, gold_for_chunks)
        post_mrr = chunk_mrr(post_top10, gold_for_chunks)
        pre_ndcg = chunk_ndcg_at_k(pre_top10, gold_for_chunks, 10)
        post_ndcg = chunk_ndcg_at_k(post_top10, gold_for_chunks, 10)
        chunk_metrics["rerank_delta_mrr"] = (
            (post_mrr - pre_mrr) if pre_mrr is not None and post_mrr is not None else None
        )
        chunk_metrics["rerank_delta_ndcg_at_10"] = (
            (post_ndcg - pre_ndcg) if pre_ndcg is not None and post_ndcg is not None else None
        )
    else:
        chunk_metrics["rerank_delta_mrr"] = None
        chunk_metrics["rerank_delta_ndcg_at_10"] = None

    return {
        "id": case.get("id"),
        "query_type": query_type,
        "slice": query_type,
        "hardcase_categories": hardcase_categories(case),
        "query": case.get("query"),
        "answerable": answerable,
        "expected_doc_ids": sorted(expected_doc_ids),
        "evidence_doc_ids": sorted(doc_id for doc_id in evidence_doc_ids if doc_id),
        "gold_chunk_ids": gold_for_chunks,
        "retrieved_chunk_ids": retrieved_chunk_ids,
        **chunk_metrics,
        "doc_match": doc_match,
        "term_match": term_match,
        "citation_term_match": citation_term_match,
        "citation_doc_precision": citation_doc_precision,
        "accuracy": accuracy,
        "groundedness": groundedness,
        "citation_precision": citation_precision,
        **citation_grounding,
        **claim_alignment,
        "abstention": abstention,
        "comparison_target_recall": comparison_target_recall,
        "comparison_pool_recall": comparison_pool_recall,
        "latency_ms": diagnostics.get("latency_ms"),
        "retry_count": diagnostics.get("retry_count", 0),
        "retry_trigger_reasons": retry_trigger_reasons(prediction),
        "last_attempt_verified": (
            bool((diagnostics.get("filter_stage_attempts") or [])[-1].get("verified"))
            if (diagnostics.get("filter_stage_attempts") or [])
            else None
        ),
        "filter_stage": plan.get("filter_stage"),
        "selected_top_k": diagnostics.get("selected_top_k"),
        "retrieval_budget": dict(plan.get("retrieval_budget") or {}),
        "metadata_ambiguous": bool(analysis.get("metadata_ambiguous")),
        "ambiguity_decision": ambiguity.get("decision"),
        "ambiguity_reason": ambiguity.get("decision_reason") or ambiguity.get("reason"),
        "metadata_candidate_count": metadata_resolution.get("candidate_count"),
        "metadata_selected_doc_ids": metadata_resolution.get("selected_doc_ids") or [],
        "cold_start": bool(diagnostics.get("cold_start", False)),
        "stage_latency": dict(diagnostics.get("stage_latency") or {}),
        "attempt_latency": [
            {
                "stage": attempt.get("stage"),
                "retrieve_ms": attempt.get("retrieve_ms", 0.0),
                "verify_ms": attempt.get("verify_ms", 0.0),
            }
            for attempt in diagnostics.get("filter_stage_attempts") or []
        ],
        "context_resolution_status": context_resolution.get("status"),
        "context_resolution_source": context_resolution.get("source"),
        "context_resolution_confidence": context_resolution.get("confidence"),
        "context_resolution_reason": context_resolution.get("reason"),
        "resolved_query": prediction.get("resolved_query"),
        "abstained": abstained,
        **answer_format,
        "answer": answer,
        "evidence": [
            {
                "text": str(item.get("text") or "")[:600],
                "doc_id": item.get("doc_id"),
                "chunk_id": item.get("chunk_id"),
                "page": item.get("page"),
            }
            for item in (prediction.get("evidence") or [])[:3]
        ],
    }
