"""Unit tests for ``scripts/phase4_query_metadata_coverage`` — pin the
load-bearing classification logic the ADR cites: (a) whitespace-ignored
char n-grams, (b) the Korean-compound-noun metadata signal, and (c)
bucket precedence + answerable-case filtering in ``analyze_coverage``.

These are pure-stdlib (no index load, no FlagEmbedding) so they stay
default-CI safe. The full n=221 run is exercised by the measurement
itself (``COVERAGE.md`` byte-identical determinism check), not here.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.phase4_query_metadata_coverage import (  # noqa: E402
    _char_ngrams,
    _metadata_signal,
    analyze_coverage,
)


class CharNgramsTest(unittest.TestCase):
    def test_whitespace_ignored(self) -> None:
        # Whitespace is squashed before windowing, so a space-split
        # Korean phrase yields the same n-grams as its compound form.
        self.assertEqual(_char_ngrams("대학 재정", n=4), _char_ngrams("대학재정", n=4))

    def test_short_text_yields_empty_set(self) -> None:
        # Fewer than n squashed chars → no n-gram (a 3-char agency like
        # "조달청" cannot form a 4-gram, so it carries no signal).
        self.assertEqual(_char_ngrams("조달청", n=4), set())
        self.assertEqual(_char_ngrams("", n=4), set())

    def test_expected_windows(self) -> None:
        self.assertEqual(
            _char_ngrams("재정정보시스템", n=4),
            {"재정정보", "정정보시", "정보시스", "보시스템"},
        )


class MetadataSignalTest(unittest.TestCase):
    def test_korean_compound_noun_match(self) -> None:
        # The motivating case: token-split misses it, char-4gram catches
        # the substring overlap between query and project.
        self.assertTrue(
            _metadata_signal(
                query="대학재정정보시스템 고도화 예산은?",
                agency="한국교육부",
                project="2024년 대학재정정보시스템 고도화 용역",
            )
        )

    def test_no_overlap_is_false(self) -> None:
        self.assertFalse(
            _metadata_signal(
                query="보안 요구사항 정리해줘",
                agency="조달청",
                project="통합관리체계",
            )
        )

    def test_empty_query_is_false(self) -> None:
        self.assertFalse(_metadata_signal(query="", agency="한국대학교", project="재정"))


class AnalyzeCoverageTest(unittest.TestCase):
    def _index(self) -> dict:
        return {
            "documents": [
                {"doc_id": "d1", "agency": "한국대학교정보원", "project": "재정시스템 고도화"},
                {"doc_id": "d2", "agency": "조달청", "project": "통합관리체계"},
                {"doc_id": "d3", "agency": "국세청", "project": "과세체계"},
            ],
            "chunks": [
                {"doc_id": "d1", "chunk_id": "d1-c1", "text": "예산편성 내역 표"},
                {"doc_id": "d2", "chunk_id": "d2-c1", "text": "보안 통제 항목"},
                {"doc_id": "d3", "chunk_id": "d3-c1", "text": "일반 내용"},
            ],
        }

    def _cases(self) -> list[dict]:
        return [
            # metadata-identifiable: query overlaps agency AND has gold →
            # precedence puts it in metadata_identifiable, not content_query.
            {
                "query": "한국대학교정보원 예산 알려줘",
                "answerable": True,
                "expected_doc_ids": ["d1"],
                "expected_terms": ["예산편성"],
                "query_type": "single_doc",
            },
            # content-query: no agency/project overlap, gold exists.
            {
                "query": "보안 요구사항 정리해줘",
                "answerable": True,
                "expected_doc_ids": ["d2"],
                "expected_terms": ["보안"],
                "query_type": "single_doc",
            },
            # underspecified: no metadata overlap, no derivable gold
            # (expected_term matches no chunk text).
            {
                "query": "그것도 포함돼?",
                "answerable": True,
                "expected_doc_ids": ["d3"],
                "expected_terms": ["존재하지않는용어"],
                "query_type": "follow_up",
            },
            # filtered: not answerable.
            {
                "query": "무엇이든",
                "answerable": False,
                "expected_doc_ids": ["d1"],
                "expected_terms": ["예산편성"],
                "query_type": "single_doc",
            },
            # filtered: expected doc not in index metadata.
            {
                "query": "유령 문서",
                "answerable": True,
                "expected_doc_ids": ["d_missing"],
                "expected_terms": ["예산편성"],
                "query_type": "single_doc",
            },
        ]

    def test_bucket_precedence_and_filtering(self) -> None:
        stats = analyze_coverage(self._cases(), self._index())
        # Only the 3 answerable + resolvable cases count.
        self.assertEqual(stats["n_answerable"], 3)
        b = stats["buckets"]
        self.assertEqual(b["metadata_identifiable"]["n"], 1)
        self.assertEqual(b["content_query"]["n"], 1)
        self.assertEqual(b["underspecified"]["n"], 1)
        # content_query gold is present by definition; underspecified has none.
        self.assertEqual(b["content_query"]["gold_present"], 1)
        self.assertEqual(b["underspecified"]["gold_present"], 0)
        # Buckets exhaustively partition the answerable set (mutually
        # exclusive — the real invariant; per-bucket pct is rounded to
        # 1 decimal so the displayed pcts need not sum to exactly 100).
        self.assertEqual(sum(b[k]["n"] for k in b), stats["n_answerable"])

    def test_metadata_identifiable_wins_over_gold(self) -> None:
        # The metadata-identifiable case also HAS gold; precedence must
        # route it to metadata_identifiable (the ADR's core claim that
        # the bucket is a strict signal, not a residual).
        stats = analyze_coverage(self._cases(), self._index())
        self.assertEqual(stats["buckets"]["content_query"]["n"], 1)
        self.assertEqual(stats["buckets"]["metadata_identifiable"]["gold_present"], 1)


if __name__ == "__main__":
    unittest.main()
