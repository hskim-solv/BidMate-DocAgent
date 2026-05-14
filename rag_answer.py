"""Answer generation: claims, citations, status, and rendering.

Extracted from ``rag_core.py`` (PR-J2, issue #468) as the third slice
of the rag_core decomposition (after rag_retrieval and rag_verifier).
Owns the post-verifier path that turns evidence into the
ADR 0003-shaped answer dict.

Public functions:

- :func:`generate_answer` — main entry. Called by the orchestration
  ``_phase_build_answer`` once retrieval + verifier converge. Returns
  ``(answer_dict, answer_text, was_insufficient)``.
- :func:`build_claims` / :func:`build_comparison_claims` /
  :func:`build_extract_claims` — claim shape constructors.
- :func:`make_claim` / :func:`claim_target` / :func:`make_citation` —
  per-claim / per-citation builders.
- :func:`answer_status` / :func:`answer_status_reason` /
  :func:`answer_query_type` / :func:`answer_summary` /
  :func:`answer_verification_reasons` — status surface helpers.
- :func:`build_insufficiency` — abstention payload.
- :func:`render_answer_text` — `answer_text` string the API returns.
- :func:`best_sentence`, :func:`metadata_claim_sentences`,
  :func:`metadata_field_requested`, :func:`format_metadata_claim_value`,
  :func:`sentence_has_verification_topic`,
  :func:`select_supporting_evidence` — claim-body helpers.

ADR 0003 contract preserved: the dict shape stays in this module
(``schema_version: 2`` literal, citation contract). CLAUDE.md
prohibition against parallel pydantic / TypedDict models still holds —
the dict IS the contract, and this module constructs it directly.

Circular-import avoidance: ``rag_core`` symbols used in five spots
(``sentence_split``, ``tokenize``, ``ordered_unique``,
``normalize_regions``, ``normalize_page_span``) are late-imported
inside the functions that need them. They serve many non-answer
surfaces in ``rag_core`` (analysis path, indexing, verifier
internals, ingestion path, parent-section reassembly) so they stay
there.

JSON-identity guarantee: every function moves byte-for-byte. The
ADR 0003 surface is gated by ``tests/test_naive_baseline_ranking_invariance.py``,
``tests/test_retrieval_loop_regression.py``, the answer-contract
regression files, and ``tests/test_langgraph_orchestrator_regression.py``.
"""

from __future__ import annotations

from typing import Any

from korean_lexicon import (
    METADATA_CLAIM_LABELS,
    METADATA_CLAIM_TOPIC_LABELS,
    METADATA_EVIDENCE_LABELS,
)
from rag_metadata_processing import normalize_page_span, normalize_regions
from rag_text_processing import (
    compact_metadata_text,
    ordered_unique,
    sentence_split,
    tokenize,
)
from rag_answer_schema import (
    ANSWER_SCHEMA_VERSION,
    ANSWER_STATUS_INSUFFICIENT,
    ANSWER_STATUS_PARTIAL,
    ANSWER_STATUS_SUPPORTED,
)
from rag_verifier import (
    PARTIAL_TOPIC_GROUNDING_REASON,
    evidence_text_for_verification,
    specific_topics,
    verification_topics,
)

# ─── Evidence pool sizing ──────────────────────────────────────────────────
# Tokens that signal aggregate intent: the user wants an exhaustive
# listing (e.g. "모든 일정과 금액 정리해줘"). Detected in
# ``select_supporting_evidence`` to widen the pool beyond the default
# of 2 so multiple field-bearing chunks can all contribute.
_AGGREGATE_SIGNALS: frozenset[str] = frozenset({
    "모든",    # all
    "전체",    # entire / all
    "모두",    # all / everything
    "목록",    # list
    "나열",    # enumerate
    "정리",    # organize / list all
    "리스트",  # list (loanword)
    "일체",    # all / every
    "전부",    # all / entirety
})

# Pool ceiling for aggregate queries. Covers the typical multi-field
# case where budget + duration + deadline live in separate chunks.
_AGGREGATE_POOL_MAX: int = 5


