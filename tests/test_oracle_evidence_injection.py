"""Oracle-evidence injection ceiling probe (P0-a, issue #1282).

Locks the eval-only oracle path that bypasses retrieval to measure the
verify+answer ceiling:

* ``build_oracle_evidence`` projects a case's gold chunks into the retrieval
  evidence shape (parity with ``rag_retrieval`` items).
* ``run_rag_query_with_oracle_evidence`` feeds those gold chunks straight to
  verify+answer, surfacing a grounded answer even when the default retriever
  would miss them — the ceiling lift.
* An empty-gold (abstention) case still abstains — the oracle never
  fabricates evidence.
* The new ``oracle_evidence_source`` config field defaults empty, so existing
  ablation summaries stay byte-equal (ADR 0001).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_eval import (  # noqa: E402
    build_oracle_evidence,
    normalize_run_config,
)
from eval.scorers import derive_gold_chunk_ids  # noqa: E402
from rag_core import (  # noqa: E402
    build_index_payload_from_documents,
    run_rag_query_with_oracle_evidence,
)

# A gold doc whose answer-bearing chunk uses vocabulary disjoint from the
# query, plus distractor docs that lexically match the query but carry no
# answer term — so the default hashing retriever ranks distractors first and
# (at a small top_k) misses the gold chunk.
_GOLD_TERM = "사업금액은 1억2천만원"
_DOCS = [
    {
        "doc_id": "gold-doc",
        "title": "조달청 통합관제 시스템 구축 사업",
        "agency": "조달청",
        "project": "통합관제 시스템 구축",
        "metadata": {},
        "sections": [{"heading": "예산", "text": f"본 사업의 {_GOLD_TERM}으로 책정되었다."}],
        "source_path": "gold-doc.txt",
    },
]
_DISTRACTORS = [
    {
        "doc_id": f"distractor-{i}",
        "title": f"무관 기관 {i} 보안 점검 용역",
        "agency": f"무관 기관 {i}",
        "project": "보안 점검 용역",
        "metadata": {},
        "sections": [
            {"heading": "개요", "text": "보안 점검 용역의 범위와 일정에 관한 일반 설명."}
        ],
        "source_path": f"distractor-{i}.txt",
    }
    for i in range(6)
]


def _index():
    return build_index_payload_from_documents(
        _DOCS + _DISTRACTORS,
        source_dir="test-fixture",
        embedding_backend="hashing",
    )


# Phrasing chosen empirically: analyze_query classifies it as answerable
# (single_doc), yet the default hashing retriever returns no usable evidence
# (status=insufficient, evidence=[]) — exactly the retrieval-miss the oracle
# path is meant to lift past.
_GOLD_CASE = {
    "id": "oracle-gold-1",
    "query": "조달청의 통합관제 시스템 구축 사업 예산은 얼마인가?",
    "query_type": "single_doc",
    "expected_doc_ids": ["gold-doc"],
    "expected_terms": [_GOLD_TERM],
}
_ABSTENTION_CASE = {
    "id": "oracle-abstain-1",
    "query": "존재하지 않는 사업의 예산은?",
    "query_type": "abstention",
    "expected_doc_ids": [],
    "expected_terms": [],
}


class BuildOracleEvidenceTest(unittest.TestCase):
    def test_projects_gold_chunks_with_parity_keys(self) -> None:
        index = _index()
        ev = build_oracle_evidence(_GOLD_CASE, index)
        self.assertTrue(ev, "gold case must yield at least one oracle evidence item")
        gold_ids = set(derive_gold_chunk_ids(_GOLD_CASE, index))
        self.assertEqual({e["chunk_id"] for e in ev}, gold_ids)
        # Shape parity with rag_retrieval evidence items consumed downstream.
        required = {
            "doc_id", "chunk_id", "title", "agency", "project", "metadata",
            "section", "section_id", "parent_section_id", "section_path",
            "text", "score", "score_parts", "retrieval_mode",
        }
        for item in ev:
            self.assertTrue(required.issubset(item.keys()))
            self.assertEqual(item["retrieval_mode"], "oracle")
            self.assertEqual(item["score"], 1.0)

    def test_empty_gold_yields_no_evidence(self) -> None:
        self.assertEqual(build_oracle_evidence(_ABSTENTION_CASE, _index()), [])

    def test_doc_level_fallback_when_terms_unmatched(self) -> None:
        # expected_terms that appear in NO chunk → chunk-level gold empty,
        # but expected_doc_ids present → fall back to all chunks of the doc.
        index = _index()
        unmatched_case = {
            "id": "oracle-doclevel-1",
            "query": _GOLD_CASE["query"],
            "query_type": "single_doc",
            "expected_doc_ids": ["gold-doc"],
            "expected_terms": ["존재하지않는토큰xyz"],
        }
        self.assertEqual(derive_gold_chunk_ids(unmatched_case, index), [])
        ev = build_oracle_evidence(unmatched_case, index)
        self.assertTrue(ev, "doc-level fallback must inject the gold doc's chunks")
        self.assertTrue(all(e["doc_id"] == "gold-doc" for e in ev))

    def test_no_expected_doc_ids_yields_no_evidence(self) -> None:
        # No doc anchor at all → fallback cannot fire → empty (abstain).
        case = {"id": "x", "query": "q", "query_type": "abstention",
                "expected_doc_ids": [], "expected_terms": ["무관"]}
        self.assertEqual(build_oracle_evidence(case, _index()), [])


class OracleBypassTest(unittest.TestCase):
    def test_answer_uses_injected_evidence_not_retrieval(self) -> None:
        """Retrieval is bypassed: the answer is grounded on the injected
        chunks, not on what the retriever would return for this query.

        Proof is deterministic regardless of hashing-retrieval quirks: we
        inject a *distractor* chunk that the retriever would never surface
        for the gold query, and assert the answer's evidence is exactly that
        injected chunk. ``verifier_retry=False`` isolates the bypass from the
        topic verifier (a legitimate ablation arm).
        """
        index = _index()
        # Build an oracle evidence item for a distractor chunk the retriever
        # would never return for the gold query.
        distractor_case = {
            "id": "inject-distractor",
            "query": _GOLD_CASE["query"],
            "query_type": "single_doc",
            "expected_doc_ids": ["distractor-0"],
            "expected_terms": ["보안 점검 용역"],
        }
        injected = build_oracle_evidence(distractor_case, index)
        self.assertTrue(injected, "fixture must yield a distractor chunk to inject")
        oracle = run_rag_query_with_oracle_evidence(
            index,
            _GOLD_CASE["query"],
            injected,
            top_k=4,
            pipeline="agentic_full",
            verifier_retry=False,
        )
        ev_ids = {e.get("chunk_id") for e in oracle.get("evidence") or []}
        self.assertEqual(ev_ids, {injected[0]["chunk_id"]})
        self.assertEqual(oracle["answer"]["status"], "supported")

    def test_injected_gold_yields_grounded_answer(self) -> None:
        """Gold chunks injected via build_oracle_evidence flow through
        verify+answer to a supported answer (verifier_retry=False isolates
        the retrieval-bypass mechanism from the topic verifier)."""
        index = _index()
        gold_ids = set(derive_gold_chunk_ids(_GOLD_CASE, index))
        oracle = run_rag_query_with_oracle_evidence(
            index,
            _GOLD_CASE["query"],
            build_oracle_evidence(_GOLD_CASE, index),
            top_k=4,
            pipeline="agentic_full",
            verifier_retry=False,
        )
        oracle_ids = {e.get("chunk_id") for e in oracle.get("evidence") or []}
        self.assertEqual(oracle_ids, gold_ids)
        self.assertEqual(oracle["answer"]["status"], "supported")

    def test_oracle_path_abstains_on_empty_gold(self) -> None:
        index = _index()
        pred = run_rag_query_with_oracle_evidence(
            index,
            _ABSTENTION_CASE["query"],
            build_oracle_evidence(_ABSTENTION_CASE, index),
            pipeline="agentic_full",
        )
        self.assertEqual(pred["answer"]["status"], "insufficient")


class ConfigByteIdentityTest(unittest.TestCase):
    def test_oracle_source_defaults_empty(self) -> None:
        cfg = normalize_run_config({"name": "full", "pipeline": "agentic_full"})
        self.assertEqual(cfg["oracle_evidence_source"], "")

    def test_oracle_source_parsed_from_raw_row(self) -> None:
        cfg = normalize_run_config(
            {"name": "oracle", "pipeline": "agentic_full", "oracle_evidence_source": "gold"}
        )
        self.assertEqual(cfg["oracle_evidence_source"], "gold")


if __name__ == "__main__":
    unittest.main()
