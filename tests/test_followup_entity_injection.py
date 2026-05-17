"""Follow-up retrieval entity injection (issue #71).

Real-data taxonomy C4-1 noted that `resolve_conversation_context` was
asymmetric:

* When `context_entities` was passed explicitly (CLI flag / eval case)
  the function returned the **original** query unchanged, leaving
  dense/lexical retrievers without the entity anchor.
* When the entity came from `conversation_state` (multi-turn active
  state), the function prepended state terms to the query.

This file locks in the fix:

* The `inject_entities_into_query` helper prepends entities,
  de-duplicating ones that already appear in the query.
* Both branches of `resolve_conversation_context` use the helper so
  the resolved query has the entity prefix consistently.
"""

import unittest
from pathlib import Path

from rag_core import (
    build_index_payload,
    inject_entities_into_query,
    resolve_conversation_context,
    run_rag_query,
)
from tests._shared_index_cache import get_shared_raw_index


class InjectEntitiesIntoQueryTest(unittest.TestCase):
    """Unit checks on the helper that prepends entities to the query."""

    def test_prepends_missing_entity(self) -> None:
        self.assertEqual(
            inject_entities_into_query("일정은 어떻게 돼?", ["기관 A"]),
            "기관 A 일정은 어떻게 돼?",
        )

    def test_skips_entity_already_in_query(self) -> None:
        # User typed the entity themselves — don't duplicate.
        self.assertEqual(
            inject_entities_into_query(
                "기관 A의 일정은 어떻게 돼?", ["기관 A"]
            ),
            "기관 A의 일정은 어떻게 돼?",
        )

    def test_case_insensitive_dedup(self) -> None:
        self.assertEqual(
            inject_entities_into_query("AGENCY a is great", ["agency A"]),
            "AGENCY a is great",
        )

    def test_no_entities_returns_query_verbatim(self) -> None:
        self.assertEqual(
            inject_entities_into_query("일정은?", []),
            "일정은?",
        )

    def test_multiple_entities_all_prepended(self) -> None:
        # Order preserved; both entities prefixed.
        self.assertEqual(
            inject_entities_into_query("비교해줘", ["기관 A", "기관 B"]),
            "기관 A 기관 B 비교해줘",
        )

    def test_mixed_present_and_missing(self) -> None:
        # Only the missing entity gets prefixed.
        self.assertEqual(
            inject_entities_into_query(
                "기관 A와 기관 B의 비교", ["기관 A", "기관 C"]
            ),
            "기관 C 기관 A와 기관 B의 비교",
        )


class ResolveConversationContextSymmetryTest(unittest.TestCase):
    """The explicit-context and conversation-state paths must both
    surface the entity in the resolved query string.

    Pre-#71 the explicit-context path returned the original query
    unchanged, leaving dense/lexical retrievers without the anchor.
    """

    def test_explicit_context_path_augments_query(self) -> None:
        resolved_query, effective_entities, ctx = resolve_conversation_context(
            "일정은 어떻게 돼?",
            initial_analysis={"matched_doc_ids": []},
            conversation_state={},
            context_entities=["기관 A"],
        )
        self.assertEqual(resolved_query, "기관 A 일정은 어떻게 돼?")
        self.assertEqual(effective_entities, ["기관 A"])
        self.assertEqual(ctx["source"], "context_entities")
        self.assertEqual(ctx["resolved_query"], "기관 A 일정은 어떻게 돼?")

    def test_conversation_state_path_augments_query(self) -> None:
        resolved_query, _, ctx = resolve_conversation_context(
            "그럼 일정은 어떻게 돼?",
            initial_analysis={"matched_doc_ids": []},
            conversation_state={
                "active_agencies": ["기관 A"],
                "active_terms": ["기관 A"],
                "confidence": 0.9,
            },
            context_entities=None,
        )
        # Both branches produce the same prefix shape.
        self.assertEqual(resolved_query, "기관 A 그럼 일정은 어떻게 돼?")
        self.assertEqual(ctx["source"], "conversation_state")

    def test_explicit_context_with_entity_already_in_query(self) -> None:
        # When the user typed the entity themselves, don't duplicate.
        resolved_query, _, ctx = resolve_conversation_context(
            "기관 A의 일정은?",
            initial_analysis={"matched_doc_ids": []},
            conversation_state={},
            context_entities=["기관 A"],
        )
        self.assertEqual(resolved_query, "기관 A의 일정은?")
        self.assertEqual(ctx["resolved_query"], "기관 A의 일정은?")


class FollowUpRetrievalAnchorRegressionTest(unittest.TestCase):
    """End-to-end guard: follow-up queries with explicit context entities
    must produce a `resolved_query` that contains the entity anchor.

    A regression that drops the entity injection flips the diagnostic
    field even when the metadata-first path happens to still pick the
    right doc — so this test guards the inject path independently of
    retrieval success on the public synthetic surface.
    """

    @classmethod
    def setUpClass(cls) -> None:
        # Issue #915 — worker-local cache, see tests/_shared_index_cache.py.
        cls.index = get_shared_raw_index()

    def test_resolved_query_contains_entity_anchor(self) -> None:
        result = run_rag_query(
            self.index,
            "그럼 일정은 어떻게 돼?",
            context_entities=["기관 A"],
        )
        analysis = result.get("analysis", {})
        context_resolution = analysis.get("context_resolution", {})
        self.assertEqual(
            context_resolution.get("source"), "context_entities"
        )
        resolved_query = context_resolution.get("resolved_query", "")
        self.assertIn(
            "기관 A",
            resolved_query,
            f"resolved_query lost entity anchor: {resolved_query!r}",
        )
        # Pre-#71 the resolved_query was just the user's input.
        self.assertNotEqual(resolved_query, "그럼 일정은 어떻게 돼?")

    def test_follow_up_still_resolves_to_correct_doc(self) -> None:
        # Sanity: the metadata-first path still drives this case to
        # the right agency on synthetic data. The fix is purely
        # additive — it gives the entity anchor to dense/lexical
        # scoring without changing what already worked.
        result = run_rag_query(
            self.index,
            "그럼 일정은 어떻게 돼?",
            context_entities=["기관 A"],
        )
        self.assertEqual(result["answer"]["status"], "supported")
        evidence = result.get("evidence", [])
        self.assertTrue(evidence)
        self.assertEqual(
            evidence[0]["doc_id"], "rfp-agency-a-ai-quality"
        )


if __name__ == "__main__":
    unittest.main()
