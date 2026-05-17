"""Single-turn metadata ambiguity clarification (issue #72).

Real-data taxonomy C2-1 ("동일 기관에 다수 사업" / "유사 명칭 기관") flagged
that ambiguous single-turn queries silently abstained without a useful
clarification. The early gate at `make_metadata_clarification_result`
already existed but the clarification message only listed bare
`doc_id`s, which doesn't help a user pick a more specific phrasing.

This file locks in two improvements made for #72:

* `metadata_clarification_answer` now renders each competing candidate
  as `agency · project (doc_id)` so the user sees the human-readable
  project name straight from the response.
* The single-turn ambiguity probe fixtures
  (`rfp_agency_e_water_quality_*.json`) trigger the clarification
  path on the public synthetic surface so a regression that drops
  the early gate or breaks the message format is caught in CI.
"""

import unittest
from pathlib import Path

from rag_core import (
    build_index_payload,
    metadata_clarification_answer,
    run_rag_query,
)
from tests._shared_index_cache import get_shared_raw_index


class MetadataClarificationAnswerTest(unittest.TestCase):
    """Unit checks on the clarification message renderer."""

    def test_includes_agency_and_project_per_candidate(self) -> None:
        analysis = {
            "metadata_ambiguity": {
                "candidate_doc_ids": ["doc-1", "doc-2"],
            },
            "matched_doc_ids": ["doc-1", "doc-2"],
            "metadata_matches": [
                {
                    "doc_id": "doc-1",
                    "agency": "기관 X",
                    "project": "사업 ALPHA",
                },
                {
                    "doc_id": "doc-2",
                    "agency": "기관 X",
                    "project": "사업 BETA",
                },
            ],
        }
        msg = metadata_clarification_answer("기관 X의 사업은?", analysis)
        # Must include both projects with agency context — not just
        # bare doc_ids.
        self.assertIn("기관 X · 사업 ALPHA", msg)
        self.assertIn("기관 X · 사업 BETA", msg)
        self.assertIn("doc-1", msg)
        self.assertIn("doc-2", msg)

    def test_falls_back_to_doc_id_when_metadata_missing(self) -> None:
        analysis = {
            "metadata_ambiguity": {
                "candidate_doc_ids": ["doc-x"],
            },
            "matched_doc_ids": ["doc-x"],
            "metadata_matches": [],
        }
        msg = metadata_clarification_answer("ambiguous q", analysis)
        # No metadata available → bare doc_id remains as fallback.
        self.assertIn("doc-x", msg)

    def test_handles_empty_candidates_gracefully(self) -> None:
        msg = metadata_clarification_answer("ambiguous q", {})
        # Defensive: the message still surfaces the abstention reason.
        self.assertIn("ambiguous q", msg)
        self.assertIn("구체적으로", msg)


class SingleTurnAmbiguityProbeTest(unittest.TestCase):
    """End-to-end guard: ambiguous 기관 E queries trigger the
    `metadata_ambiguity_clarification` gate with the new agency·project
    rendering in the response summary.
    """

    @classmethod
    def setUpClass(cls) -> None:
        # Issue #915 — worker-local cache, see tests/_shared_index_cache.py.
        cls.index = get_shared_raw_index()

    def _expect_clarification(self, query: str) -> dict:
        result = run_rag_query(self.index, query)
        answer = result["answer"]
        self.assertEqual(
            answer["status"],
            "insufficient",
            f"query={query!r} expected clarification abstention",
        )
        code = answer.get("status_reason", {}).get("code", "")
        self.assertEqual(
            code,
            "metadata_ambiguity_clarification",
            f"query={query!r} expected metadata_ambiguity_clarification "
            f"code, got {code!r}",
        )
        # The improved message must surface project names alongside
        # doc_ids so users can re-phrase without looking up doc_ids.
        summary = answer.get("summary", "")
        self.assertIn("수질 모니터링 본 사업", summary)
        self.assertIn("수질 모니터링 부속 사업", summary)
        return answer

    def test_generic_agency_query_clarifies(self) -> None:
        self._expect_clarification("기관 E의 사업 개요는?")

    def test_partial_project_query_clarifies(self) -> None:
        self._expect_clarification("기관 E의 수질 모니터링 사업은?")

    def test_ambiguity_diagnostics_are_populated(self) -> None:
        result = run_rag_query(self.index, "기관 E의 사업 개요는?")
        analysis = result.get("analysis", {})
        ambiguity = analysis.get("metadata_ambiguity") or {}
        self.assertTrue(ambiguity.get("ambiguous"))
        self.assertEqual(ambiguity.get("reason"), "close_candidate_scores")
        self.assertGreaterEqual(
            len(ambiguity.get("candidate_doc_ids") or []), 2
        )


if __name__ == "__main__":
    unittest.main()
