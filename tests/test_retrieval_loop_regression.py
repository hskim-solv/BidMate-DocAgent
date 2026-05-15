"""P0 regression guards for the retrieval loop and answerable smoke path.

Covers two real-data regressions documented in
``docs/real-data/real-data-failure-taxonomy.md`` and tracked under issue #68 / #49:

* **R2** — retrieval loop body (`retrieve` / `verify_evidence` /
  ``stage_attempts.append``) was lost in a merge, causing every answerable
  query to abstain with empty evidence.
* **R1** — ``IndexError`` when reading ``final_relaxation_reason`` with
  ``retry_count > 0`` but ``len(stage_attempts) < 2``.

These tests are intentionally lightweight (hashing embedding backend, the
existing ``data/raw`` fixture) so they can be run on every change without
slowing down the dev loop. See ``make test-regression``.
"""

import unittest
from pathlib import Path

from rag_core import (
    MAX_AGENT_ITERATIONS,
    build_index_payload,
    metadata_stage_sequence,
    run_rag_query,
)


ANSWERABLE_QUERY = "기관 A의 보안 통제 요구사항은?"
OUT_OF_CORPUS_QUERY = "외계 행성의 우주선 검수 절차는?"


class RetrievalLoopRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_index_payload(
            Path("data/raw"),
            embedding_backend="hashing",
        )

    def test_answerable_single_doc_returns_non_empty_evidence(self) -> None:
        """R2 guard: answerable single-doc query must not silently abstain.

        If the retrieval loop body is deleted again, this assertion fails fast.
        """
        result = run_rag_query(self.index, ANSWERABLE_QUERY)

        diagnostics = result["diagnostics"]
        self.assertFalse(
            diagnostics["abstained"],
            "answerable query unexpectedly abstained — retrieval loop may be broken",
        )
        self.assertGreater(
            len(result["evidence"]),
            0,
            "answerable query returned empty evidence",
        )
        attempts = diagnostics["filter_stage_attempts"]
        self.assertGreaterEqual(
            len(attempts),
            1,
            "stage_attempts must be appended on each retrieval iteration",
        )
        self.assertTrue(
            attempts[-1]["verified"],
            "final stage attempt must be verified for an answerable query",
        )
        self.assertEqual("supported", result["answer"]["status"])

    def test_diagnostics_block_safe_for_single_attempt_verified_path(self) -> None:
        """R1 guard: diagnostics must build cleanly when only one attempt ran.

        On a single verified attempt, ``retry_count == 0`` and
        ``final_relaxation_reason`` must be an empty list — not raise IndexError
        and not be ``None``.
        """
        result = run_rag_query(self.index, ANSWERABLE_QUERY)

        diagnostics = result["diagnostics"]
        self.assertEqual(0, diagnostics["retry_count"])
        self.assertIsInstance(diagnostics["final_relaxation_reason"], list)
        self.assertEqual([], diagnostics["final_relaxation_reason"])

    def test_stage_sequence_never_exceeds_cap(self) -> None:
        """Explicit-cap invariant (PR-02).

        ``metadata_stage_sequence`` is the only producer of ``stage_sequence``.
        Across all relevant analysis shapes it must stay within
        ``MAX_AGENT_ITERATIONS``; otherwise the loop guard in
        ``run_rag_query`` would raise.
        """
        analyses = [
            {},
            {"metadata_filters_by_stage": {"strict": {"agency": "기관 A"}}},
            {
                "metadata_filters_by_stage": {
                    "strict": {"agency": "기관 A"},
                    "reduced": {"agency": "기관"},
                }
            },
        ]
        for analysis in analyses:
            for metadata_first in (True, False):
                for verifier_retry in (True, False):
                    with self.subTest(
                        analysis=analysis,
                        metadata_first=metadata_first,
                        verifier_retry=verifier_retry,
                    ):
                        seq = metadata_stage_sequence(
                            analysis,
                            metadata_first=metadata_first,
                            verifier_retry=verifier_retry,
                        )
                        self.assertGreaterEqual(len(seq), 1)
                        self.assertLessEqual(len(seq), MAX_AGENT_ITERATIONS)

    def test_iteration_cap_constant_matches_observed_max(self) -> None:
        """Sanity: the published cap is at least the observed worst case."""
        # Comparison + strict + reduced + verifier_retry exercises the longest
        # sequence today (strict, reduced, relaxed = 3 stages).
        seq = metadata_stage_sequence(
            {
                "metadata_filters_by_stage": {
                    "strict": {"agency": "기관 A"},
                    "reduced": {"agency": "기관"},
                }
            },
            metadata_first=True,
            verifier_retry=True,
        )
        self.assertLessEqual(len(seq), MAX_AGENT_ITERATIONS)
        self.assertGreaterEqual(MAX_AGENT_ITERATIONS, len(seq))

    def test_out_of_corpus_query_exits_loop_without_indexerror(self) -> None:
        """R1 guard for the retry/abstention path.

        Out-of-corpus queries exercise the retry path. Regardless of how many
        attempts run, the diagnostics dict must be well-formed:
        ``final_relaxation_reason`` is a list and ``filter_stage_attempts`` is
        non-empty.
        """
        result = run_rag_query(self.index, OUT_OF_CORPUS_QUERY)

        diagnostics = result["diagnostics"]
        self.assertIsInstance(diagnostics["final_relaxation_reason"], list)
        attempts = diagnostics["filter_stage_attempts"]
        self.assertGreaterEqual(len(attempts), 1)
        # Every appended attempt carries a stage label and verified flag,
        # which proves the loop body ran end-to-end.
        for attempt in attempts:
            self.assertIn("stage", attempt)
            self.assertIn("verified", attempt)


if __name__ == "__main__":
    unittest.main()
