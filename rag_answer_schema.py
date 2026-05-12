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
