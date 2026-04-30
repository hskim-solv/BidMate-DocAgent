import unittest
from pathlib import Path

from rag_core import build_index_payload, build_index_payload_from_documents, run_rag_query


class FuzzyMetadataRetrievalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_index_payload(
            Path("data/raw"),
            embedding_backend="hashing",
        )

    def test_spacing_variant_matches_exact_agency(self) -> None:
        result = run_rag_query(self.index, "기관A의 보안 통제 요구사항은?")

        self.assertEqual(["기관 A"], result["analysis"]["entities"])
        self.assertEqual(["rfp-agency-a-ai-quality"], result["analysis"]["matched_doc_ids"])
        self.assertEqual("strict", result["plan"]["filter_stage"])
        self.assertEqual(
            ["rfp-agency-a-ai-quality"],
            result["plan"]["metadata_filters"]["doc_ids"],
        )

    def test_abbreviation_query_keeps_both_comparison_sides(self) -> None:
        result = run_rag_query(self.index, "A와 B의 AI 요구사항 차이 알려줘")

        self.assertEqual("comparison", result["analysis"]["query_type"])
        self.assertEqual(
            {"rfp-agency-a-ai-quality", "rfp-agency-b-mlops-governance"},
            set(result["analysis"]["matched_doc_ids"]),
        )
        self.assertEqual("reduced", result["plan"]["filter_stage"])
        self.assertEqual(
            {"rfp-agency-a-ai-quality", "rfp-agency-b-mlops-governance"},
            {item["doc_id"] for item in result["evidence"]},
        )

    def test_partial_project_query_matches_project_metadata(self) -> None:
        result = run_rag_query(
            self.index,
            "품질관리 플랫폼과 MLOps 자동화의 AI 요구사항 차이 알려줘",
        )

        self.assertEqual("comparison", result["analysis"]["query_type"])
        self.assertEqual(
            {"AI 품질관리 플랫폼 구축", "데이터 거버넌스 및 MLOps 자동화"},
            set(result["analysis"]["matched_projects"]),
        )
        self.assertEqual("reduced", result["plan"]["filter_stage"])
        self.assertEqual(
            {"rfp-agency-a-ai-quality", "rfp-agency-b-mlops-governance"},
            set(result["plan"]["metadata_filters"]["doc_ids"]),
        )

    def test_ambiguous_metadata_keeps_close_candidates(self) -> None:
        ambiguous_index = build_index_payload_from_documents(
            [
                {
                    "doc_id": "alpha-research",
                    "title": "Alpha Research Center 보안 시스템 RFP",
                    "agency": "Alpha Research Center",
                    "project": "보안 시스템",
                    "metadata": {},
                    "sections": [{"heading": "본문", "text": "Alpha Research Center는 보안 로그를 요구한다."}],
                    "source_path": "alpha-research.txt",
                },
                {
                    "doc_id": "alpha-regional",
                    "title": "Alpha Regional Center 보안 시스템 RFP",
                    "agency": "Alpha Regional Center",
                    "project": "보안 시스템",
                    "metadata": {},
                    "sections": [{"heading": "본문", "text": "Alpha Regional Center는 보안 통제를 요구한다."}],
                    "source_path": "alpha-regional.txt",
                },
            ],
            source_dir="test-fixture",
            embedding_backend="hashing",
        )

        result = run_rag_query(ambiguous_index, "Alpha Center 보안 요구사항은?", top_k=4)

        self.assertEqual("single_doc", result["analysis"]["query_type"])
        self.assertTrue(result["analysis"]["metadata_ambiguous"])
        self.assertEqual(
            {"alpha-research", "alpha-regional"},
            set(result["analysis"]["matched_doc_ids"]),
        )
        self.assertEqual(
            {"alpha-research", "alpha-regional"},
            set(result["plan"]["metadata_filters"]["doc_ids"]),
        )

    def test_retry_relaxes_filters_when_verifier_rejects_evidence(self) -> None:
        result = run_rag_query(self.index, "기관 A의 블록체인 납품 실적은?")

        self.assertTrue(result["diagnostics"]["abstained"])
        self.assertGreaterEqual(result["diagnostics"]["retry_count"], 1)
        self.assertEqual(
            ["strict", "relaxed"],
            [attempt["stage"] for attempt in result["diagnostics"]["filter_stage_attempts"]],
        )
        self.assertEqual("relaxed", result["plan"]["filter_stage"])


if __name__ == "__main__":
    unittest.main()
