"""Deterministic metrics for the naive RAG evaluation contract."""
from __future__ import annotations

import math
from typing import Any


RETRIEVAL_METRIC_KEYS = ("recall_at_5", "recall_at_10", "mrr_at_5", "ndcg_at_5")
ANSWER_METRIC_KEYS = (
    "faithfulness",
    "answer_relevancy",
    "citation_accuracy",
    "hallucination_flag",
    "unanswerable_detection_flag",
)
BENCHMARK_CITATION_PAGE_METRIC_KEYS = (
    "citation_chunk_accuracy",
    "citation_page_coverage",
    "citation_page_precision",
    "missing_page_number_rate",
    "page_metadata_coverage",
)
RULE_BASED_ANSWER_METRIC_KEYS = (
    "rule_based_groundedness",
    "term_coverage_accuracy",
    "failed_abstention_rate",
    "unsafe_answer_rate",
    "rule_based_hallucination_rate",
)
BENCHMARK_LATENCY_METRIC_KEYS = (
    "warm_query_latency_ms",
    "retrieval_latency_ms",
    "generation_latency_ms",
)


def unique_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float | None:
    gold_ids = unique_ids(gold)
    if not gold_ids:
        return None
    retrieved_head = set(unique_ids(retrieved)[:k])
    return sum(1 for chunk_id in gold_ids if chunk_id in retrieved_head) / len(gold_ids)


def mrr_at_k(retrieved: list[str], gold: list[str], k: int) -> float | None:
    gold_ids = set(unique_ids(gold))
    if not gold_ids:
        return None
    for rank, chunk_id in enumerate(unique_ids(retrieved)[:k], start=1):
        if chunk_id in gold_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: list[str], gold: list[str], k: int) -> float | None:
    gold_ids = set(unique_ids(gold))
    if not gold_ids:
        return None
    dcg = 0.0
    for rank, chunk_id in enumerate(unique_ids(retrieved)[:k], start=1):
        if chunk_id in gold_ids:
            dcg += 1.0 / math.log2(rank + 1)
    ideal_hits = min(len(gold_ids), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def retrieval_metrics(retrieved: list[str], gold: list[str]) -> dict[str, float | None]:
    return {
        "recall_at_5": recall_at_k(retrieved, gold, 5),
        "recall_at_10": recall_at_k(retrieved, gold, 10),
        "mrr_at_5": mrr_at_k(retrieved, gold, 5),
        "ndcg_at_5": ndcg_at_k(retrieved, gold, 5),
    }


def contains_terms(text: str, terms: list[str]) -> float | None:
    cleaned = [str(term).strip().lower() for term in terms if str(term).strip()]
    if not cleaned:
        return None
    lowered = text.lower()
    return sum(1 for term in cleaned if term in lowered) / len(cleaned)


def summarize_metric(values: list[float | int | None], total: int) -> dict[str, Any]:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    return {
        "mean": (sum(numeric) / len(numeric)) if numeric else None,
        "n": len(numeric),
        "missing": max(total - len(numeric), 0),
    }


def summarize_case_metrics(
    case_metrics: list[dict[str, Any]],
    keys: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    total = len(case_metrics)
    return {
        key: summarize_metric([metrics.get(key) for metrics in case_metrics], total)
        for key in keys
    }


def summarize_latency(values: list[float | int | None]) -> dict[str, Any]:
    numeric = sorted(float(value) for value in values if isinstance(value, (int, float)))
    if not numeric:
        return {"mean": None, "p50": None, "p95": None, "n": 0, "missing": len(values)}
    p50_idx = min(int(0.50 * (len(numeric) - 1)), len(numeric) - 1)
    p95_idx = min(int(0.95 * (len(numeric) - 1)), len(numeric) - 1)
    return {
        "mean": sum(numeric) / len(numeric),
        "p50": numeric[p50_idx],
        "p95": numeric[p95_idx],
        "n": len(numeric),
        "missing": max(len(values) - len(numeric), 0),
    }
