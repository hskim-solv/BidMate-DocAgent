"""ADR 0059 — failure-mode classifier regression guard.

Locks the first-match-wins ordering in ``eval/scorers/failure_classifier.py``
so the Phase 5 audit (#992) finding #1 pattern (``answerable=False AND not
abstained``, 87/103 incorrect_answer on n=221 baseline) accumulates into
``verifier_false_negative`` and not a more permissive category.

Test layout:

* 7 unit tests — one per category, asserting ``classify_failure`` returns
  the right label on a minimal fixture.
* 2 boundary tests — successful answerable + successful unanswerable both
  return ``None`` (so they're excluded from supply 2 / 3 consumers).
* 1 integration test — runs the same 5-case mix that
  ``tests/test_scorers_case_abstention.py`` uses through ``score_case``
  + ``aggregate_failure_categories`` and pins the expected counts so a
  future ordering / branch tweak surfaces immediately.
"""
from __future__ import annotations

import unittest

from eval.scorers.case import score_case
from eval.scorers.failure_classifier import (
    FAILURE_CATEGORIES,
    aggregate_failure_categories,
    classify_failure,
    is_failed,
)


def _prediction(
    *,
    answer_status: str = "supported",
    summary: str = "",
    claims: list[dict[str, object]] | None = None,
    evidence: list[dict[str, object]] | None = None,
    abstained: bool = False,
    filter_stage_attempts: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build a prediction dict matching ADR 0003 answer-contract schema_version=2.

    Mirrors the helper in ``tests/test_scorers_case_abstention.py``; the
    only extra parameter is ``filter_stage_attempts`` so we can drive the
    ``planner_under_decomposition`` branch via the
    ``score_case`` → ``attempt_latency`` pass-through (case.py:185-192).
    """
    return {
        "answer": {
            "schema_version": 2,
            "status": answer_status,
            "summary": summary,
            "claims": claims or [],
            "insufficiency": {"missing_targets": []},
            "confidence": None,
        },
        "evidence": evidence or [],
        "diagnostics": {
            "abstained": abstained,
            "latency_ms": 100.0,
            "retry_count": 0,
            "filter_stage_attempts": filter_stage_attempts or [],
            "stage_latency": {},
            "retrieved_chunk_ids": [],
        },
        "plan": {},
        "analysis": {},
    }


class TestVerifierFalseNegative(unittest.TestCase):
    """1. verifier_false_negative — answered an unanswerable query.

    Phase 5 audit (#992) finding #1: 87/103 incorrect_answer on n=221
    baseline. Must land here, not in ``unknown`` or ``retrieval_miss``.
    """

    def test_classifies_unanswerable_answered(self) -> None:
        case = {
            "id": "vfn_case",
            "query_type": "abstention",
            "answerable": False,
            "expected_doc_ids": [],
            "expected_terms": [],
            "expected_citation_terms": [],
        }
        prediction = _prediction(
            summary="Fabricated answer.",
            claims=[
                {
                    "target": "fake_target",
                    "text": "Fabricated answer.",
                    "citations": [{"doc_id": "doc_y", "chunk_id": "doc_y:0", "page": 1}],
                }
            ],
            evidence=[{"doc_id": "doc_y", "chunk_id": "doc_y:0", "text": "noise"}],
            abstained=False,
        )
        result = score_case(case, prediction)
        self.assertEqual(classify_failure(result), "verifier_false_negative")


class TestVerifierFalsePositive(unittest.TestCase):
    """2. verifier_false_positive — refused an answerable query whose
    EVIDENCE already contained the answer (verifier was wrong gatekeeper).

    The classifier keys on evidence-only signals (expected docs reached
    evidence AND citation terms appeared in evidence_text), NOT on
    ``term_match`` (which is computed over answer+evidence, case.py:44,81).
    """

    def test_classifies_answerable_refused_with_evidence_terms(self) -> None:
        case = {
            "id": "vfp_case",
            "query_type": "single_doc",
            "answerable": True,
            "expected_doc_ids": ["doc_a"],
            "expected_terms": ["budget"],
            "expected_citation_terms": ["budget"],
        }
        # The model abstained, but the expected doc reached evidence and the
        # citation term "budget" is present in evidence_text — the answer was
        # right there. The answer summary deliberately does NOT echo "budget",
        # so this fires purely on evidence-derived signals.
        prediction = _prediction(
            answer_status="insufficient",
            summary="The figure is unclear.",  # does NOT contain "budget"
            evidence=[{"doc_id": "doc_a", "chunk_id": "doc_a:0", "text": "budget data"}],
            abstained=True,
        )
        result = score_case(case, prediction)
        self.assertTrue(
            result["citation_term_match"], "Fixture must drive citation_term_match=True"
        )
        self.assertEqual(classify_failure(result), "verifier_false_positive")

    def test_abstained_with_empty_evidence_is_not_false_positive(self) -> None:
        """F1 regression — an abstained answerable case whose ANSWER echoes the
        expected term but whose EVIDENCE is empty must NOT be a false positive.

        ``term_match`` (answer+evidence) is True here because the summary
        echoes "budget", but evidence is empty so the answer was never
        actually grounded. The previous ``term_match`` branch mis-bucketed
        this as verifier_false_positive; it is a retrieval_miss.
        """
        case = {
            "id": "vfp_empty_evidence",
            "query_type": "single_doc",
            "answerable": True,
            "expected_doc_ids": ["doc_a"],
            "expected_terms": ["budget"],
            "expected_citation_terms": ["budget"],
        }
        prediction = _prediction(
            answer_status="insufficient",
            summary="The budget is unclear.",  # echoes "budget" → term_match=True
            evidence=[],  # but nothing was actually retrieved
            abstained=True,
        )
        result = score_case(case, prediction)
        self.assertTrue(result["term_match"], "Fixture must drive term_match=True")
        self.assertFalse(
            result["citation_term_match"], "Empty evidence → citation_term_match=False"
        )
        self.assertEqual(classify_failure(result), "retrieval_miss")


class TestRetrievalMiss(unittest.TestCase):
    """3. retrieval_miss — answerable AND expected doc not in evidence."""

    def test_classifies_missing_expected_doc(self) -> None:
        case = {
            "id": "retrieval_miss_case",
            "query_type": "single_doc",
            "answerable": True,
            "expected_doc_ids": ["doc_a"],
            "expected_terms": ["budget"],
            "expected_citation_terms": ["budget"],
        }
        # Evidence has a different doc, not doc_a.
        prediction = _prediction(
            answer_status="supported",
            summary="Some answer.",
            evidence=[{"doc_id": "doc_b", "chunk_id": "doc_b:0", "text": "unrelated"}],
            abstained=False,
        )
        result = score_case(case, prediction)
        self.assertEqual(classify_failure(result), "retrieval_miss")


class TestPlannerUnderDecomposition(unittest.TestCase):
    """4. planner_under_decomposition — decomposition-required + single attempt.

    ``multi_hop`` is carried on ``hardcase_categories`` (NOT query_type — the
    loader rejects multi_hop as a query_type, see
    ``TestLoaderRejectsMultiHopQueryType``), so the classifier must detect it
    there. Base query_type is the valid ``single_doc`` here to isolate the
    hardcase-driven path.
    """

    def test_classifies_multihop_hardcase_single_attempt(self) -> None:
        case = {
            "id": "planner_case",
            "query_type": "single_doc",
            "hardcase_categories": ["multi_hop"],
            "answerable": True,
            "expected_doc_ids": ["doc_a", "doc_b"],
            "expected_terms": ["term1"],
            "expected_citation_terms": ["term1"],
        }
        # Evidence has both expected docs (so retrieval_miss won't fire),
        # but accuracy still fails because term_match misses → is_failed.
        prediction = _prediction(
            answer_status="supported",
            summary="Some answer.",
            evidence=[
                {"doc_id": "doc_a", "chunk_id": "doc_a:0", "text": "noise"},
                {"doc_id": "doc_b", "chunk_id": "doc_b:0", "text": "noise"},
            ],
            abstained=False,
            filter_stage_attempts=[
                # Single attempt → trips planner_under_decomposition.
                {"stage": "filter", "retrieve_ms": 50.0, "verify_ms": 25.0, "verified": False},
            ],
        )
        result = score_case(case, prediction)
        # Sanity: not retrieval_miss (both expected docs present).
        self.assertEqual(set(result["evidence_doc_ids"]), {"doc_a", "doc_b"})
        self.assertEqual(result["hardcase_categories"], ["multi_hop"])
        self.assertEqual(classify_failure(result), "planner_under_decomposition")

    def test_classifies_comparison_query_type_single_attempt(self) -> None:
        """``comparison`` is a first-class query_type and also decomposition-required."""
        case = {
            "id": "planner_comparison",
            "query_type": "comparison",
            "answerable": True,
            "expected_doc_ids": ["doc_a", "doc_b"],
            "expected_terms": ["term1"],
            "expected_citation_terms": ["term1"],
        }
        prediction = _prediction(
            answer_status="supported",
            summary="Some answer.",
            evidence=[
                {"doc_id": "doc_a", "chunk_id": "doc_a:0", "text": "noise"},
                {"doc_id": "doc_b", "chunk_id": "doc_b:0", "text": "noise"},
            ],
            abstained=False,
            filter_stage_attempts=[
                {"stage": "filter", "retrieve_ms": 50.0, "verify_ms": 25.0, "verified": False},
            ],
        )
        result = score_case(case, prediction)
        self.assertEqual(classify_failure(result), "planner_under_decomposition")


class TestLoaderRejectsMultiHopQueryType(unittest.TestCase):
    """F3 premise — ``multi_hop`` is not a canonical query_type, so the loader
    rejects it. This is why the classifier must detect multi_hop via
    ``hardcase_categories`` and not ``query_type``."""

    def test_load_config_rejects_multihop_query_type(self) -> None:
        import tempfile
        from pathlib import Path

        import yaml

        from eval.run_eval import QUERY_TYPES, load_config

        self.assertNotIn("multi_hop", QUERY_TYPES)
        config = {
            "cases": [
                {
                    "id": "mh1",
                    "query": "compare A and B across hops",
                    "query_type": "multi_hop",
                    "answerable": True,
                    "expected_doc_ids": ["doc_a", "doc_b"],
                }
            ]
        }
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as fh:
            yaml.safe_dump(config, fh)
            path = Path(fh.name)
        try:
            with self.assertRaises(ValueError):
                load_config(path)
        finally:
            path.unlink(missing_ok=True)


class TestGeneratorHallucination(unittest.TestCase):
    """5. generator_hallucination — claim ↔ citation alignment below 0.5."""

    def test_classifies_low_alignment(self) -> None:
        # Retrieval found the right doc (doc_a in evidence) but answer
        # term_match misses → accuracy=0.0 → is_failed=True. Claim text
        # has 0 token overlap with citation text → cca = 0.0 < 0.5.
        # No earlier branch matches → classifier lands on
        # generator_hallucination.
        case = {
            "id": "halluc_case",
            "query_type": "single_doc",
            "answerable": True,
            "expected_doc_ids": ["doc_a"],
            "expected_terms": ["budget"],
            "expected_citation_terms": ["budget"],
        }
        prediction = _prediction(
            answer_status="supported",
            # summary does NOT contain "budget" → term_match=False →
            # accuracy=0.0 (is_failed becomes True).
            summary="The amount is roughly one hundred million won.",
            claims=[
                {
                    "target": "budget",
                    "claim": "The amount is exactly one hundred million Korean won.",
                    "citations": [{"doc_id": "doc_a", "chunk_id": "doc_a:0", "page": 1}],
                }
            ],
            evidence=[
                {
                    "doc_id": "doc_a",
                    "chunk_id": "doc_a:0",
                    "text": "completely unrelated text about something else entirely",
                }
            ],
            abstained=False,
        )
        result = score_case(case, prediction)
        # Sanity: not a retrieval miss (doc_a IS in evidence).
        self.assertEqual(result["evidence_doc_ids"], ["doc_a"])
        # Sanity: failed (accuracy != 1.0).
        self.assertNotEqual(result["accuracy"], 1.0)
        cca = result["claim_citation_alignment"]
        self.assertIsNotNone(cca, "Fixture must produce a non-None claim_citation_alignment")
        self.assertLess(cca, 0.5, f"Fixture must drive cca < 0.5 (got {cca})")
        self.assertEqual(classify_failure(result), "generator_hallucination")


class TestUnknown(unittest.TestCase):
    """7. unknown — failed but no other branch matched.

    Easiest fixture: boundary_partial (answerable=False + abstained=True +
    has_evidence) — v1 has no dedicated category for this.
    """

    def test_classifies_boundary_partial_as_unknown(self) -> None:
        case = {
            "id": "boundary_partial_case",
            "query_type": "abstention",
            "answerable": False,
            "expected_doc_ids": [],
            "expected_terms": [],
            "expected_citation_terms": [],
        }
        prediction = _prediction(
            answer_status="insufficient",
            summary="",
            claims=[],
            evidence=[{"doc_id": "doc_x", "chunk_id": "doc_x:0", "text": "noise"}],
            abstained=True,
        )
        result = score_case(case, prediction)
        # Sanity: is_failed must be True for boundary_partial.
        self.assertTrue(is_failed(result))
        self.assertEqual(classify_failure(result), "unknown")


class TestSuccessfulAnswerableReturnsNone(unittest.TestCase):
    """Boundary 1 — successful answerable case → None (excluded from counts)."""

    def test_returns_none(self) -> None:
        case = {
            "id": "success_answerable",
            "query_type": "single_doc",
            "answerable": True,
            "expected_doc_ids": ["doc_a"],
            "expected_terms": ["budget"],
            "expected_citation_terms": ["budget"],
        }
        prediction = _prediction(
            answer_status="supported",
            summary="The budget is 100M KRW.",
            claims=[
                {
                    "target": "budget",
                    "text": "The budget is 100M KRW.",
                    "citations": [{"doc_id": "doc_a", "chunk_id": "doc_a:0", "page": 1}],
                }
            ],
            evidence=[{"doc_id": "doc_a", "chunk_id": "doc_a:0", "text": "budget 100M KRW"}],
            abstained=False,
        )
        result = score_case(case, prediction)
        self.assertEqual(result["accuracy"], 1.0)
        self.assertFalse(is_failed(result))
        self.assertIsNone(classify_failure(result))


class TestSuccessfulCorrectRefusalReturnsNone(unittest.TestCase):
    """Boundary 2 — correct_refusal (unanswerable + abstained + no evidence) → None."""

    def test_returns_none(self) -> None:
        case = {
            "id": "success_correct_refusal",
            "query_type": "abstention",
            "answerable": False,
            "expected_doc_ids": [],
            "expected_terms": [],
            "expected_citation_terms": [],
        }
        prediction = _prediction(
            answer_status="insufficient",
            summary="",
            claims=[],
            evidence=[],
            abstained=True,
        )
        result = score_case(case, prediction)
        self.assertFalse(is_failed(result))
        self.assertIsNone(classify_failure(result))


class TestAggregateFailureCategoriesIntegration(unittest.TestCase):
    """Integration — mirror the 5-case mix from test_scorers_case_abstention.py.

    Expected after running through ``aggregate_failure_categories``:

    * c1 (answerable + correct) → None (excluded)
    * c2 (answerable + refused without term_match) → ``retrieval_miss``
      (expected doc_b never reached evidence)
    * c3 (correct_refusal) → None (excluded)
    * c4 (boundary_partial) → ``unknown``
    * c5 (unanswerable + answered) → ``verifier_false_negative``

    Pins:

    * ``verifier_false_negative`` count == 1 (= the c5 case).
    * ``retrieval_miss`` count == 1 (= the c2 case).
    * ``unknown`` count == 1 (= the c4 case).
    * All other categories count == 0.
    * Sum of counts == 3 (= ``is_failed`` true for 3 of 5 cases).

    A future regression that reorders branches such that c5 is no longer
    in ``verifier_false_negative`` flips this — the assertion message
    points reviewers to the Phase 5 audit finding #1 contract directly.
    """

    def _scored_case_results(self) -> list[dict[str, object]]:
        cases_and_predictions = [
            # 1. answerable + correct
            (
                {
                    "id": "c1",
                    "query_type": "single_doc",
                    "answerable": True,
                    "expected_doc_ids": ["doc_a"],
                    "expected_terms": ["budget"],
                    "expected_citation_terms": ["budget"],
                },
                _prediction(
                    answer_status="supported",
                    summary="The budget is 100M KRW.",
                    claims=[
                        {
                            "target": "budget",
                            "text": "The budget is 100M KRW.",
                            "citations": [
                                {"doc_id": "doc_a", "chunk_id": "doc_a:0", "page": 1}
                            ],
                        }
                    ],
                    evidence=[
                        {"doc_id": "doc_a", "chunk_id": "doc_a:0", "text": "budget 100M KRW"}
                    ],
                ),
            ),
            # 2. answerable + refused (no term_match, no evidence)
            (
                {
                    "id": "c2",
                    "query_type": "single_doc",
                    "answerable": True,
                    "expected_doc_ids": ["doc_b"],
                    "expected_terms": ["deadline"],
                    "expected_citation_terms": ["deadline"],
                },
                _prediction(answer_status="insufficient", abstained=True),
            ),
            # 3. unanswerable + correct_refusal
            (
                {
                    "id": "c3",
                    "query_type": "abstention",
                    "answerable": False,
                    "expected_doc_ids": [],
                    "expected_terms": [],
                    "expected_citation_terms": [],
                },
                _prediction(answer_status="insufficient", abstained=True),
            ),
            # 4. unanswerable + boundary_partial
            (
                {
                    "id": "c4",
                    "query_type": "abstention",
                    "answerable": False,
                    "expected_doc_ids": [],
                    "expected_terms": [],
                    "expected_citation_terms": [],
                },
                _prediction(
                    answer_status="insufficient",
                    evidence=[
                        {"doc_id": "doc_x", "chunk_id": "doc_x:0", "text": "noise"}
                    ],
                    abstained=True,
                ),
            ),
            # 5. unanswerable + incorrect_answer (Phase 5 finding #1 shape)
            (
                {
                    "id": "c5",
                    "query_type": "abstention",
                    "answerable": False,
                    "expected_doc_ids": [],
                    "expected_terms": [],
                    "expected_citation_terms": [],
                },
                _prediction(
                    answer_status="supported",
                    summary="fabricated.",
                    claims=[
                        {
                            "target": "fake_target",
                            "text": "fabricated.",
                            "citations": [
                                {"doc_id": "doc_y", "chunk_id": "doc_y:0", "page": 1}
                            ],
                        }
                    ],
                    evidence=[
                        {"doc_id": "doc_y", "chunk_id": "doc_y:0", "text": "noise"}
                    ],
                ),
            ),
        ]
        return [score_case(c, p) for c, p in cases_and_predictions]

    def test_counts_match_first_match_ordering(self) -> None:
        case_results = self._scored_case_results()
        counts = aggregate_failure_categories(case_results)

        # All 7 keys present.
        self.assertEqual(set(counts.keys()), set(FAILURE_CATEGORIES))

        # Phase 5 audit finding #1 contract — c5 must accumulate here.
        self.assertEqual(
            counts["verifier_false_negative"],
            1,
            "Phase 5 audit (#992) finding #1: unanswerable+answered cases "
            "MUST land in verifier_false_negative; if this fails, the "
            "first-match-wins ordering in classify_failure has been broken.",
        )
        self.assertEqual(counts["retrieval_miss"], 1, "c2 (no expected doc) must land here")
        self.assertEqual(counts["unknown"], 1, "c4 (boundary_partial) must land here in v1")

        # Empty categories.
        for category in (
            "planner_under_decomposition",
            "verifier_false_positive",
            "generator_hallucination",
            "context_dilution",  # v1 disabled
        ):
            self.assertEqual(
                counts[category],
                0,
                f"Fixture does not exercise {category}; count must be 0",
            )

        # Sum check — 3 of 5 cases are failures.
        self.assertEqual(sum(counts.values()), 3)


if __name__ == "__main__":
    unittest.main()
