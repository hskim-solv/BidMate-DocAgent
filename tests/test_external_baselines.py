"""Contract tests for the ADR 0009 external baseline comparison.

The comparison is *asymmetric by design* — the symmetric metric subset
(accuracy, retrieval_recall, latency) is the only fair comparison
surface; structured-citation metrics get null entries with a note that
points readers to the ADR.

These tests lock four things:

1. The stub backend's output schema matches what a real (LangChain /
   LlamaIndex) backend would produce — answer_text plus
   retrieved_doc_ids — so the scorer cannot drift apart between
   backends.
2. The asymmetric metric keys stay null, and the schema carries the
   explanatory note. Drift here would erase the methodology decision.
3. The corpus + cases loaders accept the real
   ``data/raw`` / ``eval/config.yaml`` so the script keeps working as
   those files evolve.
4. The committable aggregate never contains per-case LLM text — the
   ADR 0005 commit-boundary discipline applies here too.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
import sys
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.compare_external_baselines import (
    ASYMMETRIC_KEYS,
    DEFAULT_CONFIG_PATH,
    DEFAULT_CORPUS_DIR,
    chunk_text,
    load_cases,
    load_corpus,
    run_comparison,
    score_case,
)


class ExternalBaselineUnitTest(unittest.TestCase):
    def test_chunk_text_respects_overlap(self) -> None:
        chunks = chunk_text("a" * 1000, chunk_size=300, overlap=50)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 300)

    def test_chunk_text_empty_input_returns_empty(self) -> None:
        self.assertEqual(chunk_text("", chunk_size=300, overlap=50), [])

    def test_score_accuracy_answerable_doc_and_term_hit(self) -> None:
        case = {
            "answerable": True,
            "expected_doc_ids": ["rfp-a"],
            "expected_terms": ["보안 통제", "로그"],
        }
        result = {
            "answer_text": "기관 A는 보안 통제와 로그 추적이 필요하다",
            "retrieved_doc_ids": ["rfp-a", "rfp-b"],
        }
        scored = score_case(case, result)
        self.assertEqual(scored["accuracy"], 1.0)
        self.assertEqual(scored["retrieval_recall"], 1.0)

    def test_score_accuracy_term_miss(self) -> None:
        case = {
            "answerable": True,
            "expected_doc_ids": ["rfp-a"],
            "expected_terms": ["보안 통제"],
        }
        result = {"answer_text": "관련 정보가 없습니다.", "retrieved_doc_ids": ["rfp-a"]}
        self.assertEqual(score_case(case, result)["accuracy"], 0.0)

    def test_score_abstention_when_unanswerable(self) -> None:
        case = {"answerable": False, "expected_doc_ids": [], "expected_terms": []}
        result = {"answer_text": "근거 부족", "retrieved_doc_ids": []}
        self.assertEqual(score_case(case, result)["accuracy"], 1.0)

    def test_score_abstention_failure_when_unanswerable(self) -> None:
        case = {"answerable": False, "expected_doc_ids": [], "expected_terms": []}
        result = {"answer_text": "예, 가능합니다.", "retrieved_doc_ids": ["rfp-a"]}
        self.assertEqual(score_case(case, result)["accuracy"], 0.0)


class ExternalBaselineIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_cases(DEFAULT_CONFIG_PATH)
        cls.corpus = load_corpus(DEFAULT_CORPUS_DIR)

    def test_loads_real_cases_and_corpus(self) -> None:
        self.assertGreater(len(self.cases), 0)
        self.assertGreater(len(self.corpus), 0)
        # The corpus must carry the doc_id that the eval cases reference;
        # if these drift, the comparison silently scores nothing.
        case_doc_ids = {
            d for case in self.cases for d in (case.get("expected_doc_ids") or [])
        }
        corpus_doc_ids = {doc["doc_id"] for doc in self.corpus}
        missing = case_doc_ids - corpus_doc_ids
        self.assertFalse(
            missing,
            f"eval cases reference doc_ids not in corpus: {sorted(missing)}",
        )

    def test_stub_backend_runs_end_to_end(self) -> None:
        aggregate, local = run_comparison(self.cases, self.corpus, backend="stub")
        self.assertEqual(aggregate["backend"], "stub")
        self.assertEqual(aggregate["n_cases"], len(self.cases))
        self.assertIsNotNone(aggregate["metrics"]["accuracy"])
        self.assertEqual(len(local["cases"]), len(self.cases))

    def test_asymmetric_metrics_remain_null_with_note(self) -> None:
        aggregate, _ = run_comparison(self.cases, self.corpus, backend="stub")
        for key in ASYMMETRIC_KEYS:
            self.assertIn(key, aggregate["asymmetric_metrics"])
            self.assertIsNone(
                aggregate["asymmetric_metrics"][key],
                f"{key} must stay null — see ADR 0009 methodology",
            )
        self.assertIn("0009", aggregate["asymmetric_metrics_note"])

    def test_committable_aggregate_has_no_per_case_text(self) -> None:
        # ADR 0005 / ADR 0009 commit-boundary: the aggregate file must
        # not carry per-case LLM-generated text. A leak here would
        # publish RFP content under restrictive license terms.
        aggregate, _ = run_comparison(self.cases, self.corpus, backend="stub")
        serialized = json.dumps(aggregate, ensure_ascii=False)
        forbidden_substrings = ("answer_text", "case_results", "per_case", "raw_response")
        for substring in forbidden_substrings:
            self.assertNotIn(
                substring,
                serialized,
                f"Aggregate must not contain {substring!r} — ADR 0009 commit boundary",
            )

    def test_unknown_backend_raises(self) -> None:
        with self.assertRaises(ValueError):
            run_comparison(self.cases, self.corpus, backend="nope")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
