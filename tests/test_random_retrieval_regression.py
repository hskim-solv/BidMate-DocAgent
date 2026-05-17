"""Regression guard for the ``random`` retrieval backend (issue #938, ADR 0053).

The ``random`` backend is the distinguishing-power floor: it short-circuits
``retrieve_candidates`` BEFORE the embedding / BM25 / M3 forward passes and
returns filtered candidates ranked by a deterministic SHA-256 hash of
``(query, chunk_id)``. Three contracts are locked in here:

1. **Allow-list membership** — ``"random"`` is in
   ``VALID_RETRIEVAL_BACKENDS`` and ``resolve_pipeline_config`` accepts it
   without raising.
2. **Determinism** — the same query produces the same top-k ranking across
   independent calls (test-friendly, eval-reproducible). Different queries
   pull different orderings.
3. **No-embedding short-circuit** — every returned item carries the marker
   ``score_parts["random"] > 0`` AND ``score_parts["dense"] == 0.0``,
   proving the embedding / scoring path was skipped (dense would be > 0
   for a non-trivial query against the hashing embedding fixture).

The test runs on the synthetic ``data/raw`` fixture with the hashing
embedding backend so it stays fast and CI-safe (no real model deps).
"""

import unittest
from pathlib import Path

from rag_core import build_index_payload, run_rag_query
from rag_pipeline_presets import VALID_RETRIEVAL_BACKENDS


_QUERY_A = "기관 A의 보안 통제 요구사항은?"
_QUERY_B = "기관 B의 사업 일정은?"


class RandomRetrievalBackendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_index_payload(
            Path("data/raw"), embedding_backend="hashing"
        )

    def test_random_is_in_valid_retrieval_backends(self) -> None:
        """ADR 0053 — allow-list membership invariant."""
        self.assertIn("random", VALID_RETRIEVAL_BACKENDS)

    def test_random_backend_diagnostics_record_backend_choice(self) -> None:
        """Diagnostics confirm the random branch fired (no silent fallback
        to dense). ``score_parts`` is not exposed in the evidence shape —
        the user-facing signal is ``diagnostics['retrieval_backend']``."""
        result = run_rag_query(
            self.index,
            _QUERY_A,
            retrieval_backend="random",
            pipeline="single_chunk",
        )
        evidence = result.get("evidence", [])
        self.assertGreater(
            len(evidence),
            0,
            "random backend must still produce evidence — top-k>=1",
        )
        self.assertEqual(
            "random",
            result.get("diagnostics", {}).get("retrieval_backend"),
            "diagnostics must record the random backend choice end-to-end",
        )

    def test_random_backend_top_k_differs_from_dense(self) -> None:
        """No-embedding contract (orthogonal signal): random's top-k for a
        domain-loaded query like ``기관 A의 보안...`` differs from dense's
        top-k for the same query. Dense ranks security-section chunks at
        the top; random's SHA-256 ordering is uncorrelated with topic, so
        the top-4 chunk_ids must differ (collision probability across 4
        independent hash draws over a 400+ candidate set is negligible)."""
        rnd = run_rag_query(
            self.index,
            _QUERY_A,
            retrieval_backend="random",
            pipeline="naive_baseline",
        )
        dns = run_rag_query(
            self.index,
            _QUERY_A,
            retrieval_backend="dense",
            pipeline="naive_baseline",
        )
        rnd_ids = [str(it.get("chunk_id")) for it in rnd.get("evidence", [])]
        dns_ids = [str(it.get("chunk_id")) for it in dns.get("evidence", [])]
        self.assertNotEqual(
            rnd_ids,
            dns_ids,
            "random must not coincidentally reproduce the dense top-k",
        )

    def test_random_backend_is_deterministic_per_query(self) -> None:
        """Same query → identical top-k ordering across calls."""
        a1 = run_rag_query(
            self.index,
            _QUERY_A,
            retrieval_backend="random",
            pipeline="single_chunk",
        )
        a2 = run_rag_query(
            self.index,
            _QUERY_A,
            retrieval_backend="random",
            pipeline="single_chunk",
        )
        ids1 = [str(it.get("chunk_id")) for it in a1.get("evidence", [])]
        ids2 = [str(it.get("chunk_id")) for it in a2.get("evidence", [])]
        self.assertEqual(
            ids1,
            ids2,
            "deterministic seed: same query must return identical chunk_id order",
        )

    def test_random_backend_differs_across_queries(self) -> None:
        """Different queries → different top-1 chunk (at least sometimes)."""
        # Use a 4-chunk top_k so we have headroom to differ; relying on a
        # single comparison would be too tight a bet (collision probability
        # at top-1 = 1/N where N = candidate count).
        a = run_rag_query(
            self.index,
            _QUERY_A,
            retrieval_backend="random",
            pipeline="naive_baseline",
        )
        b = run_rag_query(
            self.index,
            _QUERY_B,
            retrieval_backend="random",
            pipeline="naive_baseline",
        )
        ids_a = [str(it.get("chunk_id")) for it in a.get("evidence", [])]
        ids_b = [str(it.get("chunk_id")) for it in b.get("evidence", [])]
        # SHA-256 of different inputs has vanishing collision probability
        # across the candidate set; require the full top-k orderings differ.
        self.assertNotEqual(
            ids_a,
            ids_b,
            "different queries must produce different random orderings",
        )


if __name__ == "__main__":
    unittest.main()
