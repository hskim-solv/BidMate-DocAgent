"""Regression guard for aggregate-only multi-chunk evidence failure analysis."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.render_multi_chunk_evidence_failures import build_aggregate, main


def _retrieved(ids: list[str]) -> list[dict[str, object]]:
    return [
        {
            "rank": rank,
            "chunk_id": chunk_id,
            "doc_id": f"doc-{rank}",
            "section": "PRIVATE SECTION",
            "text_preview": "PRIVATE DOC TEXT",
        }
        for rank, chunk_id in enumerate(ids, start=1)
    ]


def _case(
    *,
    gold_ids: list[str],
    retrieved_ids: list[str],
    gold_docs: list[str] | None = None,
    answerable: bool = True,
    hardcase_categories: list[str] | None = None,
    metadata_field: str | None = None,
    case_source_format: str | None = None,
    citation_claim_coverage: float | None = None,
    citation_page_coverage: float | None = None,
    citation_region_coverage: float | None = None,
    claim_citation_alignment: float | None = None,
) -> dict[str, object]:
    evidence = []
    if gold_docs is not None:
        evidence = [
            {"doc_id": doc_id, "chunk_id": chunk_id}
            for doc_id, chunk_id in zip(gold_docs, gold_ids)
        ]
    return {
        "answerable": answerable,
        "gold_chunk_ids": gold_ids,
        "gold_evidence": evidence,
        "retrieved_chunks": _retrieved(retrieved_ids),
        "hardcase_categories": hardcase_categories or [],
        "metadata_field": metadata_field,
        "case_source_format": case_source_format,
        "citation_claim_coverage": citation_claim_coverage,
        "citation_page_coverage": citation_page_coverage,
        "citation_region_coverage": citation_region_coverage,
        "claim_citation_alignment": claim_citation_alignment,
        "query": "PRIVATE QUERY",
        "answer": "PRIVATE ANSWER",
    }


def _summary(cases: list[dict[str, object]]) -> dict[str, object]:
    return {"num_predictions": len(cases), "case_results": cases}


class MultiChunkAggregateTest(unittest.TestCase):
    def test_population_excludes_single_chunk_and_unanswerable_cases(self) -> None:
        cases = [
            _case(gold_ids=["g1", "g2"], gold_docs=["d1", "d1"], retrieved_ids=["g1", "g2"]),
            _case(gold_ids=["single"], gold_docs=["d1"], retrieved_ids=["single"]),
            _case(
                gold_ids=["u1", "u2"],
                gold_docs=["d1", "d1"],
                retrieved_ids=["u1", "u2"],
                answerable=False,
            ),
        ]
        agg = build_aggregate(_summary(cases))

        self.assertEqual(agg["population"]["num_predictions"], 3)
        self.assertEqual(agg["population"]["multi_chunk_gold_cases"], 1)
        self.assertEqual(agg["population"]["multi_chunk_top10_evidence_failures"], 0)

    def test_retrieval_outcomes_and_evidence_split(self) -> None:
        all_case = _case(
            gold_ids=["all-a", "all-b"],
            gold_docs=["doc-a", "doc-a"],
            retrieved_ids=["all-a", "all-b"],
            case_source_format="json",
        )
        partial_case = _case(
            gold_ids=["partial-a", "partial-b"],
            gold_docs=["doc-b", "doc-b"],
            retrieved_ids=[
                "partial-a",
                "wrong-02",
                "wrong-03",
                "wrong-04",
                "wrong-05",
                "wrong-06",
                "wrong-07",
                "wrong-08",
                "wrong-09",
                "wrong-10",
                "partial-b",
            ],
            hardcase_categories=["table_heavy"],
            metadata_field="budget",
            case_source_format="hwp",
            citation_claim_coverage=0.5,
            citation_page_coverage=1.0,
            claim_citation_alignment=0.5,
        )
        none_case = _case(
            gold_ids=["none-a", "none-b"],
            gold_docs=["doc-c", "doc-d"],
            retrieved_ids=[f"wrong-{i:02d}" for i in range(1, 21)],
            case_source_format="pdf",
            citation_claim_coverage=1.0,
            citation_page_coverage=0.0,
            citation_region_coverage=0.0,
            claim_citation_alignment=1.0,
        )
        limited_depth_case = _case(
            gold_ids=["limited-a", "limited-b"],
            gold_docs=None,
            retrieved_ids=["limited-a"],
            case_source_format="비공개형식",
        )

        agg = build_aggregate(
            _summary([all_case, partial_case, none_case, limited_depth_case])
        )

        self.assertEqual(
            agg["retrieval_outcome_by_k"]["5"],
            {
                "all_gold_retrieved": 1,
                "partial_gold_retrieved": 1,
                "no_gold_retrieved": 1,
                "not_observable": 1,
            },
        )
        self.assertEqual(
            agg["retrieval_outcome_by_k"]["20"],
            {
                "all_gold_retrieved": 2,
                "partial_gold_retrieved": 0,
                "no_gold_retrieved": 1,
                "not_observable": 1,
            },
        )
        self.assertEqual(agg["evidence_split"], {"same_doc": 2, "multi_doc": 1, "unknown": 1})

    def test_candidate_pool_expected_impact_and_guardrails(self) -> None:
        partial_case = _case(
            gold_ids=["partial-a", "partial-b"],
            gold_docs=["doc-b", "doc-b"],
            retrieved_ids=[
                "partial-a",
                "wrong-02",
                "wrong-03",
                "wrong-04",
                "wrong-05",
                "wrong-06",
                "wrong-07",
                "wrong-08",
                "wrong-09",
                "wrong-10",
                "partial-b",
            ],
            hardcase_categories=["table_heavy"],
            metadata_field="deadline",
            case_source_format="hwp",
            citation_claim_coverage=0.0,
            claim_citation_alignment=0.0,
        )
        multi_doc_case = _case(
            gold_ids=["none-a", "none-b"],
            gold_docs=["doc-c", "doc-d"],
            retrieved_ids=[f"wrong-{i:02d}" for i in range(1, 21)],
            case_source_format="pdf",
            citation_page_coverage=0.0,
            citation_region_coverage=0.0,
        )
        limited_depth_case = _case(
            gold_ids=["limited-a", "limited-b"],
            gold_docs=None,
            retrieved_ids=["limited-a"],
            case_source_format="secret-private-format",
        )

        agg = build_aggregate(_summary([partial_case, multi_doc_case, limited_depth_case]))

        self.assertEqual(
            agg["candidate_pool_expansion"],
            {
                "missing_gold_seen_after_top10": 1,
                "all_missing_gold_seen_after_top10": 1,
                "not_observable_due_to_depth": 2,
            },
        )
        self.assertEqual(
            agg["expected_impact"],
            {
                "pool_or_rerank_candidate": 1,
                "query_decomposition_candidate": 1,
                "section_expansion_candidate": 1,
                "unknown_due_to_limited_depth": 1,
            },
        )
        self.assertEqual(
            agg["citation_guardrails"],
            {
                "citation_claim_coverage_lt_1": 1,
                "citation_page_coverage_lt_1": 1,
                "citation_region_coverage_lt_1": 1,
                "claim_citation_alignment_lt_1": 1,
            },
        )

        structured = agg["structured_overlap"]["top10_evidence_failures"]
        self.assertEqual(structured["hardcase_table_heavy"], 1)
        self.assertEqual(structured["metadata_field_structured"], 1)
        self.assertEqual(structured["case_source_format"]["hwp"], 1)
        self.assertEqual(structured["case_source_format"]["pdf"], 1)
        self.assertEqual(structured["case_source_format"]["other"], 1)

    def test_missing_retrieval_diagnostics_raises(self) -> None:
        case = _case(
            gold_ids=["g1", "g2"],
            gold_docs=["d1", "d1"],
            retrieved_ids=["g1"],
        )
        case.pop("retrieved_chunks")
        case.pop("retrieved_chunk_ids", None)

        with self.assertRaisesRegex(ValueError, "requires retrieved_chunks"):
            build_aggregate(_summary([case]))


class PrivacyBoundaryTest(unittest.TestCase):
    def test_raw_private_strings_absent_from_json(self) -> None:
        secret_doc = "SECRET_DOC_ID"
        secret_chunk = "SECRET_CHUNK_ID"
        secret_query = "비밀기관 질의"
        case = _case(
            gold_ids=[secret_chunk, "SECRET_CHUNK_ID_2"],
            gold_docs=[secret_doc, secret_doc],
            retrieved_ids=[secret_chunk],
            hardcase_categories=["table_heavy"],
            metadata_field="budget",
            case_source_format="비공개형식",
        )
        case["query"] = secret_query
        case["retrieved_chunks"] = [
            {
                "rank": 1,
                "chunk_id": secret_chunk,
                "doc_id": secret_doc,
                "path": "/Users/example/private/file.pdf",
                "section": "PRIVATE SECTION",
                "text_preview": "PRIVATE DOC TEXT",
            }
        ]

        rendered = json.dumps(build_aggregate(_summary([case])), ensure_ascii=False)

        for forbidden in (
            secret_doc,
            secret_chunk,
            secret_query,
            "비밀기관",
            "비공개형식",
            "/Users/example/private/file.pdf",
            "PRIVATE SECTION",
            "PRIVATE DOC TEXT",
        ):
            self.assertNotIn(forbidden, rendered)


class MainCliTest(unittest.TestCase):
    def test_main_writes_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path = root / "eval_summary.json"
            out_path = root / "multi_chunk.aggregate.json"
            summary_path.write_text(
                json.dumps(
                    _summary(
                        [
                            _case(
                                gold_ids=["g1", "g2"],
                                gold_docs=["d1", "d1"],
                                retrieved_ids=["g1"],
                            )
                        ]
                    )
                ),
                encoding="utf-8",
            )

            rc = main(["--summary", str(summary_path), "--out-json", str(out_path)])

            self.assertEqual(rc, 0)
            written = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(written["schema_version"], 1)
            self.assertEqual(written["population"]["multi_chunk_gold_cases"], 1)
            self.assertEqual(written["source"]["location"], "external_private/eval_summary.json")

    def test_main_missing_summary_returns_1(self) -> None:
        with TemporaryDirectory() as tmp:
            rc = main(["--summary", str(Path(tmp) / "missing.json")])
            self.assertEqual(rc, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
