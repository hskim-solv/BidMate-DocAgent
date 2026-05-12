"""Answer-format compliance scorer — schema, status, claim structure checks."""
from __future__ import annotations

from typing import Any

from eval.scorers._shared import answer_claims, answer_payload, answer_status


def score_answer_format(
    case: dict[str, Any],
    prediction: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or {}
    answerable = bool(case.get("answerable", True))
    expected_status = case.get("expected_answer_status")
    if expected_status is None:
        expected_status = (
            policy.get("answerable_status", "supported")
            if answerable
            else policy.get("unanswerable_status", "insufficient")
        )
    min_claims = case.get("min_claims")
    if min_claims is None:
        min_claims = int(
            policy.get("min_claims_answerable", 1)
            if answerable
            else policy.get("min_claims_unanswerable", 0)
        )
    require_claim_citations = bool(
        case.get("require_claim_citations", policy.get("require_claim_citations", True))
    )
    expected_targets = {str(target) for target in case.get("expected_claim_targets") or []}
    expected_missing_targets = {
        str(target) for target in case.get("expected_missing_targets") or []
    }

    payload = answer_payload(prediction)
    claims = answer_claims(prediction)
    claim_targets = {str(claim.get("target") or "") for claim in claims}
    citation_checks = []
    for claim in claims:
        citations = claim.get("citations") or []
        citation_checks.append(
            bool(citations)
            and all(
                isinstance(citation, dict)
                and bool(citation.get("doc_id"))
                and bool(citation.get("chunk_id"))
                for citation in citations
            )
        )
    citations_ok = True
    if require_claim_citations and claims:
        citations_ok = all(citation_checks)
    elif require_claim_citations and int(min_claims) > 0:
        citations_ok = False

    insufficiency = payload.get("insufficiency") if isinstance(payload, dict) else {}
    if not isinstance(insufficiency, dict):
        insufficiency = {}
    missing_targets = {str(target) for target in insufficiency.get("missing_targets") or []}

    checks = {
        "schema_version": int(payload.get("schema_version") or 0) >= 2,
        "status_match": answer_status(prediction) == str(expected_status),
        "min_claims": len(claims) >= int(min_claims),
        "claim_targets": expected_targets.issubset(claim_targets),
        "claim_citations": citations_ok,
    }
    if expected_missing_targets:
        checks["missing_targets"] = expected_missing_targets.issubset(missing_targets)
    return {
        "expected_answer_status": str(expected_status),
        "answer_status": answer_status(prediction),
        "expected_claim_targets": sorted(expected_targets),
        "claim_targets": sorted(target for target in claim_targets if target),
        "expected_missing_targets": sorted(expected_missing_targets),
        "missing_targets": sorted(target for target in missing_targets if target),
        "claim_count": len(claims),
        "format_checks": checks,
        "answer_format_compliance": 1.0 if all(checks.values()) else 0.0,
    }
