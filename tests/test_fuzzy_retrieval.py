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

    def test_single_agency_schedule_and_budget_query_is_not_comparison(self) -> None:
        same_agency_index = build_index_payload_from_documents(
            [
                {
                    "doc_id": "agency-x-main",
                    "title": "기관 X 시스템 기능개선",
                    "agency": "기관 X",
                    "project": "시스템 기능개선",
                    "metadata": {},
                    "sections": [{"heading": "본문", "text": "사업기간은 3개월이고 사업금액은 1억원이다."}],
                    "source_path": "agency-x-main.txt",
                },
                {
                    "doc_id": "agency-x-extra",
                    "title": "기관 X 포털 기능개선",
                    "agency": "기관 X",
                    "project": "포털 기능개선",
                    "metadata": {},
                    "sections": [{"heading": "본문", "text": "포털 기능개선은 별도 유지관리 사업이다."}],
                    "source_path": "agency-x-extra.txt",
                },
            ],
            source_dir="test-fixture",
            embedding_backend="hashing",
        )

        result = run_rag_query(same_agency_index, "기관 X의 사업기간과 사업금액은?")

        self.assertEqual("single_doc", result["analysis"]["query_type"])

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

    def test_verifier_ignores_metadata_and_intent_tokens_for_real_like_summary(self) -> None:
        real_like_index = build_index_payload_from_documents(
            [
                {
                    "doc_id": "bonghwa-disaster",
                    "title": "봉화군 재난통합관리시스템 고도화 사업",
                    "agency": "경상북도 봉화군",
                    "project": "봉화군 재난통합관리시스템 고도화 사업",
                    "metadata": {
                        "summary": "사업범위: 재난통합관리시스템 고도화 및 개선",
                    },
                    "sections": [
                        {
                            "heading": "본문",
                            "text": (
                                "사업내용 및 범위는 재난 상황관리 기능 개선과 "
                                "시스템 연계 고도화를 포함한다."
                            ),
                        }
                    ],
                    "source_path": "bonghwa.hwp",
                }
            ],
            source_dir="test-fixture",
            embedding_backend="hashing",
        )

        result = run_rag_query(
            real_like_index,
            "경상북도 봉화군 봉화군 재난통합관리시스템 고도화 사업의 주요 요구사항과 사업 범위를 요약해줘",
        )

        self.assertEqual("supported", result["answer"]["status"])
        self.assertFalse(result["diagnostics"]["abstained"])
        self.assertEqual({"bonghwa-disaster"}, {item["doc_id"] for item in result["evidence"]})

    def test_follow_up_budget_particle_normalization_uses_conversation_state(self) -> None:
        real_like_index = build_index_payload_from_documents(
            [
                {
                    "doc_id": "hanyeong-track",
                    "title": "한영대학교 특성화 맞춤형 교육환경 구축 사업",
                    "agency": "한영대학",
                    "project": "한영대학교 특성화 맞춤형 교육환경 구축 - 트랙운영 학사정보시스템 고도화",
                    "metadata": {
                        "budget": 130000000,
                        "summary": "사업예산 130,000,000원, 사업기간 계약일로부터 3개월",
                    },
                    "sections": [
                        {
                            "heading": "사업 안내",
                            "text": (
                                "사업예산은 130,000,000원 범위 내이다. "
                                "사업기간은 계약일로부터 3개월이다. "
                                "트랙기반 교육과정 운영 관리 체계를 지원한다."
                            ),
                        }
                    ],
                    "source_path": "hanyeong.hwp",
                }
            ],
            source_dir="test-fixture",
            embedding_backend="hashing",
        )
        first = run_rag_query(
            real_like_index,
            "한영대학교 특성화 맞춤형 교육환경 구축 사업의 주요 요구사항은?",
            conversation_state={},
        )

        follow_up = run_rag_query(
            real_like_index,
            "그 사업의 사업기간과 사업예산도 알려줘",
            conversation_state=first["conversation_state"],
        )

        self.assertEqual("supported", follow_up["answer"]["status"])
        self.assertFalse(follow_up["diagnostics"]["abstained"])
        self.assertEqual(
            "resolved",
            follow_up["diagnostics"]["context_resolution"]["status"],
        )
        self.assertEqual(
            "conversation_state",
            follow_up["diagnostics"]["context_resolution"]["source"],
        )
        self.assertIn("사업예산", follow_up["diagnostics"]["verification_topics"])

    def test_metadata_only_budget_claim_does_not_emit_unrelated_body_sentence(self) -> None:
        real_like_index = build_index_payload_from_documents(
            [
                {
                    "doc_id": "agency-x-budget",
                    "title": "기관 X 예산 사업",
                    "agency": "기관 X",
                    "project": "예산 사업",
                    "metadata": {"budget": 130000000},
                    "sections": [
                        {
                            "heading": "본문",
                            "text": "기관 X는 사용자 교육과 운영 지원을 제공한다.",
                        }
                    ],
                    "source_path": "agency-x.hwp",
                }
            ],
            source_dir="test-fixture",
            embedding_backend="hashing",
        )

        result = run_rag_query(real_like_index, "기관 X의 사업예산 알려줘")

        self.assertEqual("supported", result["answer"]["status"])
        self.assertFalse(result["diagnostics"]["abstained"])
        self.assertEqual(1, len(result["answer"]["claims"]))
        self.assertIn("사업예산", result["answer"]["claims"][0]["claim"])
        self.assertIn("130,000,000원", result["answer"]["claims"][0]["claim"])
        self.assertNotIn("운영 지원", result["answer"]["summary"])

    def test_metadata_first_can_be_disabled_for_ablation(self) -> None:
        result = run_rag_query(
            self.index,
            "기관 A의 보안 통제 요구사항은?",
            metadata_first=False,
        )

        self.assertFalse(result["plan"]["metadata_first"])
        self.assertEqual("relaxed", result["plan"]["filter_stage"])
        self.assertEqual({}, result["plan"]["metadata_filters"])

    def test_naive_pipeline_uses_dense_top_k_without_agentic_stages(self) -> None:
        result = run_rag_query(
            self.index,
            "기관 A의 보안 통제 요구사항은?",
            pipeline="naive_baseline",
        )

        self.assertEqual("naive_baseline", result["plan"]["pipeline"])
        self.assertEqual("minimal_grounded_extractive", result["plan"]["prompt_profile"])
        self.assertEqual(4, result["plan"]["top_k"])
        self.assertFalse(result["plan"]["metadata_first"])
        self.assertFalse(result["plan"]["rerank"])
        self.assertFalse(result["diagnostics"]["verifier_retry"])
        self.assertEqual("relaxed", result["plan"]["filter_stage"])
        self.assertEqual("dense", result["plan"]["strategy"])

    def test_full_alias_uses_agentic_pipeline_preset(self) -> None:
        result = run_rag_query(
            self.index,
            "기관 A의 보안 통제 요구사항은?",
            pipeline="full",
        )

        self.assertEqual("agentic_full", result["plan"]["pipeline"])
        self.assertEqual("structured_grounded_claims", result["plan"]["prompt_profile"])
        self.assertTrue(result["plan"]["metadata_first"])
        self.assertTrue(result["plan"]["rerank"])
        self.assertTrue(result["diagnostics"]["verifier_retry"])

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


