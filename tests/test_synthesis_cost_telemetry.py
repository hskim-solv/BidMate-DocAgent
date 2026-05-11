"""Cost telemetry contract for the LLM synthesis path (ADR 0011 + ADR 0015).

Locks the pricing-card semantics and the cache-token capture surface so
the LLM Ops portfolio claim ("we track token spend and cache hit rate
per query") is backed by a regression test, not just an env-time wish.

Coverage:

* ``compute_cost_usd`` reflects the per-Mtok price table for input,
  output, and cache-read/write tokens with the standard 0.1x / 1.25x
  modifiers.
* Unknown models (``stub`` / arbitrary OpenAI-compatible deployments)
  return ``None`` — we do not invent a price for them.
* ``synthesize_answer`` surfaces ``cache_read_tokens`` /
  ``cache_write_tokens`` / ``cost_estimate_usd`` in the meta dict for
  any backend that returns them in its payload.
* The synthesizer ``schema_version`` bumped to 2; downstream consumers
  that pin to v1 must be updated explicitly (no silent drift).
"""

from __future__ import annotations

import unittest

import rag_synthesis


def _make_answer():
    return {
        "schema_version": 2,
        "status": "supported",
        "status_reason": {"code": "verified", "verified": True, "verification_reasons": []},
        "query_type": "single_doc",
        "summary": "기관 A는 보안 통제와 로그 추적이 필요하다.",
        "claims": [
            {
                "target": "기관 A",
                "claim": "보안 통제 매뉴얼과 로그 추적 시스템을 구축한다",
                "support": [],
                "citations": [{"doc_id": "rfp-a", "chunk_id": "rfp-a::chunk-001"}],
            }
        ],
        "insufficiency": None,
    }


def _make_evidence():
    return [
        {
            "chunk_id": "rfp-a::chunk-001",
            "doc_id": "rfp-a",
            "agency": "기관 A",
            "text": "제안사는 보안 통제 매뉴얼과 로그 추적 시스템을 구축해야 한다.",
        }
    ]


class ComputeCostUsdTest(unittest.TestCase):
    def test_unknown_model_returns_none(self) -> None:
        self.assertIsNone(
            rag_synthesis.compute_cost_usd(
                model="not-a-real-model", tokens_in=1000, tokens_out=500
            )
        )

    def test_none_model_returns_none(self) -> None:
        self.assertIsNone(
            rag_synthesis.compute_cost_usd(model=None, tokens_in=10, tokens_out=10)
        )

    def test_sonnet_input_output_only(self) -> None:
        # Sonnet 4.6: $3 / Mtok input, $15 / Mtok output.
        # 1_000_000 input + 1_000_000 output = $3 + $15 = $18.00.
        cost = rag_synthesis.compute_cost_usd(
            model="claude-sonnet-4-6", tokens_in=1_000_000, tokens_out=1_000_000
        )
        self.assertAlmostEqual(cost, 18.0, places=6)

    def test_cache_read_uses_discount(self) -> None:
        # Cache read = 0.1x input = $0.30 / Mtok on Sonnet 4.6.
        cost = rag_synthesis.compute_cost_usd(
            model="claude-sonnet-4-6",
            tokens_in=0,
            tokens_out=0,
            cache_read_tokens=1_000_000,
        )
        self.assertAlmostEqual(cost, 0.30, places=6)

    def test_cache_write_uses_surcharge(self) -> None:
        # Cache write = 1.25x input = $3.75 / Mtok on Sonnet 4.6.
        cost = rag_synthesis.compute_cost_usd(
            model="claude-sonnet-4-6",
            tokens_in=0,
            tokens_out=0,
            cache_write_tokens=1_000_000,
        )
        self.assertAlmostEqual(cost, 3.75, places=6)

    def test_full_breakdown_sums(self) -> None:
        # Hand-computed: Sonnet 4.6 on 1k input + 500 output + 800 cache_read
        # + 200 cache_write
        # = 1000*3/1e6 + 500*15/1e6 + 800*0.3/1e6 + 200*3.75/1e6
        # = 0.003 + 0.0075 + 0.00024 + 0.00075 = 0.011490
        cost = rag_synthesis.compute_cost_usd(
            model="claude-sonnet-4-6",
            tokens_in=1000,
            tokens_out=500,
            cache_read_tokens=800,
            cache_write_tokens=200,
        )
        self.assertAlmostEqual(cost, 0.01149, places=6)

    def test_versioned_model_id_matches_prefix(self) -> None:
        # The lookup must accept dated SKUs like ``claude-sonnet-4-6-20260301``.
        cost = rag_synthesis.compute_cost_usd(
            model="claude-sonnet-4-6-20260301", tokens_in=1_000_000, tokens_out=0
        )
        self.assertAlmostEqual(cost, 3.0, places=6)

    def test_zero_tokens_zero_cost(self) -> None:
        cost = rag_synthesis.compute_cost_usd(
            model="claude-sonnet-4-6", tokens_in=0, tokens_out=0
        )
        self.assertEqual(cost, 0.0)


