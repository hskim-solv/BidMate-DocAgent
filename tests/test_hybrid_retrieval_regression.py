"""Regression guards for hybrid BM25 + dense retrieval (ADR 0009, issue #119).

Locks in four contracts:

* Default ``retrieval_backend`` is ``"dense"`` — naive_baseline behaviour
  (ADR 0001) is bit-stable when callers omit the new knob.
* ``retrieval_backend="hybrid"`` populates ``bm25`` and ``rank_rrf`` on
  ``score_parts`` and the final score equals the (normalized) RRF — so
  the hybrid path is observably different from the weighted path at
  the retrieval boundary.
* A rare-term query is retrievable under hybrid even when dense alone
  collides on neighbours under the hashing embedding backend.
* ``resolve_pipeline_config`` rejects unknown backend values.

Lightweight (hashing embedding backend + ``data/raw`` fixture) so
``make test-regression`` stays fast.
"""

import unittest
from pathlib import Path

from rag_core import (
    VALID_RETRIEVAL_BACKENDS,
    analyze_query,
    build_index_payload,
    make_plan,
    metadata_targets,
    resolve_pipeline_config,
    retrieve,
    run_rag_query,
)


ANSWERABLE_QUERY = "기관 A의 보안 통제 요구사항은?"
RARE_LEXICAL_QUERY = "기관 D 분광기 라만 캘리브레이션 주기는?"


class HybridRetrievalRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_index_payload(
            Path("data/raw"),
            embedding_backend="hashing",
        )

    def _retrieve_with_backend(self, query: str, retrieval_backend: str) -> list[dict]:
        analysis = analyze_query(query, metadata_targets(self.index))
        plan = make_plan(
            analysis,
            top_k=4,
            metadata_first=True,
            rerank=True,
            verifier_retry=False,
            retrieval_mode="flat",
            retrieval_backend=retrieval_backend,
        )
        return retrieve(self.index, query, analysis, plan)

    def test_default_backend_is_dense_when_unspecified(self) -> None:
        result = run_rag_query(self.index, ANSWERABLE_QUERY)
        self.assertEqual("dense", result["diagnostics"]["retrieval_backend"])
        self.assertEqual("dense", result["plan"]["retrieval_backend"])
        self.assertGreater(len(result["evidence"]), 0)

    def test_dense_retrieve_omits_rank_rrf_diagnostic(self) -> None:
        evidence = self._retrieve_with_backend(ANSWERABLE_QUERY, "dense")
        self.assertGreater(len(evidence), 0)
        for item in evidence:
            score_parts = item["score_parts"]
            self.assertIn("dense", score_parts)
            self.assertIn("lexical", score_parts)
            self.assertIn("metadata", score_parts)
            self.assertNotIn(
                "rank_rrf",
                score_parts,
                "dense path must not populate the RRF diagnostic field",
            )

    def test_hybrid_retrieve_populates_rrf_diagnostics(self) -> None:
        evidence = self._retrieve_with_backend(ANSWERABLE_QUERY, "hybrid")
        self.assertGreater(len(evidence), 0)
        for item in evidence:
            score_parts = item["score_parts"]
            self.assertIn("bm25", score_parts)
            self.assertIn("rank_rrf", score_parts)
            self.assertAlmostEqual(item["score"], score_parts["rank_rrf"], places=4)

    def test_hybrid_run_returns_hybrid_in_diagnostics(self) -> None:
        result = run_rag_query(
            self.index,
            ANSWERABLE_QUERY,
            retrieval_backend="hybrid",
        )
        self.assertEqual("hybrid", result["diagnostics"]["retrieval_backend"])
        self.assertEqual("hybrid", result["plan"]["retrieval_backend"])
        self.assertGreater(len(result["evidence"]), 0)

    def test_hybrid_surfaces_rare_lexical_term(self) -> None:
        """Lexical-specific rare term should retrieve its chunk under hybrid.

        The probe fixture
        ``data/raw/rfp_agency_d_spectrometer_probe.json`` carries the
        exact term "라만 캘리브레이션". BM25 weights that term sharply
        even when the hashing dense backend collides on neighbours, so
        the correct doc must appear in the top retrieval results.
        """
        evidence = self._retrieve_with_backend(RARE_LEXICAL_QUERY, "hybrid")
        doc_ids = [item["doc_id"] for item in evidence]
        self.assertIn(
            "rfp-agency-d-spectrometer-probe",
            doc_ids,
            f"hybrid retrieval missed the expected doc; got {doc_ids}",
        )

    def test_invalid_retrieval_backend_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            resolve_pipeline_config({"pipeline": "agentic_full", "retrieval_backend": "splade"})

    def test_valid_retrieval_backends_constant_is_minimal(self) -> None:
        self.assertEqual({"dense", "hybrid"}, VALID_RETRIEVAL_BACKENDS)


if __name__ == "__main__":
    unittest.main()