def generate_answer(
    query: str,
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
    verified: bool,
    verification_reasons: list[str] | None = None,
) -> tuple[dict[str, Any], str, bool]:
    claims = build_claims(analysis, evidence)
    effective_reasons = answer_verification_reasons(analysis, verification_reasons or [])
    status = answer_status(analysis, claims, verified, effective_reasons)
    insufficiency = None
    if status != ANSWER_STATUS_SUPPORTED:
        insufficiency = build_insufficiency(
            query,
            analysis,
            claims,
            verified,
            effective_reasons,
        )

    answer = {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "status": status,
        "status_reason": answer_status_reason(status, verified, effective_reasons),
        "query_type": answer_query_type(analysis, status),
        "summary": answer_summary(query, analysis, claims, status, insufficiency),
        "claims": claims,
        "insufficiency": insufficiency,
    }
    answer_text = render_answer_text(answer)
    return answer, answer_text, status == ANSWER_STATUS_INSUFFICIENT


def answer_verification_reasons(
    analysis: dict[str, Any],
    verification_reasons: list[str],
) -> list[str]:
    reasons = list(verification_reasons)
    if analysis.get("query_type") == "comparison":
        for entity in analysis.get("missing_requested_entities") or []:
            reason = f"missing_requested_entity:{entity}"
            if reason not in reasons:
                reasons.append(reason)
    return reasons


def answer_status_reason(
    status: str,
    verified: bool,
    verification_reasons: list[str],
    code: str | None = None,
) -> dict[str, Any]:
    if code is None:
        if status == ANSWER_STATUS_SUPPORTED:
            code = "verified"
        elif status == ANSWER_STATUS_PARTIAL:
            # Disambiguate between the two partial paths so the status
            # reason is machine-readable: comparison-coverage partial
            # vs partial-topic grounding (#69 / ADR 0004).
            if PARTIAL_TOPIC_GROUNDING_REASON in verification_reasons:
                code = "partial_topic_grounding"
            else:
                code = "partial_comparison"
        else:
            code = "insufficient_evidence"
    return {
        "code": code,
        "verified": bool(verified),
        "verification_reasons": verification_reasons,
    }


