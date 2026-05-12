"""Claim ↔ citation alignment scorer with NFC-normalized token matching."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from rag_core import rate

from eval.scorers._shared import answer_claims, contains_all_terms


ALIGN_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]+")
ALIGN_STOPWORDS = {
    "기관",
    "핵심",
    "요구사항",
    "요구",
    "차이",
    "비교",
    "관련",
    "확인",
    "대상",
    "한다",
    "있다",
    "이다",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "와",
    "과",
}


def normalized_alignment_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"[^0-9a-z가-힣]+", "", normalized)


def alignment_tokens(text: str) -> list[str]:
    tokens = []
    for match in ALIGN_TOKEN_RE.finditer(unicodedata.normalize("NFC", text).lower()):
        token = match.group(0)
        if len(token) <= 1 or token in ALIGN_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def evidence_alignment_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("title", ""),
        item.get("agency", ""),
        item.get("project", ""),
        item.get("section", ""),
        item.get("text", ""),
    ]
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        for key, value in sorted(metadata.items()):
            if value is None or value == "":
                continue
            parts.append(str(key))
            parts.append(str(value))
    return " ".join(str(part) for part in parts if str(part).strip())


def claim_text_supported_by_citation(claim: dict[str, Any], citation_text: str) -> bool:
    claim_text = " ".join(
        str(claim.get(key) or "") for key in ("claim", "support") if claim.get(key)
    )
    if not claim_text.strip() or not citation_text.strip():
        return False

    compact_claim = normalized_alignment_text(str(claim.get("claim") or ""))
    compact_citation = normalized_alignment_text(citation_text)
    if compact_claim and compact_claim in compact_citation:
        return True

    tokens = alignment_tokens(str(claim.get("claim") or ""))
    if not tokens:
        return bool(compact_claim and compact_claim in compact_citation)
    citation_tokens = set(alignment_tokens(citation_text))
    overlap = sum(1 for token in tokens if token in citation_tokens)
    return (overlap / max(1, len(tokens))) >= 0.5


def expected_claim_specs_for_target(
    case: dict[str, Any],
    target: str,
) -> list[dict[str, Any]]:
    specs = case.get("expected_claim_citations") or []
    matched = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        expected_target = str(spec.get("target") or "").strip()
        if not expected_target or expected_target == target:
            matched.append(spec)
    return matched


def score_claim_citation_alignment(
    case: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    evidence_by_chunk = {
        str(item.get("chunk_id")): item
        for item in prediction.get("evidence") or []
        if item.get("chunk_id")
    }
    claims = answer_claims(prediction)
    expected_specs = [
        spec for spec in case.get("expected_claim_citations") or [] if isinstance(spec, dict)
    ]
    errors: list[dict[str, Any]] = []
    scores: list[float] = []
    claim_targets = {str(claim.get("target") or "") for claim in claims}

    for claim_index, claim in enumerate(claims):
        target = str(claim.get("target") or "")
        citations = [citation for citation in claim.get("citations") or [] if isinstance(citation, dict)]
        if not citations:
            scores.append(0.0)
            errors.append(
                {
                    "code": "claim_missing_citation",
                    "message": "Claim has no citation.",
                    "claim_index": claim_index,
                    "target": target,
                }
            )
            continue

        citation_items = []
        missing_chunk_ids = []
        for citation in citations:
            chunk_id = str(citation.get("chunk_id") or "")
            item = evidence_by_chunk.get(chunk_id)
            if item is None:
                missing_chunk_ids.append(chunk_id)
                continue
            citation_items.append(item)
        citation_text = " ".join(evidence_alignment_text(item) for item in citation_items)
        citation_doc_ids = {str(item.get("doc_id") or "") for item in citation_items}

        claim_errors: list[dict[str, Any]] = []
        if missing_chunk_ids and not citation_items:
            claim_errors.append(
                {
                    "code": "citation_not_in_evidence",
                    "message": "Claim citation chunk was not present in top-level evidence.",
                    "claim_index": claim_index,
                    "target": target,
                    "chunk_ids": missing_chunk_ids,
                }
            )
        elif not claim_text_supported_by_citation(claim, citation_text):
            claim_errors.append(
                {
                    "code": "claim_text_not_supported_by_citation",
                    "message": "Claim text was not directly supported by the cited evidence text.",
                    "claim_index": claim_index,
                    "target": target,
                    "citation_chunk_ids": [item.get("chunk_id") for item in citation_items],
                }
            )

        for spec in expected_claim_specs_for_target(case, target):
            expected_doc_ids = {str(doc_id) for doc_id in spec.get("expected_doc_ids") or []}
            expected_terms = [str(term) for term in spec.get("expected_terms") or []]
            if expected_doc_ids and not (expected_doc_ids & citation_doc_ids):
                claim_errors.append(
                    {
                        "code": "expected_claim_doc_mismatch",
                        "message": "Claim citation doc_id did not match the expected claim-level doc.",
                        "claim_index": claim_index,
                        "target": target,
                        "expected_doc_ids": sorted(expected_doc_ids),
                        "actual_doc_ids": sorted(doc_id for doc_id in citation_doc_ids if doc_id),
                    }
                )
            if expected_terms and not contains_all_terms(citation_text, expected_terms):
                claim_errors.append(
                    {
                        "code": "expected_claim_terms_missing",
                        "message": "Claim citation text missed expected claim-level terms.",
                        "claim_index": claim_index,
                        "target": target,
                        "expected_terms": expected_terms,
                    }
                )

        errors.extend(claim_errors)
        scores.append(0.0 if claim_errors else 1.0)

    for spec in expected_specs:
        expected_target = str(spec.get("target") or "").strip()
        if expected_target and expected_target not in claim_targets:
            scores.append(0.0)
            errors.append(
                {
                    "code": "expected_claim_missing",
                    "message": "Expected claim target was not emitted.",
                    "target": expected_target,
                }
            )

    return {
        "claim_citation_alignment": rate(scores) if scores else None,
        "claim_citation_aligned": sum(1 for score in scores if score >= 1.0),
        "claim_citation_checked": len(scores),
        "claim_citation_errors": errors,
    }
