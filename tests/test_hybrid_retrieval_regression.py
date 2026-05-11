"""Regression guards for hybrid BM25 + dense retrieval (ADR 0010, issue #119).

Locks in five contracts:

* Default ``retrieval_backend`` is ``"dense"`` — naive_baseline behaviour
  (ADR 0001) is bit-stable when callers omit the new knob.
* ``retrieval_backend="hybrid"`` populates ``bm25`` and ``rank_rrf`` on
  ``score_parts`` and the final score equals the (normalized) RRF — so
  the hybrid path is observably different from the weighted path at
  the retrieval boundary.
* A rare-term query is retrievable under hybrid even when dense alone
  collides on neighbours under the hashing embedding backend.
* ``resolve_pipeline_config`` rejects unknown backend values.
* ``rrf_k`` is plan-time configurable (issue #149) — default is the
  module-level ``RRF_K = 60``; out-of-range values are rejected;
  varying k produces observably different normalized RRF scores.

Lightweight (hashing embedding backend + ``data/raw`` fixture) so
``make test-regression`` stays fast.
"""

import unittest
from pathlib import Path

from rag_core import (
    RRF_K,
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

    def _retrieve_with_backend(
        self,
        query: str,
        retrieval_backend: str,
        *,
        rrf_k: int = RRF_K,
    ) -> list[dict]:
        analysis = analyze_query(query, metadata_targets(self.index))
        plan = make_plan(
            analysis,
            top_k=4,
            metadata_first=True,
            rerank=True,
            verifier_retry=False,
            retrieval_mode="flat",
            retrieval_backend=retrieval_backend,
            rrf_k=rrf_k,
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

    # -- Issue #149 — RRF k as plan-time knob -----------------------

    def test_default_rrf_k_is_60(self) -> None:
        """Plan-time default for ``rrf_k`` matches the module constant.

        The ADR 0010 acceptance contract pins the default at 60; the
        knob plumbing must not silently drift away from it.
        """
        analysis = analyze_query(ANSWERABLE_QUERY, metadata_targets(self.index))
        plan = make_plan(
            analysis,
            top_k=4,
            retrieval_backend="hybrid",
        )
        self.assertEqual(60, plan["rrf_k"])
        self.assertEqual(RRF_K, plan["rrf_k"])

    def test_rrf_k_override_changes_scores(self) -> None:
        """Different ``rrf_k`` values produce observably different scores.

        k=10 makes the top rank dominate; k=200 flattens the fusion. The
        normalized RRF score for the top-ranked chunk must differ
        between these two regimes by more than rounding noise.
        """
        evidence_k10 = self._retrieve_with_backend(
            ANSWERABLE_QUERY, "hybrid", rrf_k=10
        )
        evidence_k200 = self._retrieve_with_backend(
            ANSWERABLE_QUERY, "hybrid", rrf_k=200
        )
        self.assertGreater(len(evidence_k10), 0)
        self.assertGreater(len(evidence_k200), 0)
        self.assertNotAlmostEqual(
            evidence_k10[0]["score"],
            evidence_k200[0]["score"],
            places=3,
            msg="rrf_k override should change the normalized top score",
        )

    def test_resolve_pipeline_config_rejects_out_of_range_rrf_k(self) -> None:
        with self.assertRaises(ValueError):
            resolve_pipeline_config(
                {"pipeline": "agentic_full", "retrieval_backend": "hybrid", "rrf_k": 0}
            )
        with self.assertRaises(ValueError):
            resolve_pipeline_config(
                {"pipeline": "agentic_full", "retrieval_backend": "hybrid", "rrf_k": 5000}
            )

    def test_make_plan_rejects_out_of_range_rrf_k(self) -> None:
        analysis = analyze_query(ANSWERABLE_QUERY, metadata_targets(self.index))
        with self.assertRaises(ValueError):
            make_plan(analysis, retrieval_backend="hybrid", rrf_k=0)
        with self.assertRaises(ValueError):
            make_plan(analysis, retrieval_backend="hybrid", rrf_k=5000)

    def test_dense_path_ignores_rrf_k(self) -> None:
        """``rrf_k`` only affects the hybrid RRF fusion block.

        Under ``retrieval_backend="dense"`` the score is the weighted
        dense+lexical+metadata sum (no RRF), so different ``rrf_k``
        values must produce identical evidence — this preserves ADR
        0001 bit-stability for the dense path.
        """
        r_a = self._retrieve_with_backend(ANSWERABLE_QUERY, "dense", rrf_k=10)
        r_b = self._retrieve_with_backend(ANSWERABLE_QUERY, "dense", rrf_k=200)
        self.assertEqual(
            [(it["chunk_id"], it["score"]) for it in r_a],
            [(it["chunk_id"], it["score"]) for it in r_b],
        )

    def test_diagnostics_surface_rrf_k(self) -> None:
        """``rrf_k`` appears in both ``plan`` and ``diagnostics`` for traceability."""
        result = run_rag_query(
            self.index,
            ANSWERABLE_QUERY,
            retrieval_backend="hybrid",
            rrf_k=30,
        )
        self.assertEqual(30, result["plan"]["rrf_k"])
        self.assertEqual(30, result["diagnostics"]["rrf_k"])


if __name__ == "__main__":
    unittest.main()
