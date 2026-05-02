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

    def test_section_metadata_is_stored_on_chunks_and_evidence(self) -> None:
        chunk = self.index["chunks"][0]

        self.assertEqual("section", chunk["chunking_strategy"])
        self.assertEqual(["사업 개요"], chunk["section_path"])
        self.assertEqual(1, chunk["chunk_seq_in_section"])
        self.assertTrue(chunk["section_id"].startswith("rfp-agency-a-ai-quality::section-"))

        result = run_rag_query(self.index, "기관 A의 보안 통제 요구사항은?")
        evidence = result["evidence"][0]

        self.assertEqual(["AI 요구사항"], evidence["section_path"])
        self.assertEqual(evidence["section_id"], evidence["parent_section_id"])
        self.assertEqual("section", evidence["chunking_strategy"])

    def test_abbreviation_query_keeps_both_comparison_sides(self) -> None:
        result = run_rag_query(self.index, "A와 B의 AI 요구사항 차이 알려줘")

        self.assertEqual("comparison", result["analysis"]["query_type"])
        self.assertEqual("supported", result["answer"]["status"])
        self.assertEqual("comparison", result["answer"]["query_type"])
        self.assertIn("answer_text", result)
        self.assertEqual(
            {"기관 A", "기관 B"},
            {claim["target"] for claim in result["answer"]["claims"]},
        )
        self.assertTrue(
            all(claim["citations"][0]["chunk_id"] for claim in result["answer"]["claims"])
        )
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

    def test_partial_comparison_keeps_supported_claims_and_missing_target(self) -> None:
        partial_index = build_index_payload_from_documents(
            [
                {
                    "doc_id": "agency-x-security",
                    "title": "기관 X 보안 RFP",
                    "agency": "기관 X",
                    "project": "보안 사업",
                    "metadata": {},
                    "sections": [{"heading": "보안", "text": "기관 X는 보안 로그와 접근 통제를 요구한다."}],
                    "source_path": "agency-x.txt",
                },
                {
                    "doc_id": "agency-y-schedule",
                    "title": "기관 Y 운영 RFP",
                    "agency": "기관 Y",
                    "project": "운영 사업",
                    "metadata": {},
                    "sections": [{"heading": "운영", "text": "기관 Y는 일정 관리와 사용자 교육을 요구한다."}],
                    "source_path": "agency-y.txt",
                },
            ],
            source_dir="test-fixture",
            embedding_backend="hashing",
        )

        result = run_rag_query(partial_index, "기관 X와 기관 Y의 보안 요구사항 차이를 비교해줘")

        self.assertEqual("partial", result["answer"]["status"])
        self.assertFalse(result["diagnostics"]["abstained"])
        self.assertEqual(["기관 Y"], result["answer"]["insufficiency"]["missing_targets"])
        self.assertEqual({"기관 X"}, {claim["target"] for claim in result["answer"]["claims"]})

    def test_retry_relaxes_filters_when_verifier_rejects_evidence(self) -> None:
        result = run_rag_query(self.index, "기관 A의 블록체인 납품 실적은?")

        self.assertTrue(result["diagnostics"]["abstained"])
        self.assertEqual("insufficient", result["answer"]["status"])
        self.assertEqual("abstention", result["answer"]["query_type"])
        self.assertEqual([], result["answer"]["claims"])
        self.assertTrue(result["answer"]["insufficiency"]["reasons"])
        self.assertGreaterEqual(result["diagnostics"]["retry_count"], 1)
        self.assertEqual(
            ["strict", "relaxed"],
            [attempt["stage"] for attempt in result["diagnostics"]["filter_stage_attempts"]],
        )
        self.assertEqual("relaxed", result["plan"]["filter_stage"])

    def test_metadata_first_can_be_disabled_for_ablation(self) -> None:
        result = run_rag_query(
            self.index,
            "기관 A의 보안 통제 요구사항은?",
            metadata_first=False,
        )

        self.assertFalse(result["plan"]["metadata_first"])
        self.assertEqual("relaxed", result["plan"]["filter_stage"])
        self.assertEqual({}, result["plan"]["metadata_filters"])

    def test_rerank_can_be_disabled_for_ablation(self) -> None:
        result = run_rag_query(
            self.index,
            "기관 A의 보안 통제 요구사항은?",
            rerank=False,
        )

        self.assertFalse(result["plan"]["rerank"])
        self.assertEqual("dense", result["plan"]["strategy"].replace("metadata-first ", ""))

    def test_verifier_retry_can_be_disabled_for_ablation(self) -> None:
        result = run_rag_query(
            self.index,
            "기관 A의 블록체인 납품 실적은?",
            verifier_retry=False,
        )

        self.assertFalse(result["diagnostics"]["verifier_retry"])
        self.assertFalse(result["diagnostics"]["abstained"])
        self.assertEqual("supported", result["answer"]["status"])
        self.assertEqual(0, result["diagnostics"]["retry_count"])
        self.assertTrue(result["evidence"])

    def test_conversation_state_resolves_implicit_follow_up_entity(self) -> None:
        first = run_rag_query(
            self.index,
            "기관 A의 AI 요구사항은?",
            conversation_state={},
        )

        follow_up = run_rag_query(
            self.index,
            "그 기관이 요구한 보안 조건도 보여줘",
            conversation_state=first["conversation_state"],
        )

        self.assertFalse(follow_up["diagnostics"]["abstained"])
        self.assertEqual(
            "resolved",
            follow_up["diagnostics"]["context_resolution"]["status"],
        )
        self.assertEqual(
            "conversation_state",
            follow_up["diagnostics"]["context_resolution"]["source"],
        )
        self.assertIn("기관 A", follow_up["resolved_query"])
        self.assertEqual(
            {"rfp-agency-a-ai-quality"},
            {item["doc_id"] for item in follow_up["evidence"]},
        )

    def test_conversation_state_clarifies_ambiguous_singular_reference(self) -> None:
        first = run_rag_query(
            self.index,
            "기관 A와 기관 B의 보안 요구사항 차이를 비교해줘",
            conversation_state={},
        )

        follow_up = run_rag_query(
            self.index,
            "그 기관의 보안 조건은?",
            conversation_state=first["conversation_state"],
        )

        self.assertTrue(follow_up["diagnostics"]["abstained"])
        self.assertEqual([], follow_up["evidence"])
        self.assertEqual(
            "needs_clarification",
            follow_up["diagnostics"]["context_resolution"]["status"],
        )
        self.assertEqual(
            "ambiguous_active_state",
            follow_up["diagnostics"]["context_resolution"]["reason"],
        )


if __name__ == "__main__":
    unittest.main()
