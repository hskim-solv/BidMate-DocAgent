"""Regression guards for gold-free citation coverage (eval_summary surface).

``score_citation_coverage`` answers "of the claims the model produced, how many
carry a citation, and of those citations, how many fill page / region metadata"
— distinct from the gold-scored ``citation_*_precision``. Denominator-empty
rates return ``None`` (no claims / no citations) so the run-level aggregate in
``metric_block`` skips vacuous cases (e.g. well-formed abstentions) instead of
fabricating a 1.0/0.0.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_eval import metric_block  # noqa: E402
from eval.scorers.citation import score_citation_coverage  # noqa: E402

COVERAGE_KEYS = (
    "citation_claim_coverage",
    "citation_page_coverage",
    "citation_region_coverage",
)


def _pred(claims):
    return {"answer": {"claims": claims}}


class CitationCoverageTest(unittest.TestCase):
    def test_claim_and_page_and_region_coverage(self) -> None:
        pred = _pred(
            [
                # cited, page_span only (page filled, region empty)
                {"claim": "a", "citations": [{"doc_id": "d", "page_span": [1, 1]}]},
                # cited, region with bbox (page derived + region filled)
                {
                    "claim": "b",
                    "citations": [
                        {
                            "doc_id": "d",
                            "regions": [{"page_number": 2, "bbox": [0, 0, 1, 1]}],
                        }
                    ],
                },
                # no citation
                {"claim": "c", "citations": []},
            ]
        )
        cov = score_citation_coverage(pred)
        self.assertAlmostEqual(cov["citation_claim_coverage"], 2 / 3)
        # 2 citations, both expose a page; only 1 exposes a bbox region
        self.assertAlmostEqual(cov["citation_page_coverage"], 1.0)
        self.assertAlmostEqual(cov["citation_region_coverage"], 0.5)
        self.assertEqual(cov["citation_page_coverage_denominator"], 2)
        self.assertEqual(cov["citation_region_coverage_denominator"], 2)
        self.assertEqual(cov["citation_page_coverage_reason"], "ok")
        self.assertEqual(cov["citation_region_coverage_reason"], "region_metadata_missing")

    def test_no_claims_returns_none(self) -> None:
        cov = score_citation_coverage(_pred([]))
        for key in COVERAGE_KEYS:
            self.assertIsNone(cov[key])
        self.assertEqual(cov["citation_claim_coverage_denominator"], 0)
        self.assertEqual(cov["citation_page_coverage_denominator"], 0)
        self.assertEqual(cov["citation_page_coverage_reason"], "no_citations")

    def test_claims_without_citations_have_none_metadata_coverage(self) -> None:
        cov = score_citation_coverage(_pred([{"claim": "a", "citations": []}]))
        self.assertEqual(cov["citation_claim_coverage"], 0.0)
        self.assertIsNone(cov["citation_page_coverage"])
        self.assertIsNone(cov["citation_region_coverage"])
        self.assertEqual(cov["citation_claim_coverage_denominator"], 1)
        self.assertEqual(cov["citation_page_coverage_denominator"], 0)
        self.assertEqual(cov["citation_page_coverage_reason"], "no_citations")

    def test_aggregate_skips_none_cases(self) -> None:
        base = {
            "accuracy": 1.0,
            "groundedness": 1.0,
            "citation_precision": 1.0,
            "abstention": None,
            "query_type": "single_doc",
            "latency_ms": 1.0,
            "retry_count": 0,
        }
        rows = [
            {**base, "citation_claim_coverage": 1.0, "citation_page_coverage": 1.0,
             "citation_region_coverage": 0.0},
            {**base, "citation_claim_coverage": 0.0, "citation_page_coverage": None,
             "citation_region_coverage": None},
        ]
        block = metric_block(rows)
        self.assertAlmostEqual(block["citation_claim_coverage"], 0.5)
        # page coverage: only the first row carried a value
        self.assertEqual(block["citation_page_coverage"], 1.0)
        self.assertEqual(block["ci"]["citation_page_coverage"]["n"], 1)
        for key in COVERAGE_KEYS:
            self.assertIn(key, block)
            self.assertIn(key, block["ci"])
        self.assertIn("citation_coverage_reason_counts", block)


if __name__ == "__main__":
    unittest.main()
