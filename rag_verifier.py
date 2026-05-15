"""Verifier path: grounding checks + evidence-side injection defense.

Extracted from ``rag_core.py`` (PR-J1, issue #465). Owns the
verifier surface that lives between retrieval and answer generation:

- :func:`verify_evidence` — main verifier. Strict topic grounding
  with the ``partial_topic_grounding`` soft signal (ADR 0004
  strict→relaxed staging policy).
- :func:`verification_topics` / :func:`specific_topics` /
  :func:`metadata_terms_for_verification` — topic-extraction helpers
  that decide which terms must appear in evidence.
- :func:`neutralize_instruction_patterns` — ADR 0008 evidence-boundary
  defense. Wraps chat-template tokens and instruction-override lines
  so injected directives in retrieved chunks cannot impersonate role
  boundaries in downstream LLM consumers.
- :func:`evidence_text_for_verification` / :func:`evidence_has_topic` —
  evidence-side inspection helpers consumed by ``verify_evidence``.

Constants:

- :data:`PARTIAL_TOPIC_GROUNDING_MIN_FRACTION` /
  :data:`PARTIAL_TOPIC_GROUNDING_MIN_MATCHED` /
  :data:`PARTIAL_TOPIC_GROUNDING_REASON` — the policy floors for
  partial-topic acceptance (issue #69 / #89, ADR 0004).
- :data:`EVIDENCE_BOUNDARY` — the chunk-separator token the synthetic
  LLM-judge surface and the OSS llm_judge script join evidence with
  (ADR 0008 / ADR 0012).

Circular-import avoidance: ``rag_core`` symbols that this module's
functions need (``normalize_metadata_token``, ``metadata_tokens``,
``ordered_unique``) are late-imported at function-call time. They
serve many non-verifier call sites in ``rag_core`` (analysis path,
metadata matching, claim builders) so they stay there.

JSON-identity guarantee: every function moves byte-for-byte from
``rag_core``. The verifier-touching regression gates remain green —
``tests/test_naive_baseline_ranking_invariance.py`` (ADR 0001),
``tests/test_retrieval_loop_regression.py``,
``tests/test_prompt_injection_regression.py`` (ADR 0008 surface),
``tests/test_synthetic_judge.py`` (EVIDENCE_BOUNDARY contract),
``tests/test_langgraph_orchestrator_regression.py``.
"""

from __future__ import annotations

import re
from typing import Any

from korean_lexicon import (
    METADATA_EVIDENCE_LABELS,
    METADATA_GENERIC_TOKENS,
    TOPIC_KEYWORDS,
    VERIFICATION_INTENT_TOKENS,
    VERIFICATION_TOPIC_EXCLUSIONS,
)
from rag_metadata_processing import metadata_tokens
from rag_text_processing import normalize_metadata_token, ordered_unique
from text_normalize import expand_forms, normalize_text


# Partial-topic grounding requires BOTH (a) at least
# PARTIAL_TOPIC_GROUNDING_MIN_MATCHED matched verification topics AND
# (b) the matched fraction to be at least
# PARTIAL_TOPIC_GROUNDING_MIN_FRACTION of all topics. The "≥ 2 matched"
# floor exists because a 1-of-2 incidental-overlap pattern flipped
# intended-abstention real-data cases to `partial` after #69 (see
# issue #89 and the Real-data Decision Log in
# docs/real-data/private-100-doc-experiments.md). Genuine partial recovery
# requires structural agreement across multiple topics. Keep both
# guards: the fraction floor still rejects 2-of-5 = 0.4 etc.
# See issue #69 / docs/real-data/real-data-failure-taxonomy.md C6, ADR 0004 for
# the strict→relaxed staging policy this implements.
PARTIAL_TOPIC_GROUNDING_MIN_FRACTION = 0.5
PARTIAL_TOPIC_GROUNDING_MIN_MATCHED = 2
PARTIAL_TOPIC_GROUNDING_REASON = "partial_topic_grounding"


