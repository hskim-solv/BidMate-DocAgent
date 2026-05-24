"""Regression guard for the verifier_false_negative overlap renderer.

Stub eval_summary inputs only. Fixtures intentionally include synthetic raw
strings so the test can prove the renderer emits only counts/buckets.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.render_verifier_false_negative_overlap import (
    SAFE_CATEGORIES,
    build_aggregate,
    main,
    render_markdown,
    source_provenance,
)


def _summary(cases: list[dict[str, object]]) -> dict[str, object]:
    return {
        "num_predictions": len(cases),
        "case_results": cases,
    }


def _retrieved(score: float | None, *, chunk_id: str = "chunk-x") -> list[dict[str, object]]:
    row: dict[str, object] = {"rank": 1, "chunk_id": chunk_id, "doc_id": "doc-x"}
    if score is not None:
        row["score"] = score
    return [row]


def _vfn_case(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "answerable": False,
        "abstained": False,
        "query_type": "abstention",
        "hardcase_categories": ["no_answer"],
        "evidence_doc_ids": ["wrong-doc"],
        "expected_doc_ids": ["gold-doc"],
        "gold_chunk_ids": ["gold-chunk"],
        "retrieved_chunk_ids": ["wrong-chunk"],
        "retrieved_chunks": _retrieved(0.1),
        "chunk_recall_at_5": 0.0,
        "retry_count": 1,
        "query": "예산은 얼마인가요?",
        "term_match": False,
        "doc_match": False,
        "citation": [],
        "citation_claim_coverage_reason": "missing_claim_citation",
        "claim_citation_checked": 1,
        "claim_citation_alignment": 0.0,
        "claim_citation_errors": [
            {"code": "claim_missing_citation"},
            {"code": "claim_text_not_supported_by_citation"},
        ],
    }
    base.update(overrides)
    return base


def _retrieval_miss_case(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "answerable": True,
        "accuracy": 0.0,
        "abstained": False,
        "query_type": "single_doc",
        "hardcase_categories": ["multi_hop"],
        "evidence_doc_ids": ["wrong-doc"],
        "expected_doc_ids": ["gold-doc"],
        "gold_chunk_ids": ["gold-chunk"],
        "retrieved_chunk_ids": ["wrong-chunk"],
        "retrieved_chunks": _retrieved(0.9),
        "chunk_recall_at_5": 0.0,
        "retry_count": 0,
        "query": "사업 기간",
        "term_match": False,
        "doc_match": False,
    }
    base.update(overrides)
    return base


class AggregateShapeTest(unittest.TestCase):
    def test_failure_counts_and_answerability_split(self) -> None:
        cases = [
            _vfn_case(),
            _retrieval_miss_case(),
        ]
        agg = build_aggregate(_summary(cases))

        self.assertEqual(set(agg["failure_category_counts"]), set(SAFE_CATEGORIES))
        self.assertEqual(agg["failure_category_counts"]["verifier_false_negative"], 1)
        self.assertEqual(agg["failure_category_counts"]["retrieval_miss"], 1)
        self.assertEqual(
            agg["failure_category_by_answerability"]["verifier_false_negative"],
            {"answerable": 0, "unanswerable": 1},
        )
        self.assertEqual(
            agg["failure_category_by_answerability"]["retrieval_miss"],
            {"answerable": 1, "unanswerable": 0},
        )

    def test_missing_case_results_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_aggregate({"num_predictions": 0})


class OverlapTest(unittest.TestCase):
    def test_vfn_retrieval_label_overlap_is_separate_from_retrieval_signal(self) -> None:
        cases = [
            _vfn_case(),
            _retrieval_miss_case(),
        ]
        vfn = build_aggregate(_summary(cases))["verifier_false_negative"]

        self.assertEqual(vfn["overlap"]["retrieval_miss_label_overlap"]["count"], 0)
        self.assertTrue(
            vfn["overlap"]["retrieval_miss_label_overlap"][
                "expected_zero_due_to_first_match_wins"
            ]
        )
        self.assertEqual(vfn["overlap"]["retrieval_fault_signal"]["count"], 1)
        self.assertEqual(
            vfn["overlap"]["retrieval_fault_signal"]["components"]["expected_doc_missing"],
            1,
        )
        self.assertEqual(
            vfn["overlap"]["retrieval_fault_signal"]["components"]["expected_chunk_missing"],
            1,
        )

    def test_low_score_citation_missing_and_unsupported_buckets(self) -> None:
        # Failed-case scores: 0.1, 0.2, 0.9 -> p25 bucket threshold is 0.1.
        cases = [
            _vfn_case(retrieved_chunks=_retrieved(0.1)),
            _vfn_case(
                evidence_doc_ids=["gold-doc"],
                retrieved_chunk_ids=["wrong-chunk"],
                retrieved_chunks=_retrieved(0.2),
                chunk_recall_at_5=0.5,
                citation=[{"chunk_id": "wrong-chunk"}],
                citation_claim_coverage_reason="ok",
                claim_citation_checked=1,
                claim_citation_alignment=0.5,
                claim_citation_errors=[{"code": "expected_claim_terms_missing"}],
            ),
            _retrieval_miss_case(retrieved_chunks=_retrieved(0.9)),
        ]
        vfn = build_aggregate(_summary(cases))["verifier_false_negative"]

        self.assertEqual(vfn["total"], 2)
        self.assertEqual(vfn["decision"], "mixed")
        self.assertEqual(
            vfn["slices"]["expected_coverage"],
            {"no_expected": 0, "expected_in_evidence": 1, "expected_not_in_evidence": 1},
        )
        self.assertEqual(vfn["overlap"]["low_top_score"]["threshold"], 0.1)
        self.assertEqual(
            vfn["overlap"]["low_top_score"]["buckets"],
            {"low_top_score": 1, "above_low_top_score": 1, "score_missing": 0},
        )
        self.assertEqual(vfn["overlap"]["citation_missing"]["count"], 1)
        self.assertEqual(
            vfn["overlap"]["citation_missing"]["citation_claim_coverage_reason"][
                "missing_claim_citation"
            ],
            1,
        )
        self.assertEqual(vfn["overlap"]["unsupported_answer"]["count"], 2)
        self.assertEqual(
            vfn["overlap"]["unsupported_answer"]["claim_citation_error_codes"][
                "expected_claim_terms_missing"
            ],
            1,
        )
        self.assertEqual(
            vfn["overlap"]["pairwise_intersections"][
                "retrieval_fault_signal+unsupported_answer"
            ],
            2,
        )

    def test_score_missing_bucket(self) -> None:
        vfn = build_aggregate(
            _summary([_vfn_case(retrieved_chunks=_retrieved(None))])
        )["verifier_false_negative"]
        self.assertEqual(vfn["overlap"]["low_top_score"]["buckets"]["score_missing"], 1)


class PrivacyBoundaryTest(unittest.TestCase):
    def test_raw_strings_absent_from_json_and_markdown(self) -> None:
        secret_query = "비밀기관 평가 기준은 얼마인가요"
        secret_doc = "secret-doc-id-123"
        secret_chunk = "secret-chunk-id-456"
        secret_answer = "PRIVATE RAW ANSWER"
        secret_path = "/Users/example/private/file.pdf"
        case = _vfn_case(
            query=secret_query,
            answer=secret_answer,
            evidence_doc_ids=[secret_doc],
            expected_doc_ids=[secret_doc],
            gold_chunk_ids=[secret_chunk],
            retrieved_chunk_ids=[secret_chunk],
            retrieved_chunks=[
                {
                    "rank": 1,
                    "score": 0.1,
                    "doc_id": secret_doc,
                    "chunk_id": secret_chunk,
                    "path": secret_path,
                    "text_preview": "PRIVATE DOC TEXT",
                }
            ],
            citation=[{"doc_id": secret_doc, "chunk_id": secret_chunk}],
        )
        agg = build_aggregate(_summary([case]))
        rendered = json.dumps(agg, ensure_ascii=False)
        md = render_markdown(agg)
        for forbidden in (
            secret_query,
            "비밀기관",
            secret_doc,
            secret_chunk,
            secret_answer,
            secret_path,
            "PRIVATE DOC TEXT",
        ):
            self.assertNotIn(forbidden, rendered)
            self.assertNotIn(forbidden, md)


class MainCliTest(unittest.TestCase):
    def test_external_source_provenance_redacts_absolute_path(self) -> None:
        with TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "eval_summary.json"
            summary_path.write_text(
                json.dumps(_summary([_vfn_case()]), ensure_ascii=False),
                encoding="utf-8",
            )

            source = source_provenance(summary_path)

            self.assertEqual(source["location"], "external_private/eval_summary.json")
            self.assertTrue(source["location_redacted"])
            self.assertEqual(source["basename"], "eval_summary.json")
            self.assertNotIn(str(summary_path), json.dumps(source))

    def test_main_writes_json_and_md(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path = root / "eval_summary.json"
            out_json = root / "vfn.aggregate.json"
            out_md = root / "vfn.md"
            summary_path.write_text(
                json.dumps(_summary([_vfn_case()]), ensure_ascii=False),
                encoding="utf-8",
            )

            rc = main(
                [
                    "--summary",
                    str(summary_path),
                    "--out-json",
                    str(out_json),
                    "--out-md",
                    str(out_md),
                ]
            )

            self.assertEqual(rc, 0)
            self.assertTrue(out_json.is_file())
            self.assertTrue(out_md.is_file())
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["verifier_false_negative"]["total"], 1)
            self.assertEqual(
                payload["source"]["location"], "external_private/eval_summary.json"
            )
            self.assertNotIn(str(summary_path), out_md.read_text(encoding="utf-8"))

    def test_main_missing_summary_returns_nonzero(self) -> None:
        with TemporaryDirectory() as tmp:
            rc = main(
                [
                    "--summary",
                    str(Path(tmp) / "missing.json"),
                    "--out-json",
                    str(Path(tmp) / "x.json"),
                    "--out-md",
                    str(Path(tmp) / "x.md"),
                ]
            )
            self.assertEqual(rc, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
