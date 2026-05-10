"""P0 regression guards for the retrieval loop and answerable smoke path.

Covers two real-data regressions documented in
``docs/real-data-failure-taxonomy.md`` and tracked under issue #68 / #49:

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

from rag_core import build_index_payload, run_rag_query


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
