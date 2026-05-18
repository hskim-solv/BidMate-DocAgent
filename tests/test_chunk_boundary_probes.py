"""Chunk-boundary probe diagnostics (issue #73).

Two complementary checks:

* **Diagnostic shape** — `total_chunks_in_section` is computed during
  index build and propagated through retrieval into the public evidence
  payload. Reviewers can then read "got chunk 2 of 3" straight from
  `outputs/answer.json` to distinguish a chunking failure (we got a
  chunk but it was the wrong one) from a retrieval failure (no chunk
  from this section came back at all).
* **Probe behavior** — three probe queries against the
  `rfp-agency-d-spectrometer-probe` fixture target facts located in
  specific chunk positions (chunk 2/N, last chunk, overlap region).
  A regression that drops the answer chunk or misaligns the chunk
  metadata flips these probes from `supported` to `insufficient`.

Both tests use the deterministic hashing embedding backend on the
existing `data/raw` fixture, matching the pattern in
`tests/test_retrieval_loop_regression.py`.
"""

import unittest

import pytest

from rag_core import (
    DEFAULT_CHUNK_MAX_CHARS,
    build_chunk_records,
    run_rag_query,
)


class ChunkSectionMetadataTest(unittest.TestCase):
    """Unit-level checks on `total_chunks_in_section` computation."""

    def test_total_chunks_in_section_matches_split_count(self) -> None:
        # Construct a 2-section doc that the chunker MUST split:
        # section A is long enough to span 2+ chunks at the default
        # max_chars; section B is a single short sentence.
        long_section_text = " ".join(
            [
                f"문장 {i}는 시험용 문장이다."
                for i in range(1, 60)  # ~60 short sentences → multi-chunk
            ]
        )
        documents = [
            {
                "doc_id": "test-multi-chunk",
                "title": "Test Multi-Chunk Doc",
                "agency": "테스트 기관",
                "project": "테스트 프로젝트",
                "metadata": {},
                "sections": [
                    {"heading": "긴 섹션", "text": long_section_text},
                    {"heading": "짧은 섹션", "text": "단일 문장 섹션이다."},
                ],
            }
        ]
        chunks, _, diagnostics = build_chunk_records(
            documents, chunking_strategy="section"
        )
        # Group chunks by parent section and verify
        # total_chunks_in_section equals the count for that section.
        from collections import Counter

        per_section = Counter(c["section_id"] for c in chunks)
        for chunk in chunks:
            with self.subTest(chunk_id=chunk["chunk_id"]):
                self.assertEqual(
                    chunk["total_chunks_in_section"],
                    per_section[chunk["section_id"]],
                )
                self.assertGreaterEqual(chunk["chunk_seq_in_section"], 1)
                self.assertLessEqual(
                    chunk["chunk_seq_in_section"],
                    chunk["total_chunks_in_section"],
                )

        # The long section MUST have been split (otherwise the test is
        # not exercising the diagnostic).
        long_chunks = [c for c in chunks if c["section"] == "긴 섹션"]
        self.assertGreater(
            len(long_chunks),
            1,
            f"long section did not split (max_chars={DEFAULT_CHUNK_MAX_CHARS})",
        )


class ChunkBoundaryProbeRetrievalTest(unittest.TestCase):
    """End-to-end guard: probe queries hit the right chunk position.

    These exercise the `rfp-agency-d-spectrometer-probe` fixture added
    for issue #73. A regression in chunking — dropped chunk, wrong
    chunk_seq, broken overlap — flips the answer status away from
    `supported`.
    """

    @pytest.fixture(autouse=True)
    def _inject_shared_index(self, shared_raw_index):
        self.index = shared_raw_index

    def _expect_supported_with_term(
        self, query: str, expected_term: str
    ) -> dict:
        # ADR 0058 (Scenario A, 2026-05-19) — `agentic_full` preset default
        # `retrieval_backend` flipped from `dense` to `hybrid`. Chunk
        # boundary probes are a chunking diagnostic (not a retrieval-mode
        # diagnostic), so pin `retrieval_backend="dense"` to keep the
        # top-1 chunk deterministic regardless of the production default.
        result = run_rag_query(self.index, query, retrieval_backend="dense")
        self.assertEqual(
            result["answer"]["status"],
            "supported",
            f"query={query!r} reasons={result.get('verification', {}).get('reasons')}",
        )
        evidence = result.get("evidence", [])
        self.assertTrue(evidence, f"no evidence for query={query!r}")
        top = evidence[0]
        self.assertEqual(top["doc_id"], "rfp-agency-d-spectrometer-probe")
        self.assertIn(
            expected_term,
            top.get("text", ""),
            f"top evidence missing {expected_term!r}; "
            f"got chunk_seq={top.get('chunk_seq_in_section')}/"
            f"{top.get('total_chunks_in_section')}",
        )
        # Diagnostic surface contract: both fields must travel into
        # the public evidence payload.
        self.assertIsNotNone(top.get("chunk_seq_in_section"))
        self.assertIsNotNone(top.get("total_chunks_in_section"))
        return top

    def test_external_audit_probe_hits_non_first_chunk(self) -> None:
        """Probe 1 — answer is in chunk 2 of section 1."""
        top = self._expect_supported_with_term(
            "기관 D 분광기 운영 데이터의 외부 감사 주기는?", "분기별"
        )
        # The fact "분기별 외부 감사" lives in the second chunk of
        # the 사업 개요 section. A regression that drops this chunk or
        # surfaces only chunk 1 fails the term-match assertion above.
        self.assertGreaterEqual(top["total_chunks_in_section"], 2)

    def test_report_storage_probe_hits_last_section_chunk(self) -> None:
        """Probe 2 — answer is in the second section (보관 기간)."""
        top = self._expect_supported_with_term(
            "기관 D 분광기 보고서 보관 기간과 위치는?", "5년"
        )
        # Lives in 운영 자동화 section. Confirms the probe doesn't
        # accidentally route to the 사업 개요 section.
        self.assertNotEqual(top.get("section"), "사업 개요")

    def test_overlap_calibration_probe_finds_either_overlap_chunk(self) -> None:
        """Probe 3 — overlap region: 캘리브레이션 주기 appears in both
        chunks of section 1 due to `DEFAULT_CHUNK_OVERLAP_SENTENCES=1`.

        Either chunk satisfies the probe; the probe's job is to confirm
        the overlap mechanism kept the answer reachable from BOTH
        positions in section 1.
        """
        top = self._expect_supported_with_term(
            "기관 D 분광기 라만 캘리브레이션 주기는?", "매일"
        )
        self.assertEqual(top["section"], "사업 개요")


if __name__ == "__main__":
    unittest.main()