def _count_target_doc_topic_matches(
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
    topics: list[str],
) -> int:
    """Count how many topics match inside *target-doc-only* evidence text.

    Guards against *cross-entity incidental matches* in partial-topic grounding:
    when the relaxed retrieval stage drops all metadata filters, documents from
    unrelated agencies can be retrieved alongside the correct ones. If those
    unrelated chunks happen to mention 2+ verification topics (e.g. a generic
    "납품 일정" phrase), the topic count computed over the combined evidence pool
    would incorrectly trigger ``partial_topic_grounding``.

    When ``analysis["matched_doc_ids"]`` is non-empty (the query was mapped to
    specific documents by the analysis layer), this function restricts the
    topic-counting to evidence items whose ``doc_id`` is in that target set.
    If no target evidence exists, the count is 0. If ``matched_doc_ids`` is
    empty (unconstrained query), all evidence is used and the function behaves
    identically to the full-pool count — the guard is dormant.

    Issue #687 / ADR 0004 (partial-topic grounding policy).
    """
    target_doc_ids: set[str] = set(analysis.get("matched_doc_ids") or [])
    if not target_doc_ids:
        # Unconstrained query — count over all evidence (guard dormant).
        pool = evidence
    else:
        pool = [item for item in evidence if item.get("doc_id", "") in target_doc_ids]
        if not pool:
            return 0

    pool_text = " ".join(evidence_text_for_verification(item) for item in pool).lower()
    pool_canonical = normalize_text(pool_text)
    return sum(
        1
        for topic in topics
        if any(
            form in pool_text or form in pool_canonical
            for form in expand_forms(topic.lower())
        )
    )


def verify_evidence(
    analysis: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    allow_partial_topic: bool = False,
) -> tuple[bool, list[str]]:
    """Verify that ``evidence`` supports the query in ``analysis``.

    When ``allow_partial_topic`` is ``True`` (caller signals this is the
    last retrieval attempt), a partial topic match — at least
    :data:`PARTIAL_TOPIC_GROUNDING_MIN_MATCHED` matched topics AND at
    least :data:`PARTIAL_TOPIC_GROUNDING_MIN_FRACTION` of all topics
    present in the combined evidence text — is accepted with
    ``verified=True`` and a non-blocking
    :data:`PARTIAL_TOPIC_GROUNDING_REASON` in the reasons list. The
    caller (see :func:`answer_status`) maps that reason to
    ``ANSWER_STATUS_PARTIAL`` so the answer surfaces the weaker
    grounding instead of abstaining outright.

    The ``≥ 2 matched`` floor (issue #89) cuts the 1-of-2 incidental
    overlap pattern that flipped real-data intended-abstention cases
    to ``partial`` after #69; the fraction floor remains as a guard
    against weakly-balanced cases like 2-of-5.

    All other checks (low top score, comparison entity / doc coverage)
    remain strict — partial topic grounding does not bypass hallucination
    floors or comparison contracts.
    """
    reasons: list[str] = []
    if not evidence:
        return False, ["no_evidence"]
    if evidence[0]["score"] < 0.18:
        reasons.append("low_top_score")

    combined = " ".join(evidence_text_for_verification(item) for item in evidence).lower()
    # ADR 0007 / issue #170: Korean money/date OR-match. Build canonical form
    # once; substring check tests (form ∈ combined) OR (form ∈ canonical) for
    # each form in expand_forms(topic). Strictly additive — legacy
    # (topic ∈ combined) is preserved as the first branch.
    combined_canonical = normalize_text(combined)
    topics = verification_topics(analysis)
    if topics:
        matched_topic_count = sum(
            1
            for topic in topics
            if any(
                form in combined or form in combined_canonical
                for form in expand_forms(topic.lower())
            )
        )
        if matched_topic_count < len(topics):
            if allow_partial_topic:
                # Cross-entity guard (issue #687): recount topics only in
                # target-doc evidence so incidental matches from unrelated
                # agencies retrieved in relaxed mode can't flip the decision.
                partial_count = _count_target_doc_topic_matches(
                    analysis, evidence, topics
                )
            else:
                partial_count = matched_topic_count
            if (
                allow_partial_topic
                and partial_count >= PARTIAL_TOPIC_GROUNDING_MIN_MATCHED
                and (partial_count / len(topics)) >= PARTIAL_TOPIC_GROUNDING_MIN_FRACTION
            ):
                # Soft signal — caller surfaces this as `partial` status.
                reasons.append(PARTIAL_TOPIC_GROUNDING_REASON)
            else:
                reasons.append("topic_not_grounded")

    entities = analysis.get("entities") or []
    if analysis.get("query_type") == "comparison" and len(entities) > 1:
        covered = {item.get("agency") for item in evidence}
        missing = [entity for entity in entities if entity not in covered]
        if missing:
            reasons.append("missing_comparison_entity:" + ",".join(missing))
        if topics:
            missing_topic_entities = []
            for entity in entities:
                entity_evidence = [item for item in evidence if item.get("agency") == entity]
                if entity_evidence and not any(evidence_has_topic(item, topics) for item in entity_evidence):
                    missing_topic_entities.append(entity)
            if missing_topic_entities:
                reasons.append("missing_comparison_topic:" + ",".join(missing_topic_entities))

    matched_doc_ids = analysis.get("matched_doc_ids") or []
    if analysis.get("query_type") == "comparison" and len(matched_doc_ids) > 1:
        covered_doc_ids = {item.get("doc_id") for item in evidence}
        missing_doc_ids = [doc_id for doc_id in matched_doc_ids if doc_id not in covered_doc_ids]
        if missing_doc_ids:
            reasons.append("missing_comparison_doc:" + ",".join(missing_doc_ids))

    # `partial_topic_grounding` is non-blocking: it surfaces the weaker
    # grounding to the answer layer without forcing an abstention.
    blocking_reasons = [reason for reason in reasons if reason != PARTIAL_TOPIC_GROUNDING_REASON]
    return not blocking_reasons, reasons


