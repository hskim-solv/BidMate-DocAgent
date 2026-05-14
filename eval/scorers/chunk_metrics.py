"""Chunk-level retrieval metrics: recall@k, MRR, nDCG@k."""
from __future__ import annotations

import math
from typing import Any


CHUNK_METRIC_KS = (5, 10, 20)


def derive_gold_chunk_ids(
    case: dict[str, Any],
    index: dict[str, Any] | None,
) -> list[str]:
    """Derive a chunk-level gold set from ``expected_doc_ids`` + ``expected_terms``.

    A chunk is gold if its ``doc_id`` is in the case's ``expected_doc_ids`` AND
    its text contains at least one ``expected_term``. If the case provides an
    explicit ``gold_chunk_ids`` list it is used verbatim. Returns an empty list
    for cases without expectations (e.g. abstention).
    """
    explicit = case.get("gold_chunk_ids")
    if explicit:
        return [str(item) for item in explicit if item]
    expected_doc_ids = set(case.get("expected_doc_ids") or [])
    expected_terms = [str(term) for term in case.get("expected_terms") or [] if term]
    if not expected_doc_ids or not expected_terms or not index:
        return []
    chunks = index.get("chunks") or []
    gold: list[str] = []
    for chunk in chunks:
        if chunk.get("doc_id") not in expected_doc_ids:
            continue
        text = str(chunk.get("text") or "")
        if any(term in text for term in expected_terms):
            chunk_id = str(chunk.get("chunk_id") or "")
            if chunk_id:
                gold.append(chunk_id)
    return gold


def chunk_recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float | None:
    if not gold:
        return None
    if not retrieved or k <= 0:
        return 0.0
    head = retrieved[:k]
    hits = sum(1 for chunk_id in gold if chunk_id in head)
    return hits / len(gold)


def chunk_mrr(retrieved: list[str], gold: list[str]) -> float | None:
    if not gold:
        return None
    if not retrieved:
        return 0.0
    gold_set = set(gold)
    for rank, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in gold_set:
            return 1.0 / rank
    return 0.0


def chunk_ndcg_at_k(retrieved: list[str], gold: list[str], k: int) -> float | None:
    if not gold:
        return None
    if not retrieved or k <= 0:
        return 0.0
    gold_set = set(gold)
    dcg = 0.0
    for rank, chunk_id in enumerate(retrieved[:k], start=1):
        rel = 1.0 if chunk_id in gold_set else 0.0
        if rel:
            dcg += rel / math.log2(rank + 1)
    ideal_hits = min(len(gold_set), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return (dcg / idcg) if idcg else 0.0