class SynthesisMetaSurfaceTest(unittest.TestCase):
    def test_schema_version_is_2(self) -> None:
        # v2 introduces the cost telemetry fields. Downstream consumers
        # that pin to v1 must update explicitly — see ADR 0015.
        self.assertEqual(rag_synthesis.SYNTHESIS_SCHEMA_VERSION, 2)

    def test_meta_exposes_cache_and_cost_keys_even_for_stub(self) -> None:
        _, meta = rag_synthesis.synthesize_answer(
            query="기관 A의 보안 통제 요구사항은?",
            analysis={"query_type": "single_doc", "entities": ["기관 A"]},
            answer=_make_answer(),
            evidence=_make_evidence(),
            backend="stub",
        )
        # Keys must always be present so dashboards don't trip on missing fields.
        for key in ("cache_read_tokens", "cache_write_tokens", "cost_estimate_usd"):
            self.assertIn(key, meta, f"meta missing key: {key}")
        # Stub backend does not invent prices.
        self.assertIsNone(meta["cost_estimate_usd"])

    def test_meta_promotes_payload_cache_tokens(self) -> None:
        # A backend that returns cache token counts must surface them
        # in meta and yield a non-None cost when the model is priced.
        original = rag_synthesis._BACKENDS["stub"]

        def priced_backend(*, query, analysis, answer, evidence):
            return {
                "summary": "기관 A는 보안 통제 매뉴얼과 로그 추적을 요구한다.",
                "used_chunk_ids": ["rfp-a::chunk-001"],
                "model": "claude-sonnet-4-6",
                "tokens_in": 100,
                "tokens_out": 50,
                "cache_read_tokens": 2000,
                "cache_write_tokens": 500,
            }

        rag_synthesis._BACKENDS["stub"] = priced_backend
        try:
            _, meta = rag_synthesis.synthesize_answer(
                query="기관 A의 보안 통제 요구사항은?",
                analysis={"query_type": "single_doc"},
                answer=_make_answer(),
                evidence=_make_evidence(),
                backend="stub",
            )
        finally:
            rag_synthesis._BACKENDS["stub"] = original

        self.assertEqual(meta["tokens_in"], 100)
        self.assertEqual(meta["tokens_out"], 50)
        self.assertEqual(meta["cache_read_tokens"], 2000)
        self.assertEqual(meta["cache_write_tokens"], 500)
        # 100*3/1e6 + 50*15/1e6 + 2000*0.3/1e6 + 500*3.75/1e6
        # = 0.0003 + 0.00075 + 0.0006 + 0.001875 = 0.003525
        self.assertAlmostEqual(meta["cost_estimate_usd"], 0.003525, places=6)


if __name__ == "__main__":
    unittest.main()
