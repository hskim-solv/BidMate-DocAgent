"""ADR 0054 — conditional-on-answer scorer semantics regression guard.

Locks in the fix for the Goodhart trap surfaced by PR #946's first
distinguishing-power gauge measurement at n=221: the pre-fix
``eval/scorers/case.py:89-91`` branch assigned vacuous-truth 1.0 to
``groundedness`` / ``citation_precision`` for the (unanswerable AND
abstained AND no-evidence) path. Coupled with the answer-format scorer's
trivially-passing checks on empty claims, this double-counted the
already-measured ``abstention`` rate + ``abstention_outcomes`` 3-bin
(PR #464) and inflated quality means on high-abstention runs (e.g.
random_retrieval at ~89% abstention).

Per ADR 0054:

* Quality metrics (``accuracy``, ``groundedness``, ``citation_precision``,
  ``answer_format_compliance``) are measured **only on substantive answer
  attempts** (``answerable=True`` — for accuracy/groundedness/
  citation_precision; or ``not (unanswerable AND abstained AND no evidence)``
  — for answer_format_compliance).
* The unanswerable + abstained + no-evidence path returns ``None`` for
  those metrics → ``metric_block`` excludes them from the denominator
  (eval/run_eval.py:470-516 already has the None-filter pattern wired).
* Refusal correctness stays measured exclusively by ``abstention`` (rate)
  + ``abstention_outcomes`` 3-bin.

The 5 unit cases below cover the cartesian (answerable × abstained ×
evidence-present) corners that matter; the 6th integration case asserts
``metric_block`` correctly excludes None scores from the substantive
subset average.
"""
from __future__ import annotations

import unittest

from eval.run_eval import metric_block
from eval.scorers.case import score_case


