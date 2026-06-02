"""Regression: agentic confidence emission + ADR 0001 naive guard (issue #1820).

ADR 0098: the agentic answer path (``verifier_retry=True``) emits a
``confidence`` ∈ [0,1] field that the ADR 0048 ``abstention_calibration``
block consumes; the naive_baseline path (``verifier_retry=False``) never
emits it because the verifier signals it derives from do not exist there,
so the ADR 0001 byte-identical answer dict is preserved by construction.

Pins:

1. ``generate_answer(emit_confidence=True)`` adds a float ``confidence``
   ∈ [0,1]; ``emit_confidence=False`` (the naive path) omits the key — and
   ``confidence`` is the *only* key difference between the two dicts.
2. ``_answer_confidence`` is the U-shaped 4-tier map ADR 0098 specifies
   (strong answer & strong abstention high, ambiguous middle low) and is
   deterministic.
3. The emitted values flow through ``_abstention_calibration`` under the
   ``P(decision correct)`` semantic of ``_calibration_correctness`` — a
   confident ``no_evidence`` abstention on a truly-unanswerable case that
   did abstain is a *correct* high-confidence decision.

The companion ADR 0001 byte-shape guard is
``test_answer_contract_snapshot.py``, which must stay green *unmodified*:
``confidence`` is excluded from the pinned contract subset (like
``analysis`` / ``plan``).
"""
from __future__ import annotations

import unittest

from eval.run_eval import _abstention_calibration, _calibration_correctness
from rag_answer import _answer_confidence, generate_answer
from rag_answer_schema import (
    ANSWER_STATUS_INSUFFICIENT,
    ANSWER_STATUS_PARTIAL,
    ANSWER_STATUS_SUPPORTED,
)


def _analysis() -> dict[str, object]:
    # Minimal single-doc analysis; empty evidence drives the INSUFFICIENT
    # branch. The emit gate is status-agnostic — it keys off
    # ``emit_confidence``, not the status — so this is enough to exercise
    # the gate on both paths. Returned fresh per call so a mutation inside
    # ``generate_answer`` can never leak across cases.
    return {"query_type": "single_doc", "topic": "예산"}


class TestConfidenceEmissionGate(unittest.TestCase):
    def test_agentic_emits_float_confidence_in_unit_range(self) -> None:
        answer, _text, _abstained = generate_answer(
            "예산이 얼마야?", _analysis(), [], False, [],
            emit_confidence=True,
        )
        self.assertIn("confidence", answer)
        self.assertIsInstance(answer["confidence"], float)
        self.assertGreaterEqual(answer["confidence"], 0.0)
        self.assertLessEqual(answer["confidence"], 1.0)

    def test_naive_path_omits_confidence_key(self) -> None:
        # emit_confidence=False is the naive_baseline path
        # (verifier_retry=False). ADR 0001: the answer dict must stay
        # byte-identical, so the key is absent — not present-and-null.
        answer, _text, _abstained = generate_answer(
            "예산이 얼마야?", _analysis(), [], False, [],
            emit_confidence=False,
        )
        self.assertNotIn("confidence", answer)

    def test_confidence_is_the_only_key_difference(self) -> None:
        # The agentic dict differs from the naive dict by exactly the one
        # additive key — proof the field is purely additive (ADR 0003) and
        # nothing else shifts when the gate opens.
        agentic, _t1, _a1 = generate_answer(
            "예산이 얼마야?", _analysis(), [], False, [], emit_confidence=True,
        )
        naive, _t2, _a2 = generate_answer(
            "예산이 얼마야?", _analysis(), [], False, [], emit_confidence=False,
        )
        self.assertEqual(set(agentic) - set(naive), {"confidence"})
        self.assertEqual(set(naive) - set(agentic), set())

    def test_emission_does_not_change_answer_text(self) -> None:
        # confidence is added *after* render_answer_text, so the rendered
        # answer text must be identical with and without emission.
        _a1, text_on, _o1 = generate_answer(
            "예산이 얼마야?", _analysis(), [], False, [], emit_confidence=True,
        )
        _a2, text_off, _o2 = generate_answer(
            "예산이 얼마야?", _analysis(), [], False, [], emit_confidence=False,
        )
        self.assertEqual(text_on, text_off)

    def test_emission_is_deterministic(self) -> None:
        a1, _t1, _o1 = generate_answer(
            "예산이 얼마야?", _analysis(), [], False, [], emit_confidence=True,
        )
        a2, _t2, _o2 = generate_answer(
            "예산이 얼마야?", _analysis(), [], False, [], emit_confidence=True,
        )
        self.assertEqual(a1["confidence"], a2["confidence"])