def specific_topics(analysis: dict[str, Any]) -> list[str]:
    return verification_topics(analysis)


def verification_topics(analysis: dict[str, Any]) -> list[str]:
    metadata_terms = metadata_terms_for_verification(analysis)
    keyword_terms = {
        norm
        for keyword in TOPIC_KEYWORDS
        for norm in (normalize_metadata_token(keyword),)
        if norm.lower() != "ai"
    }
    topics = []
    for topic in analysis.get("topics", []):
        normalized = normalize_metadata_token(str(topic))
        if not normalized or normalized.lower() == "ai":
            continue
        if normalized in metadata_terms and normalized not in keyword_terms:
            continue
        if normalized in METADATA_GENERIC_TOKENS or normalized in VERIFICATION_INTENT_TOKENS:
            continue
        if normalized in VERIFICATION_TOPIC_EXCLUSIONS:
            continue
        topics.append(normalized)
    return ordered_unique(topics)


def metadata_terms_for_verification(analysis: dict[str, Any]) -> set[str]:
    values: list[str] = []
    for key in ("entities", "matched_agencies", "matched_projects", "context_entities"):
        values.extend(str(value) for value in analysis.get(key) or [])
    for match in analysis.get("metadata_matches") or []:
        values.extend(
            str(match.get(key) or "")
            for key in ("agency", "project", "value")
        )
        values.extend(str(term) for term in match.get("matched_terms") or [])
    return set(metadata_tokens(" ".join(values)))


EVIDENCE_BOUNDARY = "\n[---EVIDENCE_BOUNDARY---]\n"

