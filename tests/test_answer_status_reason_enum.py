"""Regression: answer["status_reason"]["code"] is a closed enum (issue #759).

RAG senior-review critique #2: ADR 0003 names the answer dict a
"contract" but the ``status_reason.code`` field used to accept any
string. Downstream consumers (synthetic judge, eval scorer, dashboard)
silently mis-bucketed unknown codes.

This test pins the four-value closed set defined in
``rag_answer_schema.KNOWN_ANSWER_STATUS_REASON_CODES`` and verifies:

1. Every code is reachable from a corresponding status (no dead enum).
2. An out-of-set override raises ``ValueError`` rather than flowing
   into the dict (silent acceptance is the bug we are fixing).
3. ``answer["status_reason"]["code"]`` produced by the default path
   is always inside the closed set, regardless of which status branch
   ``generate_answer`` takes.
"""

from __future__ import annotations

import unittest

from rag_answer import answer_status_reason
from rag_answer_schema import (
    ANSWER_STATUS_INSUFFICIENT,
    ANSWER_STATUS_PARTIAL,
    ANSWER_STATUS_REASON_CONTEXT_CLARIFICATION,
    ANSWER_STATUS_REASON_INSUFFICIENT_EVIDENCE,
    ANSWER_STATUS_REASON_METADATA_AMBIGUITY_CLARIFICATION,
    ANSWER_STATUS_REASON_PARTIAL_COMPARISON,
    ANSWER_STATUS_REASON_PARTIAL_TOPIC_GROUNDING,
    ANSWER_STATUS_REASON_VERIFIED,
    ANSWER_STATUS_SUPPORTED,
    KNOWN_ANSWER_STATUS_REASON_CODES,
)
from rag_verifier import PARTIAL_TOPIC_GROUNDING_REASON


class TestAnswerStatusReasonEnum(unittest.TestCase):
    def test_known_set_has_exactly_six_codes(self) -> None:
        # The contract is a closed six-value set: four reachable from
        # ``answer_status_reason``'s default branch (one per
        # status × partial subcase) plus two reachable via the
        # ``code=`` override the clarification surface uses. Adding a
        # seventh value here without bumping ANSWER_SCHEMA_VERSION +
        # updating ADR 0003 is the regression we want this test to
        # surface.
        self.assertEqual(
            KNOWN_ANSWER_STATUS_REASON_CODES,
            frozenset({
                ANSWER_STATUS_REASON_VERIFIED,
                ANSWER_STATUS_REASON_PARTIAL_TOPIC_GROUNDING,
                ANSWER_STATUS_REASON_PARTIAL_COMPARISON,
                ANSWER_STATUS_REASON_INSUFFICIENT_EVIDENCE,
                ANSWER_STATUS_REASON_CONTEXT_CLARIFICATION,
                ANSWER_STATUS_REASON_METADATA_AMBIGUITY_CLARIFICATION,
            }),
        )

    def test_supported_status_yields_verified_code(self) -> None:
        result = answer_status_reason(
            status=ANSWER_STATUS_SUPPORTED,
            verified=True,
            verification_reasons=[],
        )
        self.assertEqual(result["code"], ANSWER_STATUS_REASON_VERIFIED)
        self.assertIn(result["code"], KNOWN_ANSWER_STATUS_REASON_CODES)

    def test_partial_with_topic_grounding_yields_topic_code(self) -> None:
        result = answer_status_reason(
            status=ANSWER_STATUS_PARTIAL,
            verified=True,
            verification_reasons=[PARTIAL_TOPIC_GROUNDING_REASON],
        )
        self.assertEqual(
            result["code"], ANSWER_STATUS_REASON_PARTIAL_TOPIC_GROUNDING
        )
        self.assertIn(result["code"], KNOWN_ANSWER_STATUS_REASON_CODES)

    def test_partial_without_topic_grounding_yields_comparison_code(self) -> None:
        # The "other" partial path: comparison-coverage gaps, no
        # PARTIAL_TOPIC_GROUNDING_REASON in the reason list.
        result = answer_status_reason(
            status=ANSWER_STATUS_PARTIAL,
            verified=False,
            verification_reasons=["missing_requested_entity:foo"],
        )
        self.assertEqual(
            result["code"], ANSWER_STATUS_REASON_PARTIAL_COMPARISON
        )
        self.assertIn(result["code"], KNOWN_ANSWER_STATUS_REASON_CODES)

    def test_insufficient_status_yields_insufficient_evidence_code(self) -> None:
        result = answer_status_reason(
            status=ANSWER_STATUS_INSUFFICIENT,
            verified=False,
            verification_reasons=[],
        )
        self.assertEqual(
            result["code"], ANSWER_STATUS_REASON_INSUFFICIENT_EVIDENCE
        )
        self.assertIn(result["code"], KNOWN_ANSWER_STATUS_REASON_CODES)

    def test_clarification_codes_pass_through_via_override(self) -> None:
        # rag_clarification uses the ``code=`` override to disambiguate
        # *why* a query was abstained from. Both clarification codes
        # must be accepted (not rejected as unknown).
        for clarification_code in (
            ANSWER_STATUS_REASON_CONTEXT_CLARIFICATION,
            ANSWER_STATUS_REASON_METADATA_AMBIGUITY_CLARIFICATION,
        ):
            with self.subTest(code=clarification_code):
                result = answer_status_reason(
                    status=ANSWER_STATUS_INSUFFICIENT,
                    verified=False,
                    verification_reasons=["needs_clarification"],
                    code=clarification_code,
                )
                self.assertEqual(result["code"], clarification_code)
                self.assertIn(
                    result["code"], KNOWN_ANSWER_STATUS_REASON_CODES
                )

    def test_explicit_known_code_passes_through(self) -> None:
        # An override that names a known code should be accepted —
        # the validator only rejects unknown codes.
        for code in sorted(KNOWN_ANSWER_STATUS_REASON_CODES):
            with self.subTest(code=code):
                result = answer_status_reason(
                    status=ANSWER_STATUS_SUPPORTED,
                    verified=True,
                    verification_reasons=[],
                    code=code,
                )
                self.assertEqual(result["code"], code)

    def test_unknown_code_override_raises_valueerror(self) -> None:
        # The bug we are fixing: previously a typo or stale code
        # would flow into ``answer["status_reason"]["code"]`` and
        # downstream consumers silently mis-bucketed it. Now it
        # surfaces at the call site.
        with self.assertRaises(ValueError) as cm:
            answer_status_reason(
                status=ANSWER_STATUS_PARTIAL,
                verified=False,
                verification_reasons=[],
                code="not_a_real_code",
            )
        # Surface should mention what was given and what's allowed —
        # cheap diagnostic for the developer who hits this.
        message = str(cm.exception)
        self.assertIn("not_a_real_code", message)
        self.assertIn("verified", message)


if __name__ == "__main__":
    unittest.main()
