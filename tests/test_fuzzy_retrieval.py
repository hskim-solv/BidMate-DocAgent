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

    def test_auto_chunking_uses_fixed_fallback_for_weak_structure(self) -> None:
        fallback_index = build_index_payload_from_documents(
            [
                {
                    "doc_id": "single-body",
                    "title": "단일 본문 RFP",
                    "agency": "기관 S",
                    "project": "단일 본문 사업",
                    "metadata": {},
                    "sections": [
                        {
                            "heading": "본문",
                            "text": "보안 로그를 남긴다. 운영 리포트를 제출한다.",
                        }
                    ],
                    "source_path": "single-body.txt",
                }
            ],
            source_dir="test-fixture",
            embedding_backend="hashing",
        )

        self.assertEqual(
            {"fixed": 1},
            fallback_index["build"]["chunking"]["actual_strategy_counts"],
        )
        self.assertEqual("fixed", fallback_index["chunks"][0]["chunking_strategy"])
        self.assertEqual(["문서 전체"], fallback_index["chunks"][0]["section_path"])

    def test_hierarchical_retrieval_reassembles_parent_section(self) -> None:
        long_section_index = build_index_payload_from_documents(
            [
                {
                    "doc_id": "section-parent",
                    "title": "부모 섹션 테스트 RFP",
                    "agency": "기관 P",
                    "project": "부모 섹션 사업",
                    "metadata": {},
                    "sections": [
                        {
                            "heading": "보안 요구사항",
                            "text": (
                                "보안 로그는 모든 관리자 작업에 대해 남겨야 한다. "
                                "접근 권한은 역할별로 분리한다. "
                                "운영 리포트는 매월 제출한다."
                            ),
                        }
                    ],
                    "source_path": "section-parent.txt",
                }
            ],
            source_dir="test-fixture",
            embedding_backend="hashing",
            chunking_strategy="section",
            chunk_max_chars=45,
            chunk_overlap_sentences=0,
        )

        flat = run_rag_query(long_section_index, "기관 P의 보안 로그 요구사항은?", top_k=1)
        hierarchical = run_rag_query(
            long_section_index,
            "기관 P의 보안 로그 요구사항은?",
            top_k=1,
            retrieval_mode="hierarchical",
        )

        self.assertEqual("flat", flat["diagnostics"]["retrieval_mode"])
        self.assertEqual("hierarchical", hierarchical["diagnostics"]["retrieval_mode"])
        self.assertEqual("hierarchical", hierarchical["evidence"][0]["retrieval_mode"])
        self.assertGreater(len(hierarchical["evidence"][0]["text"]), len(flat["evidence"][0]["text"]))
        self.assertIn("운영 리포트", hierarchical["evidence"][0]["text"])
        self.assertTrue(hierarchical["evidence"][0]["child_chunk_ids"])

    def test_retry_relaxes_filters_when_verifier_rejects_evidence(self) -> None:
        result = run_rag_query(self.index, "기관 A의 블록체인 납품 실적은?")

        self.assertTrue(result["diagnostics"]["abstained"])
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
