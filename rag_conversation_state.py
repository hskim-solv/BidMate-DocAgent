"""Multi-turn conversation state for the BidMate RAG core.

Extracted from ``rag_core.py`` in issue #415 (PR-E stage 3 of the
``rag_core.py`` decomposition epic — external senior review 2026-05
finding #3). This module owns the **canonical** definition of the
conversation-state schema that ``run_rag_query`` consumes and emits
across turns:

- ``CONVERSATION_STATE_SCHEMA_VERSION`` — bumps when a follow-up PR
  alters the state shape in a way that breaks producers / consumers.
- ``MAX_CONVERSATION_TURNS`` — bounded-history cap on ``turns``.
- ``CONTEXT_RESOLUTION_THRESHOLD`` — confidence floor for
  cross-turn reference resolution.
- ``AMBIGUOUS_CONFIDENCE_DELTA`` — minimum gap between the top
  metadata score and the next candidate before we declare a single
  winner. Used by the planner's ambiguity surface (rag_core, line
  ~1229) and re-exported here so the conversation-state schema and
  the ambiguity threshold travel together.
- :func:`empty_conversation_state` — schema-version-tagged blank.
- :func:`normalize_conversation_state` — defensive coercion of an
  arbitrary external payload into the schema.

The module is a **leaf**: it imports nothing from ``rag_core``.
``rag_core`` imports the six public symbols back and uses them
directly — no re-export wrapper because no external module references
these names (verified via repo-wide grep at issue #415 filing time).

Helper duplication note
-----------------------
``_ordered_unique`` and ``_coerce_string_list`` are five-line copies
of the same-named utilities in ``rag_core.py``. Inlining them here
keeps the leaf-module invariant (no rag_core import) at the cost of
two tiny duplicates; a future stage that extracts a shared
``rag_text_utils`` module can collapse them.
"""

from __future__ import annotations

from typing import Any, Iterable


CONVERSATION_STATE_SCHEMA_VERSION = 1
MAX_CONVERSATION_TURNS = 12
CONTEXT_RESOLUTION_THRESHOLD = 0.70
AMBIGUOUS_CONFIDENCE_DELTA = 0.05


def _ordered_unique(values: Iterable[str]) -> list[str]:
    """Return *values* with duplicates and falsy entries removed, order preserved."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _coerce_string_list(value: Any) -> list[str]:
    """Coerce *value* to ``list[str]`` of trimmed, deduped, non-empty entries.

    Returns ``[]`` for any non-list input. Matches the semantics of
    ``rag_core.coerce_string_list`` exactly.
    """
    if not isinstance(value, list):
        return []
    return _ordered_unique(str(item).strip() for item in value if str(item).strip())


def empty_conversation_state() -> dict[str, Any]:
    """Return a schema-versioned, empty conversation state."""
    return {
        "schema_version": CONVERSATION_STATE_SCHEMA_VERSION,
        "active_agencies": [],
        "active_projects": [],
        "active_topics": [],
        "active_doc_ids": [],
        "active_candidates": [],
        "confidence": 0.0,
        "ambiguous": False,
        "turns": [],
    }


def normalize_conversation_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """Defensively coerce *state* into the schema.

    Trusts nothing about the input — any field that fails its type
    contract is replaced with the empty-schema default. ``turns`` is
    capped at the most recent ``MAX_CONVERSATION_TURNS`` entries;
    ``active_candidates`` is capped at the most recent 8.
    """
    normalized = empty_conversation_state()
    if not isinstance(state, dict):
        return normalized

    normalized["schema_version"] = int(
        state.get("schema_version") or CONVERSATION_STATE_SCHEMA_VERSION
    )
    normalized["active_agencies"] = _coerce_string_list(state.get("active_agencies"))
    normalized["active_projects"] = _coerce_string_list(state.get("active_projects"))
    normalized["active_topics"] = _coerce_string_list(state.get("active_topics"))
    normalized["active_doc_ids"] = _coerce_string_list(state.get("active_doc_ids"))
    active_candidates = state.get("active_candidates")
    if isinstance(active_candidates, list):
        normalized["active_candidates"] = [
            candidate for candidate in active_candidates[-8:] if isinstance(candidate, dict)
        ]
    normalized["ambiguous"] = bool(state.get("ambiguous", False))
    try:
        normalized["confidence"] = round(float(state.get("confidence") or 0.0), 3)
    except (TypeError, ValueError):
        normalized["confidence"] = 0.0

    turns = state.get("turns") if isinstance(state.get("turns"), list) else []
    normalized["turns"] = [
        turn for turn in turns[-MAX_CONVERSATION_TURNS:] if isinstance(turn, dict)
    ]
    return normalized