def build_claims(analysis: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if analysis.get("query_type") == "comparison" and len(analysis.get("entities", [])) > 1:
        return build_comparison_claims(analysis, evidence)

    return build_extract_claims(analysis, evidence)


def build_comparison_claims(
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    claims = []
    used_chunks = set()
    for entity in analysis["entities"]:
        entity_evidence = [item for item in evidence if item.get("agency") == entity]
        if not entity_evidence:
            continue
        item = entity_evidence[0]
        if item["chunk_id"] in used_chunks:
            continue
        used_chunks.add(item["chunk_id"])
        claims.append(make_claim(entity, item, analysis))
    return claims


def build_extract_claims(analysis: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    seen = set()
    for item in evidence:
        metadata_sentences = metadata_claim_sentences(item, analysis)
        for metadata_sentence in metadata_sentences:
            key = (item["chunk_id"], metadata_sentence)
            if key in seen:
                continue
            seen.add(key)
            selected.append(
                make_claim(
                    claim_target(item),
                    item,
                    analysis,
                    sentence=metadata_sentence,
                    support=metadata_sentence,
                )
            )
            if len(selected) >= 2:
                break
        if len(selected) >= 2:
            break

        sentence = best_sentence(item["text"], analysis.get("topics", []), analysis.get("tokens", []))
        if metadata_sentences and not sentence_has_verification_topic(sentence, analysis):
            continue
        key = (item["chunk_id"], sentence)
        if key in seen:
            continue
        seen.add(key)
        selected.append(make_claim(claim_target(item), item, analysis, sentence=sentence))
        if len(selected) >= 2:
            break
    return selected


def make_claim(
    target: str,
    item: dict[str, Any],
    analysis: dict[str, Any],
    sentence: str | None = None,
    support: str | None = None,
) -> dict[str, Any]:
    claim_text = sentence or best_sentence(item["text"], analysis.get("topics", []), analysis.get("tokens", []))
    return {
        "target": target,
        "claim": claim_text,
        "support": support or item["text"],
        "citations": [make_citation(item)],
    }


def claim_target(item: dict[str, Any]) -> str:
    return str(item.get("agency") or item.get("title") or item.get("doc_id") or "unknown")


def make_citation(item: dict[str, Any]) -> dict[str, Any]:
    citation = {
        "doc_id": item.get("doc_id", ""),
        "chunk_id": item.get("chunk_id", ""),
        "title": item.get("title", ""),
        "section": item.get("section", ""),
        "agency": item.get("agency", ""),
    }
    regions = normalize_regions(item.get("regions"))
    page_span = normalize_page_span(item.get("page_span"), regions)
    if regions:
        citation["regions"] = regions
    if page_span:
        citation["page_span"] = page_span
    return citation


def answer_status(
    analysis: dict[str, Any],
    claims: list[dict[str, Any]],
    verified: bool,
    verification_reasons: list[str],
) -> str:
    has_partial_topic = PARTIAL_TOPIC_GROUNDING_REASON in verification_reasons
    if verified:
        has_missing_requested = any(
            reason.startswith("missing_requested_entity") for reason in verification_reasons
        )
        if has_partial_topic and claims:
            # Verified via the relaxed-stage partial-topic path: surface
            # the weaker grounding as ``partial`` rather than the
            # unconditional ``supported`` that strict verification yields.
            return ANSWER_STATUS_PARTIAL
        if not has_missing_requested and not has_partial_topic:
            return ANSWER_STATUS_SUPPORTED
    has_partial_comparison_reason = any(
        reason.startswith("missing_comparison")
        or reason.startswith("missing_requested_entity")
        for reason in verification_reasons
    )
    if analysis.get("query_type") == "comparison" and claims and has_partial_comparison_reason:
        return ANSWER_STATUS_PARTIAL
    return ANSWER_STATUS_INSUFFICIENT


def answer_query_type(analysis: dict[str, Any], status: str) -> str:
    if status == ANSWER_STATUS_INSUFFICIENT:
        return "abstention"
    if analysis.get("query_type") == "comparison":
        return "comparison"
    if analysis.get("query_type") == "follow_up":
        return "follow_up"
    return "single_doc"


def answer_summary(
    query: str,
    analysis: dict[str, Any],
    claims: list[dict[str, Any]],
    status: str,
    insufficiency: dict[str, Any] | None,
) -> str:
    if status == ANSWER_STATUS_INSUFFICIENT:
        return f"제공된 공개 샘플 RFP 근거에서는 '{query}'에 답할 수 있는 내용을 찾지 못했습니다."

    compact_claims = " ".join(f"{claim['target']}: {claim['claim']}" for claim in claims)
    if status == ANSWER_STATUS_PARTIAL:
        missing = ", ".join((insufficiency or {}).get("missing_targets") or [])
        suffix = f" 확인되지 않은 대상: {missing}." if missing else ""
        return f"일부 근거만 확인했습니다. {compact_claims}{suffix}".strip()

    if analysis.get("query_type") == "comparison":
        return compact_claims
    return " ".join(claim["claim"] for claim in claims)


def build_insufficiency(
    query: str,
    analysis: dict[str, Any],
    claims: list[dict[str, Any]],
    verified: bool,
    verification_reasons: list[str],
) -> dict[str, Any]:
    supported_targets = {claim.get("target") for claim in claims}
    checked_entities = analysis.get("entities") or analysis.get("context_entities") or []
    missing_targets = [entity for entity in checked_entities if entity not in supported_targets]
    if not verified and not missing_targets and checked_entities:
        missing_targets = list(checked_entities)
    return {
        "message": f"'{query}'에 대한 충분한 근거를 찾지 못했습니다.",
        "reasons": verification_reasons or (["verification_failed"] if not verified else []),
        "missing_targets": missing_targets,
        "missing_topics": specific_topics(analysis),
        "checked_entities": checked_entities,
        "checked_doc_ids": analysis.get("matched_doc_ids") or [],
    }


def render_answer_text(answer: dict[str, Any]) -> str:
    lines = [str(answer.get("summary") or "").strip()]
    for claim in answer.get("claims") or []:
        citations = claim.get("citations") or []
        citation_ids = ", ".join(citation.get("chunk_id", "") for citation in citations if citation.get("chunk_id"))
        suffix = f" [{citation_ids}]" if citation_ids else ""
        lines.append(f"- {claim.get('target')}: {claim.get('claim')}{suffix}")
    insufficiency = answer.get("insufficiency")
    if insufficiency:
        reasons = ", ".join(insufficiency.get("reasons") or [])
        missing_targets = ", ".join(insufficiency.get("missing_targets") or [])
        details = []
        if reasons:
            details.append(f"사유: {reasons}")
        if missing_targets:
            details.append(f"확인 필요 대상: {missing_targets}")
        if details:
            lines.append("- 근거 부족: " + "; ".join(details))
    return "\n".join(line for line in lines if line)


def best_sentence(text: str, topics: list[str], query_tokens: list[str]) -> str:
    sentences = sentence_split(text) or [text]
    scored = []
    token_set = set(query_tokens)
    for sentence in sentences:
        lowered = sentence.lower()
        topic_hits = sum(1 for topic in topics if topic.lower() in lowered)
        sentence_tokens = set(tokenize(sentence))
        token_hits = len(token_set & sentence_tokens)
        scored.append((topic_hits * 3 + token_hits, len(sentence), sentence))
    scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return scored[0][2]


def metadata_claim_sentences(item: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        return []

    sentences = []
    for key in METADATA_CLAIM_LABELS:
        value = metadata.get(key)
        if value is None or value == "":
            continue
        if not metadata_field_requested(key, value, analysis):
            continue
        sentences.append(f"{METADATA_CLAIM_LABELS[key]}: {format_metadata_claim_value(key, value)}")
    return ordered_unique(sentences)


def metadata_field_requested(key: str, value: Any, analysis: dict[str, Any]) -> bool:
    terms = [term for term in verification_topics(analysis) if term]
    if not terms:
        return False

    labels = METADATA_CLAIM_TOPIC_LABELS.get(key) or METADATA_EVIDENCE_LABELS.get(key, (key,))
    label_text = " ".join(str(label) for label in labels)
    value_text = str(value)
    searchable = compact_metadata_text(f"{label_text} {value_text}")
    for term in terms:
        compact_term = compact_metadata_text(str(term))
        if compact_term and compact_term in searchable:
            return True
    return False


def format_metadata_claim_value(key: str, value: Any) -> str:
    if key == "budget" and isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            return f"{value:,.2f}원"
        return f"{int(value):,}원"
    return str(value)


def sentence_has_verification_topic(sentence: str, analysis: dict[str, Any]) -> bool:
    topics = verification_topics(analysis)
    if not topics:
        return True
    lowered = sentence.lower()
    return any(topic.lower() in lowered for topic in topics)


def _is_aggregate_query(analysis: dict[str, Any]) -> bool:
    """Return True when the query has aggregate intent.

    Detects tokens such as "모든" / "전체" / "정리" that indicate the
    user wants an exhaustive listing of all matching fields — not just
    the first matching chunk.  Checked against ``analysis["tokens"]``
    (tokenised resolved query) and ``analysis["resolved_query"]`` as
    a substring fallback for tokens the analyser may have merged or
    split differently.
    """
    resolved: str = analysis.get("resolved_query") or ""
    tokens: list[str] = analysis.get("tokens") or []
    return any(sig in resolved for sig in _AGGREGATE_SIGNALS) or any(
        sig in tokens for sig in _AGGREGATE_SIGNALS
    )


def select_supporting_evidence(
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    topics = [topic.lower() for topic in verification_topics(analysis)]
    topic_matched = [
        item
        for item in evidence
        if not topics or any(topic in evidence_text_for_verification(item).lower() for topic in topics)
    ]

    if analysis.get("query_type") == "comparison" and len(analysis.get("entities", [])) > 1:
        selected = []
        for entity in analysis["entities"]:
            match = next((item for item in topic_matched if item.get("agency") == entity), None)
            if not match and not topics:
                match = next((item for item in evidence if item.get("agency") == entity), None)
            if match:
                selected.append(match)
        if topics:
            return selected or topic_matched[:2]
        return selected or evidence[:2]

    pool = topic_matched or evidence
    pool_size = _AGGREGATE_POOL_MAX if _is_aggregate_query(analysis) else 2
    return pool[:pool_size]