class BalancedComparisonRerankTest(unittest.TestCase):
    """Tests for the comparison-aware top-k cut introduced for issue #33."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = cls._build_asymmetric_index()

    @staticmethod
    def _build_asymmetric_index() -> dict:
        """Two-doc fixture where one document has many more chunks than the other."""
        agency_a_sections = [
            {"heading": f"섹션 A{i}", "text": f"기관 A는 보안 통제 {i}번 항목을 요구한다."}
            for i in range(1, 7)
        ]
        agency_b_sections = [
            {"heading": "섹션 B1", "text": "기관 B는 개인정보 비식별화를 요구한다."}
        ]
        return build_index_payload_from_documents(
            [
                {
                    "doc_id": "asym-agency-a",
                    "title": "기관 A 보안 RFP",
                    "agency": "기관 A",
                    "project": "보안 통제",
                    "metadata": {},
                    "sections": agency_a_sections,
                    "source_path": "asym-a.txt",
                },
                {
                    "doc_id": "asym-agency-b",
                    "title": "기관 B 보안 RFP",
                    "agency": "기관 B",
                    "project": "개인정보 보호",
                    "metadata": {},
                    "sections": agency_b_sections,
                    "source_path": "asym-b.txt",
                },
            ],
            source_dir="test-fixture",
            embedding_backend="hashing",
        )

    def test_balanced_rerank_min_coverage_under_asymmetry(self) -> None:
        """Comparison query against an asymmetric corpus must cover both targets."""
        result = run_rag_query(
            self.index,
            "기관 A와 기관 B의 보안 요구사항 차이를 비교해줘",
            pipeline="agentic_full",
        )

        self.assertEqual("comparison", result["analysis"]["query_type"])
        coverage = result["plan"].get("comparison_coverage")
        self.assertIsNotNone(coverage)
        self.assertTrue(coverage["balanced"])
        self.assertEqual(
            sorted(coverage["targets"]),
            sorted(["asym-agency-a", "asym-agency-b"]),
        )
        for target in coverage["targets"]:
            self.assertGreaterEqual(coverage["after"][target], 1)

    def test_balanced_disabled_preserves_top_k_ordering(self) -> None:
        """With balancing disabled, the cut must be a plain global score sort."""
        result = run_rag_query(
            self.index,
            "기관 A와 기관 B의 보안 요구사항 차이를 비교해줘",
            pipeline="agentic_full",
            comparison_balance={"enabled": False},
        )
        coverage = result["plan"].get("comparison_coverage")
        self.assertIsNotNone(coverage)
        self.assertFalse(coverage["balanced"])

    def test_balanced_no_op_for_single_doc_query(self) -> None:
        """Single-doc queries must not record comparison_coverage diagnostics."""
        result = run_rag_query(
            self.index,
            "기관 A의 보안 통제 요구사항은?",
            pipeline="agentic_full",
        )
        self.assertEqual("single_doc", result["analysis"]["query_type"])
        self.assertIsNone(result["plan"].get("comparison_coverage"))

    def test_naive_baseline_does_not_apply_balancing(self) -> None:
        """The naive_baseline preset must not enable comparison balancing."""
        result = run_rag_query(
            self.index,
            "기관 A와 기관 B의 보안 요구사항 차이를 비교해줘",
            pipeline="naive_baseline",
        )
        coverage = result["plan"].get("comparison_coverage")
        if coverage is not None:
            self.assertFalse(coverage["balanced"])


if __name__ == "__main__":
    unittest.main()
