"""Answer-contract schema constants for the BidMate RAG core.

Extracted from ``rag_core.py`` in issue #417 (PR-E stage 4a of the
``rag_core.py`` decomposition epic — external senior review 2026-05
finding #3). This module owns the **canonical** definitions of the
load-bearing symbols that
[ADR 0003 — Structured answer / citation contract](docs/adr/0003-structured-answer-citation-contract.md)
codifies:

- :data:`ANSWER_STATUS_SUPPORTED` / :data:`ANSWER_STATUS_PARTIAL` /
  :data:`ANSWER_STATUS_INSUFFICIENT` — the three values
  ``answer["status"]`` may take. Every consumer that branches on the
  status (verifier, LLM judge, eval scorers, demo UI) keys off these
  exact strings; a typo here would invalidate the contract for every
  downstream gate.
- :data:`ANSWER_SCHEMA_VERSION` — bumps whenever the dict that
  ``rag_core.run_rag_query`` returns adds, removes, or renames a
  field in a way that breaks a downstream consumer. CLAUDE.md
  ``Prohibited`` list flags this bump as load-bearing.

The module is a **leaf**: it imports nothing from ``rag_core``.
``rag_core`` imports the four symbols back and re-exports them, so
external consumers — ``tests/test_demo_helpers.py``,
``tests/test_governance.py``,
``tests/test_answer_contract_snapshot.py`` — keep their existing
``from rag_core import ANSWER_STATUS_SUPPORTED`` imports.

Stage 4b will move the answer-builder *functions*
(``generate_answer``, ``build_claims``, ``render_answer_text``,
``answer_status``, ...) — those have a deeper dependency chain
(``normalize_regions``, ``best_sentence``, ``PARTIAL_TOPIC_GROUNDING_REASON``)
and need their own JSON-identity gate.
"""

from __future__ import annotations


ANSWER_STATUS_SUPPORTED = "supported"
ANSWER_STATUS_PARTIAL = "partial"
ANSWER_STATUS_INSUFFICIENT = "insufficient"

ANSWER_SCHEMA_VERSION = 2

# Reason codes that ``answer["status_reason"]["code"]`` may take. Issue
# #759 (RAG senior-review critique #2) promotes the four string literals
# previously inlined in :func:`rag_answer.answer_status_reason` to
# canonical constants, then gates the function with
# :data:`KNOWN_ANSWER_STATUS_REASON_CODES` so an unknown override
# raises :class:`ValueError` instead of silently flowing into the
# downstream synthetic judge / eval scorer / dashboard layer.
#
# Mapping from ``answer["status"]`` to default code (no override path):
#   - ``ANSWER_STATUS_SUPPORTED``     → ``ANSWER_STATUS_REASON_VERIFIED``
#   - ``ANSWER_STATUS_PARTIAL``       → ``ANSWER_STATUS_REASON_PARTIAL_TOPIC_GROUNDING``
#                                       (when ``PARTIAL_TOPIC_GROUNDING_REASON``
#                                       is in verification_reasons; ADR 0004)
#                                     → ``ANSWER_STATUS_REASON_PARTIAL_COMPARISON``
#                                       (otherwise — comparison-coverage path)
#   - ``ANSWER_STATUS_INSUFFICIENT``  → ``ANSWER_STATUS_REASON_INSUFFICIENT_EVIDENCE``
#
# Two additional codes are reachable via the ``code=`` override that
# the clarification surface (rag_clarification) uses to disambiguate
# the *reason* a query was abstained from. Both pair with
# ``ANSWER_STATUS_INSUFFICIENT`` because clarification is a refusal-
# to-answer path that needs more user input:
#   - ``ANSWER_STATUS_REASON_CONTEXT_CLARIFICATION`` — the follow-up
#     query references prior context that has not been resolved
#     (rag_clarification.context_clarification_answer).
#   - ``ANSWER_STATUS_REASON_METADATA_AMBIGUITY_CLARIFICATION`` —
#     metadata-first matched multiple candidate documents
#     (rag_clarification.metadata_ambiguity_clarification_answer).
ANSWER_STATUS_REASON_VERIFIED = "verified"
ANSWER_STATUS_REASON_PARTIAL_TOPIC_GROUNDING = "partial_topic_grounding"
ANSWER_STATUS_REASON_PARTIAL_COMPARISON = "partial_comparison"
ANSWER_STATUS_REASON_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
ANSWER_STATUS_REASON_CONTEXT_CLARIFICATION = "context_clarification"
ANSWER_STATUS_REASON_METADATA_AMBIGUITY_CLARIFICATION = "metadata_ambiguity_clarification"

KNOWN_ANSWER_STATUS_REASON_CODES: frozenset[str] = frozenset({
    ANSWER_STATUS_REASON_VERIFIED,
    ANSWER_STATUS_REASON_PARTIAL_TOPIC_GROUNDING,
    ANSWER_STATUS_REASON_PARTIAL_COMPARISON,
    ANSWER_STATUS_REASON_INSUFFICIENT_EVIDENCE,
    ANSWER_STATUS_REASON_CONTEXT_CLARIFICATION,
    ANSWER_STATUS_REASON_METADATA_AMBIGUITY_CLARIFICATION,
})
