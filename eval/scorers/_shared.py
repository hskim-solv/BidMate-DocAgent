"""Shared helpers used by both per-case scorers and run-level orchestration.

Kept in a leaf module with no intra-package imports so ``eval/run_eval.py``
and any of the ``eval/scorers/*.py`` submodules can import from it without
triggering a circular dependency through ``eval/scorers/__init__.py``.
"""
from __future__ import annotations

from typing import Any


QUERY_TYPE_ALIASES = {"multi_doc": "comparison"}


def hardcase_categories(item: dict[str, Any]) -> list[str]:
    categories = item.get("hardcase_categories") or item.get("hardcase_category") or []
    if isinstance(categories, str):
        categories = [categories]
    if not isinstance(categories, list):
        return []
    normalized = []
    seen: set[str] = set()
    for category in categories:
        value = str(category).strip()
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def canonical_query_type(query_type: Any) -> str:
    value = str(query_type or "").strip()
    return QUERY_TYPE_ALIASES.get(value, value)


def contains_all_terms(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return all(str(term).lower() in lowered for term in terms)


def retry_trigger_reasons(prediction: dict[str, Any]) -> list[str]:
    diagnostics = prediction.get("diagnostics") or {}
    reasons: list[str] = []
    for attempt in diagnostics.get("filter_stage_attempts") or []:
        if attempt.get("verified"):
            continue
        reasons.extend(str(reason) for reason in attempt.get("verification_reasons") or [])
    return reasons


def answer_payload(prediction: dict[str, Any]) -> dict[str, Any]:
    answer = prediction.get("answer")
    return answer if isinstance(answer, dict) else {}


def answer_claims(prediction: dict[str, Any]) -> list[dict[str, Any]]:
    claims = answer_payload(prediction).get("claims") or []
    return [claim for claim in claims if isinstance(claim, dict)]


def answer_to_text(prediction: dict[str, Any]) -> str:
    payload = answer_payload(prediction)
    if not payload:
        return str(prediction.get("answer") or "")
    parts = [
        str(payload.get("summary") or ""),
        str(prediction.get("answer_text") or ""),
    ]
    for claim in answer_claims(prediction):
        parts.extend([str(claim.get("claim") or ""), str(claim.get("support") or "")])
    insufficiency = payload.get("insufficiency")
    if isinstance(insufficiency, dict):
        parts.append(str(insufficiency.get("message") or ""))
    return " ".join(part for part in parts if part)


def answer_status(prediction: dict[str, Any]) -> str:
    payload = answer_payload(prediction)
    diagnostics = prediction.get("diagnostics") or {}
    return str(payload.get("status") or diagnostics.get("answer_status") or "")


def answer_citations(prediction: dict[str, Any]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for claim in answer_claims(prediction):
        for citation in claim.get("citations") or []:
            if isinstance(citation, dict):
                citations.append(citation)
    return citations
