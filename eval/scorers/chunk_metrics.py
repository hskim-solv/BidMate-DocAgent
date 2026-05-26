"""Chunk-level retrieval metrics: recall@k, MRR@k, nDCG@k.

The ``context_*`` helpers are deterministic, gold-chunk based retrieval
metrics. They are intentionally separate from the opt-in RAGAS judge metrics
that live under ``judge_ragas``.
"""
from __future__ import annotations

import math
from typing import Any


CHUNK_METRIC_KS = (5, 10, 20)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _normalize_page_span(value: Any) -> list[int] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    try:
        return [int(value[0]), int(value[1])]
    except (TypeError, ValueError):
        return None


def _chunk_lookup(index: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        str(chunk.get("chunk_id") or ""): chunk
        for chunk in ((index or {}).get("chunks") or [])
        if chunk.get("chunk_id")
    }


def _gold_row_from_chunk(
    chunk: dict[str, Any] | None,
    *,
    chunk_id: str,
    required_terms: list[str] | None = None,
    support_claim: str = "",
) -> dict[str, Any]:
    chunk = chunk or {}
    return {
        "doc_id": str(chunk.get("doc_id") or ""),
        "chunk_id": chunk_id,
        "page_span": _normalize_page_span(chunk.get("page_span")),
        "required_terms": list(required_terms or []),
        "support_claim": support_claim,
    }


def _derive_gold_ids_from_expected(
    case: dict[str, Any],
    index: dict[str, Any] | None,
) -> list[str]:
    expected_doc_ids = set(case.get("expected_doc_ids") or [])
    expected_terms = [str(term) for term in case.get("expected_terms") or [] if term]
    if not expected_doc_ids or not expected_terms or not index:
        return []
    gold: list[str] = []
    for chunk in index.get("chunks") or []:
        if chunk.get("doc_id") not in expected_doc_ids:
            continue
        text = str(chunk.get("text") or "")
        if any(term in text for term in expected_terms):
            chunk_id = str(chunk.get("chunk_id") or "")
            if chunk_id:
                gold.append(chunk_id)
    return _unique(gold)


def derive_gold_evidence(
    case: dict[str, Any],
    index: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Normalize explicit or derived gold evidence labels.

    Preferred explicit shape:
    ``{doc_id, chunk_id, page_span, required_terms, support_claim}``.
    When ``gold_evidence`` is present it wins over legacy fallbacks. Entries
    without ``chunk_id`` can still resolve to chunks through ``doc_id`` +
    ``required_terms`` when an index is available.
    """
    by_id = _chunk_lookup(index)
    explicit = case.get("gold_evidence")
    if isinstance(explicit, list) and explicit:
        rows: list[dict[str, Any]] = []
        for item in explicit:
            if not isinstance(item, dict):
                continue
            doc_id = str(item.get("doc_id") or "")
            chunk_id = str(item.get("chunk_id") or "")
            required_terms = [
                str(term) for term in item.get("required_terms") or [] if term
            ]
            support_claim = str(item.get("support_claim") or "")
            page_span = _normalize_page_span(item.get("page_span"))
            if chunk_id:
                chunk = by_id.get(chunk_id)
                rows.append(
                    {
                        "doc_id": doc_id or str((chunk or {}).get("doc_id") or ""),
                        "chunk_id": chunk_id,
                        "page_span": page_span or _normalize_page_span((chunk or {}).get("page_span")),
                        "required_terms": required_terms,
                        "support_claim": support_claim,
                    }
                )
                continue
            if doc_id and required_terms and index:
                for chunk in index.get("chunks") or []:
                    if str(chunk.get("doc_id") or "") != doc_id:
                        continue
                    text = str(chunk.get("text") or "")
                    if any(term in text for term in required_terms):
                        resolved_chunk_id = str(chunk.get("chunk_id") or "")
                        if resolved_chunk_id:
                            rows.append(
                                {
                                    "doc_id": doc_id,
                                    "chunk_id": resolved_chunk_id,
                                    "page_span": page_span or _normalize_page_span(chunk.get("page_span")),
                                    "required_terms": required_terms,
                                    "support_claim": support_claim,
                                }
                            )
                continue
            if doc_id or page_span or required_terms or support_claim:
                rows.append(
                    {
                        "doc_id": doc_id,
                        "chunk_id": "",
                        "page_span": page_span,
                        "required_terms": required_terms,
                        "support_claim": support_claim,
                    }
                )
        return rows

    explicit_ids = [str(item) for item in case.get("gold_chunk_ids") or [] if item]
    if explicit_ids:
        return [
            _gold_row_from_chunk(by_id.get(chunk_id), chunk_id=chunk_id)
            for chunk_id in _unique(explicit_ids)
        ]

    derived_ids = _derive_gold_ids_from_expected(case, index)
    required_terms = [str(term) for term in case.get("expected_terms") or [] if term]
    return [
        _gold_row_from_chunk(
            by_id.get(chunk_id),
            chunk_id=chunk_id,
            required_terms=required_terms,
        )
        for chunk_id in derived_ids
    ]


def derive_gold_chunk_ids(
    case: dict[str, Any],
    index: dict[str, Any] | None,
) -> list[str]:
    """Derive a chunk-level gold set.

    Priority: explicit ``gold_evidence`` → legacy ``gold_chunk_ids`` →
    ``expected_doc_ids`` + ``expected_terms`` fallback.
    """
    return _unique(
        [
            str(item.get("chunk_id") or "")
            for item in derive_gold_evidence(case, index)
            if isinstance(item, dict) and item.get("chunk_id")
        ]
    )


def chunk_recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float | None:
    if not gold:
        return None
    if not retrieved or k <= 0:
        return 0.0
    head = retrieved[:k]
    hits = sum(1 for chunk_id in gold if chunk_id in head)
    return hits / len(gold)


def context_precision_at_k(retrieved: list[str], gold: list[str], k: int) -> float | None:
    if not gold:
        return None
    if not retrieved or k <= 0:
        return 0.0
    gold_set = set(gold)
    head = _unique(retrieved[:k])
    if not head:
        return 0.0
    hits = sum(1 for chunk_id in head if chunk_id in gold_set)
    return hits / len(head)


def context_recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float | None:
    return chunk_recall_at_k(retrieved, gold, k)


def chunk_mrr_at_k(retrieved: list[str], gold: list[str], k: int) -> float | None:
    if not gold:
        return None
    if not retrieved or k <= 0:
        return 0.0
    gold_set = set(gold)
    for rank, chunk_id in enumerate(retrieved[:k], start=1):
        if chunk_id in gold_set:
            return 1.0 / rank
    return 0.0


def chunk_mrr(retrieved: list[str], gold: list[str]) -> float | None:
    return chunk_mrr_at_k(retrieved, gold, len(retrieved))


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