def _prediction(
    *,
    answer_status: str,
    summary: str = "",
    claims: list[dict[str, object]] | None = None,
    evidence: list[dict[str, object]] | None = None,
    abstained: bool = False,
) -> dict[str, object]:
    """Build a prediction dict matching ADR 0003 answer-contract schema_version=2.

    Mirrors the shape ``rag_answer.run_rag_query`` emits — kept terse here so
    the test cases below stay readable; only the fields ``score_case``
    actually reads are populated.
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
            "filter_stage_attempts": [],
            "stage_latency": {},
            "retrieved_chunk_ids": [],
        },
        "plan": {},
        "analysis": {},
    }


class TestAnswerableSubstantiveAnswerCorrect(unittest.TestCase):
    """Case 1 — answerable=True, abstained=False, fully correct.

    Regression guard: the ADR 0054 fix must NOT alter the answerable path.
    Pre-fix and post-fix scoring must be identical here.
    """

    def test_quality_metrics_at_one_abstention_none(self) -> None:
        case = {
            "id": "case_substantive_correct",
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
        self.assertEqual(result["groundedness"], 1.0)
        self.assertEqual(result["citation_precision"], 1.0)
        # Abstention 메트릭은 unanswerable 케이스에서만 measured.
        self.assertIsNone(result["abstention"])
        # answer_format_compliance 는 substantive 답변 시도이므로 유지.
        self.assertEqual(result["answer_format_compliance"], 1.0)


class TestAnswerableButAbstainedIncorrectly(unittest.TestCase):
    """Case 2 — answerable=True, abstained=True (model refused when shouldn't).

    The model gave up on an answerable case. Quality metrics correctly
    *penalize* this with 0.0 (NOT None — these cases ARE substantive
    attempts that simply failed). Abstention stays None because we only
    measure refusal correctness on the unanswerable subset.
    """

    def test_quality_metrics_zero_abstention_none(self) -> None:
        case = {
            "id": "case_answerable_but_refused",
            "query_type": "single_doc",
            "answerable": True,
            "expected_doc_ids": ["doc_a"],
            "expected_terms": ["budget"],
            "expected_citation_terms": ["budget"],
        }
        prediction = _prediction(
            answer_status="insufficient",
            summary="",
            claims=[],
            evidence=[],
            abstained=True,
        )
        result = score_case(case, prediction)
        # Answerable but the model refused → 0.0 quality (not None).
        self.assertEqual(result["accuracy"], 0.0)
        self.assertEqual(result["groundedness"], 0.0)
        # citation_precision: no evidence_doc_ids → 0.0 (citation_doc_precision branch).
        self.assertEqual(result["citation_precision"], 0.0)
        # Abstention measured only on unanswerable subset.
        self.assertIsNone(result["abstention"])


class TestUnanswerableCorrectRefusal(unittest.TestCase):
    """Case 3 — answerable=False, abstained=True, no evidence (correct_refusal).

    **This is the heart of the ADR 0054 fix.** Pre-fix this case got a
    vacuous-truth 1.0 on groundedness + citation_precision +
    answer_format_compliance — double-counting the abstention signal.
    Post-fix: those three are None (excluded from the substantive-mean),
    and abstention alone correctly carries the refusal-correctness signal.
    """

    def test_quality_metrics_none_abstention_one(self) -> None:
        case = {
            "id": "case_correct_refusal",
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
        # Quality metrics are N/A for non-substantive cases.
        self.assertIsNone(
            result["accuracy"],
            "accuracy must be None on the correct_refusal path",
        )
        self.assertIsNone(
            result["groundedness"],
            "ADR 0054: groundedness must be None (was vacuously 1.0 pre-fix)",
        )
        self.assertIsNone(
            result["citation_precision"],
            "ADR 0054: citation_precision must be None (was vacuously 1.0 pre-fix)",
        )
        self.assertIsNone(
            result["answer_format_compliance"],
            "ADR 0054: answer_format_compliance must be None on correct_refusal "
            "(was vacuously 1.0 — insufficient + empty claims + min_claims=0 "
            "trivially satisfied every check)",
        )
        # Refusal correctness measured here.
        self.assertEqual(result["abstention"], 1.0)


class TestUnanswerableBoundaryPartial(unittest.TestCase):
    """Case 4 — answerable=False, abstained=True, has evidence (boundary_partial).

    Model refused but still attached evidence — neither clean refusal nor
    substantive answer. Quality metrics still None (ADR 0054 — this is
    NOT a substantive answer attempt); abstention=1.0 (model did refuse).
    answer_format_compliance stays computed (not None) because evidence is
    present → not the empty-claims vacuous path.
    """

    def test_quality_metrics_none_format_compliance_computed(self) -> None:
        case = {
            "id": "case_boundary_partial",
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
            evidence=[{"doc_id": "doc_x", "chunk_id": "doc_x:0", "text": "unrelated noise"}],
            abstained=True,
        )
        result = score_case(case, prediction)
        self.assertIsNone(result["groundedness"])
        self.assertIsNone(result["citation_precision"])
        # answer_format_compliance: evidence present → format_compliance computed
        # (NOT the (unanswerable AND abstained AND no-evidence) post-process branch).
        self.assertIsNotNone(result["answer_format_compliance"])
        self.assertEqual(result["abstention"], 1.0)


class TestUnanswerableIncorrectAnswer(unittest.TestCase):
    """Case 5 — answerable=False, abstained=False (incorrect_answer).

    Model hallucinated an answer to an unanswerable query — a failure mode.
    Quality metrics None (not a substantive attempt against any gold
    answer — there isn't one); abstention=0.0 (model should have refused
    but didn't).
    """

    def test_quality_none_abstention_zero(self) -> None:
        case = {
            "id": "case_incorrect_answer",
            "query_type": "abstention",
            "answerable": False,
            "expected_doc_ids": [],
            "expected_terms": [],
            "expected_citation_terms": [],
        }
        prediction = _prediction(
            answer_status="supported",
            summary="The answer is XYZ.",
            claims=[
                {
                    "target": "fake_target",
                    "text": "The answer is XYZ.",
                    "citations": [{"doc_id": "doc_y", "chunk_id": "doc_y:0", "page": 1}],
                }
            ],
            evidence=[{"doc_id": "doc_y", "chunk_id": "doc_y:0", "text": "noise"}],
            abstained=False,
        )
        result = score_case(case, prediction)
        self.assertIsNone(result["groundedness"])
        self.assertIsNone(result["citation_precision"])
        # No abstention happened → 0.0 on the abstention metric.
        self.assertEqual(result["abstention"], 0.0)


class TestMetricBlockExcludesNoneFromSubstantiveMean(unittest.TestCase):
    """Case 6 — integration: ``metric_block`` excludes None from the mean.

    Builds a mixed 5-case case-results list (1 substantive-correct, 1
    answerable-but-refused, 1 correct_refusal, 1 boundary_partial, 1
    incorrect_answer) — same composition as case_results that
    ``eval/run_eval.py`` builds — and asserts:

    * ``num_predictions`` = 5 (all cases counted in the cardinality).
    * ``accuracy`` mean = mean of 2 substantive answerable cases (1.0, 0.0)
      = 0.5. The three unanswerable cases (whose accuracy is None) are
      excluded from the denominator.
    * ``groundedness`` mean = 0.5 (same denominator under ADR 0054).
    * ``abstention`` mean = mean of 3 unanswerable cases (1.0, 1.0, 0.0)
      = 2/3 ≈ 0.6666. This is the correct-refusal-rate-on-unanswerable.

    The pre-ADR-0054 expectation would have been ``groundedness ≈ 0.75``
    (2 unanswerable+abstained cases each contributing 1.0 vacuously);
    asserting 0.5 here proves the inflation is gone.
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
            # 2. answerable + refused (penalized 0.0)
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
            # 3. unanswerable + correct refusal (was vacuous 1.0 pre-fix)
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
            # 4. unanswerable + boundary_partial (abstained but with evidence)
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
            # 5. unanswerable + incorrect_answer
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

    def test_metric_block_substantive_mean(self) -> None:
        case_results = self._scored_case_results()
        block = metric_block(case_results)
        # Cardinality is total (all 5 cases counted).
        self.assertEqual(block["num_predictions"], 5)
        # Quality means on the 2 answerable cases only (1.0 + 0.0 = 0.5).
        # Pre-ADR-0054 groundedness would have been ≈ 0.75 due to the
        # vacuous 1.0 from cases #3 + #4. Asserting 0.5 here is the
        # regression guard against that inflation.
        self.assertAlmostEqual(block["accuracy"], 0.5, places=6)
        self.assertAlmostEqual(block["groundedness"], 0.5, places=6)
        # Abstention rate on the 3 unanswerable cases: (1 + 1 + 0) / 3.
        self.assertAlmostEqual(block["abstention"], 2 / 3, places=6)
        # 3-bin decomposition is intact (PR #464 surface).
        outcomes = block["abstention_outcomes"]
        self.assertEqual(outcomes["correct_refusal"], 1)
        self.assertEqual(outcomes["boundary_partial"], 1)
        self.assertEqual(outcomes["incorrect_answer"], 1)


if __name__ == "__main__":
    unittest.main()
