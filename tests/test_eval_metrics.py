import unittest

from eval.run_eval import score_case


class EvalMetricsTest(unittest.TestCase):
    def test_scores_retrieval_quality_independent_of_answer(self) -> None:
        case = {
            "id": "retrieval-rank",
            "query_type": "single_doc",
            "query": "기관 A 보안 요구사항은?",
            "expected_doc_ids": ["expected-doc"],
            "expected_terms": ["보안"],
            "expected_citation_terms": ["보안"],
            "expected_claim_targets": ["기관 A"],
            "answerable": True,
        }
        prediction = {
            "answer": {
                "status": "supported",
                "claims": [
                    {
                        "target": "기관 A",
                        "claim": "보안 요구사항은 접근 통제이다.",
                        "support": "보안 요구사항은 접근 통제이다.",
                        "citations": [{"doc_id": "expected-doc", "chunk_id": "chunk-2"}],
                    }
                ],
            },
            "answer_text": "보안 요구사항은 접근 통제이다.",
            "evidence": [
                {"doc_id": "expected-doc", "text": "보안 요구사항은 접근 통제이다."}
            ],
            "diagnostics": {
                "abstained": False,
                "filter_stage_attempts": [
                    {
                        "verified": True,
                        "retrieved_ranked_refs": [
                            {"rank": 1, "doc_id": "other-doc", "chunk_id": "chunk-1"},
                            {"rank": 2, "doc_id": "expected-doc", "chunk_id": "chunk-2"},
                        ],
                    }
                ],
            },
        }

        result = score_case(case, prediction)

        self.assertEqual(0.0, result["retrieval_recall_at_1"])
        self.assertEqual(1.0, result["retrieval_recall_at_3"])
        self.assertEqual(0.5, result["retrieval_mrr"])
        self.assertEqual({"expected-doc": 2}, result["expected_doc_ranks"])
        self.assertEqual([], result["retrieval_missed_doc_ids"])


if __name__ == "__main__":
    unittest.main()
