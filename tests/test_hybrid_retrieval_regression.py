"""Regression guards for hybrid BM25 + dense retrieval (ADR 0010, issue #119).

Locks in six contracts:

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
* ``bm25_stopword_profile`` is plan-time configurable (issue #150) —
  default is ``"shared"`` (current behaviour); the ``"bm25_extra"``
  profile strips additional Korean particles (까지/부터/마다/…) and
  short discourse stopwords from BM25 only, leaving dense/Jaccard
  scoring bit-stable.

Lightweight (hashing embedding backend + ``data/raw`` fixture) so
``make test-regression`` stays fast.
"""

import unittest
from pathlib import Path

from rag_core import (
    BM25_EXTRA_PARTICLE_SUFFIXES,
    BM25_EXTRA_STOPWORDS,
    RRF_K,
    VALID_BM25_STOPWORD_PROFILES,
    VALID_RETRIEVAL_BACKENDS,
    _apply_bm25_extra_filter,
    analyze_query,
    bm25_scores_for_index,
    build_index_payload,
    get_or_build_bm25,
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
        bm25_stopword_profile: str = "shared",
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
            bm25_stopword_profile=bm25_stopword_profile,
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
        # Issue #151 — ``m3`` joins the allow-list as the third opt-in
        # backend (BGE-M3 dense + sparse + ColBERT multi-vector fused
        # via N-way RRF). Default remains ``dense``; ``hybrid`` is
        # unchanged. See ``docs/vision/m3-multichannel-spike.md``.
        # Issue #938 / ADR 0053 — ``random`` is the 4th member: the
        # distinguishing-power floor (uniform random ranking over
        # filtered candidates, no embedding / BM25 / M3 forward pass).
        self.assertEqual(
            {"dense", "hybrid", "m3", "random"}, VALID_RETRIEVAL_BACKENDS
        )

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
        normalized RRF score spread across the top-K must differ between
        these two regimes by more than rounding noise.

        Note: under ADR 0050's expanded corpus the top-1 chunk is rank 0
        in BOTH dense and BM25 channels for the answerable query, so its
        normalized score saturates at 1.0 in every ``rrf_k`` regime
        (``rrf * rrf_norm`` = ``N/k * k/N`` = 1). The differentiation
        shows up on lower-ranked chunks where ranks diverge across
        channels — pin the last-of-top-K score, which moves cleanly.
        """
        evidence_k10 = self._retrieve_with_backend(
            ANSWERABLE_QUERY, "hybrid", rrf_k=10
        )
        evidence_k200 = self._retrieve_with_backend(
            ANSWERABLE_QUERY, "hybrid", rrf_k=200
        )
        self.assertGreater(len(evidence_k10), 1)
        self.assertGreater(len(evidence_k200), 1)
        self.assertEqual(len(evidence_k10), len(evidence_k200))
        self.assertNotAlmostEqual(
            evidence_k10[-1]["score"],
            evidence_k200[-1]["score"],
            places=3,
            msg="rrf_k override should change the lower-ranked normalized scores",
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

    # -- Issue #150 — BM25 stopword profile knob --------------------

    def test_default_bm25_stopword_profile_is_shared(self) -> None:
        """Plan-time default for ``bm25_stopword_profile`` is ``"shared"`` —
        the existing BM25 path stays bit-stable when callers omit the knob.
        """
        analysis = analyze_query(ANSWERABLE_QUERY, metadata_targets(self.index))
        plan = make_plan(analysis, top_k=4, retrieval_backend="hybrid")
        self.assertEqual("shared", plan["bm25_stopword_profile"])

    def test_valid_bm25_stopword_profiles_constant(self) -> None:
        self.assertEqual({"shared", "bm25_extra"}, VALID_BM25_STOPWORD_PROFILES)

    def test_resolve_pipeline_config_rejects_invalid_profile(self) -> None:
        with self.assertRaises(ValueError):
            resolve_pipeline_config(
                {
                    "pipeline": "agentic_full",
                    "retrieval_backend": "hybrid",
                    "bm25_stopword_profile": "kkma",
                }
            )

    def test_make_plan_rejects_invalid_profile(self) -> None:
        analysis = analyze_query(ANSWERABLE_QUERY, metadata_targets(self.index))
        with self.assertRaises(ValueError):
            make_plan(
                analysis,
                retrieval_backend="hybrid",
                bm25_stopword_profile="splade",
            )

    def test_bm25_extra_strips_까지_부터_suffixes(self) -> None:
        """``_apply_bm25_extra_filter`` removes ``까지`` / ``부터`` / etc.
        from the BM25 input tokens (issue #150 user-listed particles).

        Mirrors the existing :func:`normalize_metadata_token`
        invariant: a suffix is stripped only if the remaining stem is
        ≥ 2 Hangul characters (otherwise the token would collapse to a
        meaningless 1-char fragment). So ``기관까지`` → ``기관`` but a
        3-char input like ``주마다`` (stem ``주``) is left unchanged.
        """
        filtered = _apply_bm25_extra_filter(
            ["기관까지", "보안부터", "월간마다", "정상", "주마다"]
        )
        self.assertEqual(
            ["기관", "보안", "월간", "정상", "주마다"],
            filtered,
        )

    def test_bm25_extra_drops_extra_stopwords(self) -> None:
        filtered = _apply_bm25_extra_filter(["또한", "또는", "보안"])
        self.assertEqual(["보안"], filtered)
        # Sanity: every BM25_EXTRA_STOPWORDS member is dropped.
        for sw in BM25_EXTRA_STOPWORDS:
            self.assertEqual([], _apply_bm25_extra_filter([sw]))

    def test_bm25_cache_is_keyed_by_profile(self) -> None:
        """Two profiles produce two distinct BM25Okapi instances in
        ``index["_bm25_by_profile"]`` — they must not collide.
        """
        bm25_shared, _ = get_or_build_bm25(self.index, "shared")
        bm25_extra, _ = get_or_build_bm25(self.index, "bm25_extra")
        self.assertIsNot(bm25_shared, bm25_extra)
        # Calling again returns the cached instances unchanged.
        self.assertIs(bm25_shared, get_or_build_bm25(self.index, "shared")[0])
        self.assertIs(bm25_extra, get_or_build_bm25(self.index, "bm25_extra")[0])

    def test_dense_path_unaffected_by_bm25_stopword_profile(self) -> None:
        """``retrieval_backend="dense"`` is byte-stable across profiles.

        BM25 is not consulted on the dense path; the profile knob must
        therefore produce **identical** evidence (chunk_id, score) lists.
        This locks in the ADR 0001 / issue #150 acceptance criterion.
        """
        r_shared = self._retrieve_with_backend(
            ANSWERABLE_QUERY, "dense", bm25_stopword_profile="shared"
        )
        r_extra = self._retrieve_with_backend(
            ANSWERABLE_QUERY, "dense", bm25_stopword_profile="bm25_extra"
        )
        self.assertEqual(
            [(it["chunk_id"], it["score"]) for it in r_shared],
            [(it["chunk_id"], it["score"]) for it in r_extra],
        )

    def test_hybrid_profile_changes_query_side_scoring(self) -> None:
        """Under hybrid retrieval, a query containing ``까지`` / ``부터``
        gets different BM25 scores between profiles — the bm25_extra
        profile strips those suffixes before BM25 sees them.
        """
        analysis = analyze_query(ANSWERABLE_QUERY, metadata_targets(self.index))
        query_tokens = list(analysis.get("tokens") or []) + ["기관까지", "보안부터"]
        scores_shared = bm25_scores_for_index(
            self.index, query_tokens, stopword_profile="shared"
        )
        scores_extra = bm25_scores_for_index(
            self.index, query_tokens, stopword_profile="bm25_extra"
        )
        self.assertEqual(scores_shared.keys(), scores_extra.keys())
        # Some chunk must score differently between the two profiles
        # (the suffix-stripped versions resolve to different BM25 terms).
        self.assertTrue(
            any(
                abs(scores_shared[cid] - scores_extra[cid]) > 1e-9
                for cid in scores_shared
            ),
            "bm25_extra profile should produce observably different scores "
            "for queries carrying the additional particle suffixes",
        )

    def test_diagnostics_surface_bm25_stopword_profile(self) -> None:
        result = run_rag_query(
            self.index,
            ANSWERABLE_QUERY,
            retrieval_backend="hybrid",
            bm25_stopword_profile="bm25_extra",
        )
        self.assertEqual("bm25_extra", result["plan"]["bm25_stopword_profile"])
        self.assertEqual(
            "bm25_extra", result["diagnostics"]["bm25_stopword_profile"]
        )

    def test_bm25_extra_particle_list_includes_까지_부터(self) -> None:
        """The BM25-only particle list explicitly carries the
        user-listed missing particles from issue #150.
        """
        self.assertIn("까지", BM25_EXTRA_PARTICLE_SUFFIXES)
        self.assertIn("부터", BM25_EXTRA_PARTICLE_SUFFIXES)


if __name__ == "__main__":
    unittest.main()