_CHAT_TEMPLATE_TOKEN_RE = re.compile(
    r"<\|(?:im_start|im_end|system|user|assistant|tool|begin_of_text|end_of_text|fim_[a-z_]+|endoftext)\|>",
    re.IGNORECASE,
)
_ROLE_TAG_LINE_RE = re.compile(
    r"(?im)^[ \t]*(SYSTEM|ASSISTANT|USER|TOOL)\s*:\s*.+$"
)
_INSTRUCTION_OVERRIDE_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,80}?\b(?:instructions?|prompts?|rules?|directives?|system|guidance)\b.*$"
)


def neutralize_instruction_patterns(text: str) -> str:
    """Neutralize chat-template and instruction-override patterns in document-controlled text.

    Wraps suspicious lines with ``[INSTRUCTION_LIKE]...[/INSTRUCTION_LIKE]``
    and replaces chat template tokens with ``[REDACTED_CHAT_TOKEN]`` so they
    cannot impersonate role boundaries in downstream LLM consumers. Content
    is preserved (citations remain readable) — see ADR 0008.
    """
    if not text:
        return text
    out = _CHAT_TEMPLATE_TOKEN_RE.sub("[REDACTED_CHAT_TOKEN]", text)
    out = _ROLE_TAG_LINE_RE.sub(
        lambda m: f"[INSTRUCTION_LIKE]{m.group(0)}[/INSTRUCTION_LIKE]", out
    )
    out = _INSTRUCTION_OVERRIDE_LINE_RE.sub(
        lambda m: f"[INSTRUCTION_LIKE]{m.group(0)}[/INSTRUCTION_LIKE]", out
    )
    return out


def evidence_text_for_verification(item: dict[str, Any]) -> str:
    parts = [
        neutralize_instruction_patterns(str(item.get("title", "") or "")),
        neutralize_instruction_patterns(str(item.get("agency", "") or "")),
        neutralize_instruction_patterns(str(item.get("project", "") or "")),
        neutralize_instruction_patterns(str(item.get("section", "") or "")),
        neutralize_instruction_patterns(str(item.get("text", "") or "")),
    ]
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            if value is None or value == "":
                continue
            parts.extend(METADATA_EVIDENCE_LABELS.get(str(key), (str(key),)))
            parts.append(neutralize_instruction_patterns(str(value)))
    return " ".join(part for part in parts if part.strip())


def evidence_has_topic(item: dict[str, Any], topics: list[str]) -> bool:
    text = evidence_text_for_verification(item).lower()
    text_canonical = normalize_text(text)
    return any(
        (form in text) or (form in text_canonical)
        for topic in topics
        for form in expand_forms(topic.lower())
    )


def format_verifier_feedback(
    reasons: list[str],
    evidence: list[dict[str, Any]],
) -> str:
    """Format verifier failure reasons into a coaching message for the next planning turn.

    Called by ``rag_graph_react._react_loop_node`` after a ``verify_grounding``
    tool call returns a non-grounded verdict.  The returned string is stored in
    ``attempt["feedback_message"]`` in the history dict, so ``LLMPlanner`` can
    read it in the next ``plan_next`` call and adjust retrieval parameters.

    ``reasons`` are internal diagnostic strings produced by ``verify_evidence``,
    not external evidence text, so ``neutralize_instruction_patterns`` is not
    applied here.  If ``reasons`` is empty (unexpected) a generic fallback is
    returned.
    """
    if not reasons:
        return (
            "이전 검색 결과의 근거가 부족합니다. "
            "다른 stage(relaxed) 또는 키워드로 retrieve_evidence를 재시도해주세요."
        )
    chunk_count = len(evidence)
    reasons_text = "\n".join(f"- {r}" for r in reasons)
    return (
        f"이전 검색 결과 검증 실패 ({chunk_count}개 chunk):\n"
        f"{reasons_text}\n"
        "위 원인을 참고해 검색 stage/필터/top_k를 조정한 뒤 retrieve_evidence를 다시 호출하거나, "
        "evidence가 확실히 없으면 abstain을 선택하세요."
    )