class TestAnswerConfidenceMap(unittest.TestCase):
    def test_u_shape_four_tiers(self) -> None:
        # The first-pass hypothesis values ADR 0098 pins. A follow-up may
        # tune them from calibration data, but the tier *ordering* (the
        # U-shape) is the load-bearing invariant — pinned separately below.
        self.assertEqual(_answer_confidence(ANSWER_STATUS_SUPPORTED, []), 0.90)
        self.assertEqual(_answer_confidence(ANSWER_STATUS_PARTIAL, []), 0.45)
        self.assertEqual(
            _answer_confidence(ANSWER_STATUS_INSUFFICIENT, ["no_evidence"]), 0.85
        )
        self.assertEqual(
            _answer_confidence(ANSWER_STATUS_INSUFFICIENT, ["low_top_score"]), 0.55
        )
        # Any other insufficient reason falls in the ambiguous middle.
        self.assertEqual(_answer_confidence(ANSWER_STATUS_INSUFFICIENT, []), 0.55)
        self.assertEqual(
            _answer_confidence(ANSWER_STATUS_INSUFFICIENT, ["topic_not_grounded"]),
            0.55,
        )

    def test_always_in_unit_range(self) -> None:
        for status in (
            ANSWER_STATUS_SUPPORTED,
            ANSWER_STATUS_PARTIAL,
            ANSWER_STATUS_INSUFFICIENT,
        ):
            for reasons in (
                [],
                ["no_evidence"],
                ["low_top_score"],
                ["topic_not_grounded"],
            ):
                with self.subTest(status=status, reasons=reasons):
                    c = _answer_confidence(status, reasons)
                    self.assertGreaterEqual(c, 0.0)
                    self.assertLessEqual(c, 1.0)

    def test_u_shape_extremes_exceed_ambiguous_middle(self) -> None:
        # The structural invariant that survives value tuning: a strong
        # answer and a confident no_evidence abstention both outrank the
        # ambiguous middle (partial answer, weak-evidence abstention).
        strong_answer = _answer_confidence(ANSWER_STATUS_SUPPORTED, [])
        strong_abstain = _answer_confidence(
            ANSWER_STATUS_INSUFFICIENT, ["no_evidence"]
        )
        weak_answer = _answer_confidence(ANSWER_STATUS_PARTIAL, [])
        weak_abstain = _answer_confidence(
            ANSWER_STATUS_INSUFFICIENT, ["low_top_score"]
        )
        for high in (strong_answer, strong_abstain):
            for low in (weak_answer, weak_abstain):
                with self.subTest(high=high, low=low):
                    self.assertGreater(high, low)


class TestConfidenceCalibrationFlow(unittest.TestCase):
    def test_null_block_without_confidence(self) -> None:
        # naive_baseline / pre-0098 snapshots carry no confidence → the
        # calibration block is None (ADR 0048 forward-compat), not a
        # misleading zeroed dict.
        case_results = [{"answerable": True, "accuracy": 1.0, "abstention": None}]
        self.assertIsNone(_abstention_calibration(case_results))

    def test_confident_correct_abstention_is_well_aligned(self) -> None:
        # End-to-end semantic: a confident no_evidence abstention (0.85) on
        # a truly-unanswerable case that DID abstain →
        # _calibration_correctness = 1.0. The (0.85, 1.0) pair yields a
        # small Brier — the P(decision correct) semantic lines up.
        conf = _answer_confidence(ANSWER_STATUS_INSUFFICIENT, ["no_evidence"])
        result = {
            "answerable": False,
            "abstention": 1.0,
            "accuracy": None,
            "confidence": conf,
        }
        self.assertEqual(_calibration_correctness(result), 1.0)
        block = _abstention_calibration([result])
        self.assertIsNotNone(block)
        assert block is not None  # narrow for the type checker
        self.assertEqual(block["n"], 1)
        # brier = (0.85 - 1.0)^2
        self.assertAlmostEqual(block["brier"], (conf - 1.0) ** 2, places=9)

    def test_exact_ece_brier_over_known_pairs(self) -> None:
        # Two singleton bins, hand-computed against the ADR 0098 emit
        # values, so the calibration math and the emit map are pinned
        # together:
        #   supported answer that was correct → (0.90, 1.0), bin 9
        #   partial answer that was wrong     → (0.45, 0.0), bin 4
        # ece   = 0.5*|1.0-0.90| + 0.5*|0.0-0.45| = 0.05 + 0.225 = 0.275
        # brier = ((0.90-1.0)^2 + (0.45-0.0)^2)/2 = (0.01+0.2025)/2 = 0.10625
        supported = _answer_confidence(ANSWER_STATUS_SUPPORTED, [])
        partial = _answer_confidence(ANSWER_STATUS_PARTIAL, [])
        case_results = [
            {
                "answerable": True,
                "accuracy": 1.0,
                "abstention": None,
                "confidence": supported,
            },
            {
                "answerable": True,
                "accuracy": 0.0,
                "abstention": None,
                "confidence": partial,
            },
        ]
        block = _abstention_calibration(case_results)
        assert block is not None  # narrow for the type checker
        self.assertEqual(block["n"], 2)
        self.assertAlmostEqual(block["ece"], 0.275, places=9)
        self.assertAlmostEqual(block["brier"], 0.10625, places=9)


if __name__ == "__main__":
    unittest.main()
