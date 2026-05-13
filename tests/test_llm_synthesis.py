"""Contract tests for ADR 0011 — LLM answer synthesis as additive ablation.

The synthesizer is *additive*: it rewrites only ``summary`` and
``answer_text``. ``status``, ``claims``, ``citations``, ``insufficiency``,
and ``status_reason`` stay under the deterministic verifier. Any
synthesized output that references a chunk_id outside the evidence list
must be rejected and the deterministic answer kept.

These tests lock the contract on three surfaces:

* unit-level guards on ``rag_synthesis.synthesize_answer``
* the pass-through stub backend (used by public CI per ADR 0011)
* the end-to-end ``agentic_full_llm`` pipeline preset returning a
  zero-regression answer dict against the same query as ``agentic_full``
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import rag_synthesis
from rag_answer_schema import ANSWER_SCHEMA_VERSION
from rag_core import build_index_payload, run_rag_query


ANSWERABLE_QUERY = "기관 A의 보안 통제 요구사항은?"


def _make_answer() -> dict[str, Any]:
    return {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "status": "supported",
        "status_reason": {"code": "verified", "verified": True, "verification_reasons": []},
        "query_type": "single_doc",
        "summary": "기관 A는 보안 통제 매뉴얼과 로그 추적이 필요하다.",
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


def _make_evidence() -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": "rfp-a::chunk-001",
            "doc_id": "rfp-a",
            "agency": "기관 A",
            "text": "제안사는 보안 통제 매뉴얼과 로그 추적 시스템을 구축해야 한다.",
        }
    ]


class SynthesisUnitTest(unittest.TestCase):
    def test_stub_backend_passes_through_summary(self) -> None:
        answer = _make_answer()
        original_summary = answer["summary"]
        updated, meta = rag_synthesis.synthesize_answer(
            query=ANSWERABLE_QUERY,
            analysis={"query_type": "single_doc", "entities": ["기관 A"]},
            answer=answer,
            evidence=_make_evidence(),
            backend="stub",
        )
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["summary"], original_summary)
        self.assertEqual(updated["claims"], answer["claims"])
        self.assertEqual(updated["status"], "supported")
        self.assertFalse(meta["fell_back"])
        self.assertEqual(meta["backend"], "stub")
        self.assertEqual(meta["used_chunk_ids"], ["rfp-a::chunk-001"])

    def test_unknown_backend_falls_back(self) -> None:
        updated, meta = rag_synthesis.synthesize_answer(
            query=ANSWERABLE_QUERY,
            analysis={"query_type": "single_doc"},
            answer=_make_answer(),
            evidence=_make_evidence(),
            backend="hypothetical_backend",
        )
        self.assertIsNone(updated)
        self.assertTrue(meta["fell_back"])
        self.assertTrue(meta["fallback_reason"].startswith("unknown_backend"))

    def test_no_evidence_falls_back(self) -> None:
        updated, meta = rag_synthesis.synthesize_answer(
            query=ANSWERABLE_QUERY,
            analysis={"query_type": "single_doc"},
            answer=_make_answer(),
            evidence=[],
            backend="stub",
        )
        self.assertIsNone(updated)
        self.assertEqual(meta["fallback_reason"], "no_evidence_chunks")

    def test_unauthorized_chunk_id_falls_back(self) -> None:
        # ADR 0011 hard postcondition: any chunk_id outside evidence
        # rejects the synthesis and keeps the deterministic answer.
        original = rag_synthesis._BACKENDS["stub"]

        def rogue(*, query, analysis, answer, evidence):  # type: ignore[no-untyped-def]
            return {
                "summary": "기관 A는 위조 인용을 포함한다.",
                "used_chunk_ids": ["rfp-z::not-in-evidence"],
                "model": "rogue",
            }

        rag_synthesis._BACKENDS["stub"] = rogue
        try:
            updated, meta = rag_synthesis.synthesize_answer(
                query=ANSWERABLE_QUERY,
                analysis={"query_type": "single_doc"},
                answer=_make_answer(),
                evidence=_make_evidence(),
                backend="stub",
            )
        finally:
            rag_synthesis._BACKENDS["stub"] = original
        self.assertIsNone(updated)
        self.assertTrue(meta["fallback_reason"].startswith("unauthorized_chunk_ids"))

    def test_chunk_id_outside_claim_citations_falls_back(self) -> None:
        # An evidence chunk that no claim cites must not appear as a
        # synthesis citation either — otherwise the LLM could weave in
        # support from a chunk the verifier explicitly dropped.
        original = rag_synthesis._BACKENDS["stub"]

        def stray_cite(*, query, analysis, answer, evidence):  # type: ignore[no-untyped-def]
            return {
                "summary": "기관 A는 보안 통제가 필요하다.",
                "used_chunk_ids": ["rfp-a::chunk-001", "rfp-a::chunk-stray"],
                "model": "stray",
            }

        evidence = _make_evidence() + [
            {
                "chunk_id": "rfp-a::chunk-stray",
                "doc_id": "rfp-a",
                "agency": "기관 A",
                "text": "이 청크는 어떤 claim에도 인용되지 않은 부수 청크다.",
            }
        ]

        rag_synthesis._BACKENDS["stub"] = stray_cite
        try:
            updated, meta = rag_synthesis.synthesize_answer(
                query=ANSWERABLE_QUERY,
                analysis={"query_type": "single_doc"},
                answer=_make_answer(),
                evidence=evidence,
                backend="stub",
            )
        finally:
            rag_synthesis._BACKENDS["stub"] = original
        self.assertIsNone(updated)
        self.assertTrue(meta["fallback_reason"].startswith("chunks_outside_claims"))

    def test_backend_exception_falls_back(self) -> None:
        original = rag_synthesis._BACKENDS["stub"]

        def broken(*, query, analysis, answer, evidence):  # type: ignore[no-untyped-def]
            raise RuntimeError("simulated backend outage")

        rag_synthesis._BACKENDS["stub"] = broken
        try:
            updated, meta = rag_synthesis.synthesize_answer(
                query=ANSWERABLE_QUERY,
                analysis={"query_type": "single_doc"},
                answer=_make_answer(),
                evidence=_make_evidence(),
                backend="stub",
            )
        finally:
            rag_synthesis._BACKENDS["stub"] = original
        self.assertIsNone(updated)
        self.assertTrue(meta["fallback_reason"].startswith("backend_error"))
        self.assertIsNotNone(meta["latency_ms"])

    def test_anthropic_backend_raises_without_api_key(self) -> None:
        # The pipeline wraps the call in a try/except and falls back; the
        # backend itself raises a clear RuntimeError so the meta
        # carries an actionable reason.
        import os

        prior = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            updated, meta = rag_synthesis.synthesize_answer(
                query=ANSWERABLE_QUERY,
                analysis={"query_type": "single_doc"},
                answer=_make_answer(),
                evidence=_make_evidence(),
                backend="anthropic",
            )
        finally:
            if prior is not None:
                os.environ["ANTHROPIC_API_KEY"] = prior
        self.assertIsNone(updated)
        self.assertTrue(meta["fell_back"])
        self.assertIn("backend_error", meta["fallback_reason"])


class SynthesisPipelineIntegrationTest(unittest.TestCase):
    """End-to-end: ``agentic_full_llm`` with stub backend must be a
    zero-regression contract test against ``agentic_full``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_index_payload(
            Path("data/raw"),
            embedding_backend="hashing",
        )

    def test_stub_synthesis_preserves_extractive_answer(self) -> None:
        extractive = run_rag_query(
            self.index, ANSWERABLE_QUERY, pipeline="agentic_full"
        )
        synthesized = run_rag_query(
            self.index, ANSWERABLE_QUERY, pipeline="agentic_full_llm"
        )

        self.assertEqual(
            extractive["answer"]["status"],
            synthesized["answer"]["status"],
        )
        self.assertEqual(
            extractive["answer"]["claims"],
            synthesized["answer"]["claims"],
            "stub synthesis must not modify claims (ADR 0003 preserved)",
        )
        self.assertEqual(
            extractive["answer"]["summary"],
            synthesized["answer"]["summary"],
            "pass-through stub must keep the extractive summary verbatim",
        )
        self.assertEqual(
            extractive["answer"].get("insufficiency"),
            synthesized["answer"].get("insufficiency"),
        )
        self.assertEqual(
            extractive["answer"]["status_reason"],
            synthesized["answer"]["status_reason"],
        )

    def test_synthesis_meta_present_only_for_llm_preset(self) -> None:
        extractive = run_rag_query(
            self.index, ANSWERABLE_QUERY, pipeline="agentic_full"
        )
        synthesized = run_rag_query(
            self.index, ANSWERABLE_QUERY, pipeline="agentic_full_llm"
        )

        self.assertIsNone(extractive["diagnostics"].get("synthesis"))
        meta = synthesized["diagnostics"].get("synthesis")
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta["backend"], "stub")
        self.assertFalse(meta["fell_back"])
        self.assertIn("synthesis_ms", synthesized["diagnostics"]["stage_latency"])

    def test_naive_baseline_does_not_trigger_synthesis(self) -> None:
        # ADR 0001 invariant — naive_baseline never routes through the
        # LLM path even with synthesis available.
        baseline = run_rag_query(
            self.index, ANSWERABLE_QUERY, pipeline="naive_baseline"
        )
        self.assertIsNone(baseline["diagnostics"].get("synthesis"))
        self.assertNotIn("synthesis_ms", baseline["diagnostics"]["stage_latency"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
