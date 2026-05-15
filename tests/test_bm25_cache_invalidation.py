"""Regression: BM25 cache invalidates on schema_version / chunk count change (issue #833).

RAG senior-review critique #7.1. The cache used to be keyed by
``(stopword_profile, tokenizer)`` only. A caller that reused the
same ``index`` dict after mutating ``index["chunks"]`` (test fixture
mutation, runtime reload, schema bump that adds/removes chunks) got
the stale BM25 + stale chunk_ids — silent corruption with no
exception or warning.

This test pins the new contract:

1. Same ``(profile, tokenizer)`` + same chunks → cache hit (same
   BM25 object returned).
2. Same ``(profile, tokenizer)`` + different ``schema_version`` →
   cache miss (different BM25 object returned).
3. Same ``(profile, tokenizer)`` + chunks list mutated (append) →
   cache miss + chunk_ids in returned tuple reflect the new chunks.
4. Different ``(profile, tokenizer)`` → cache miss (existing
   behavior preserved).
"""

from __future__ import annotations

import unittest

import pytest

# rank_bm25 is an optional dependency; skip the entire module if it
# is missing rather than failing to import (matches scripts/test.sh
# minimal-env policy).
pytest.importorskip("rank_bm25")

from rag_retrieval import get_or_build_bm25  # noqa: E402


def _chunk(chunk_id: str, text: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "doc_id": "d1",
        "title": "t",
        "text": text,
        # ``_chunk_tokens_for_bm25`` reads either ``tokens`` (cached)
        # or falls back to re-tokenizing ``text``; both paths work for
        # this test as long as one is present.
        "tokens": text.split(),
    }


class TestBM25CacheInvalidation(unittest.TestCase):
    def setUp(self) -> None:
        # Two-chunk fixture; ``schema_version`` set explicitly so the
        # cache key is deterministic.
        self.chunks = [
            _chunk("c1", "alpha bravo"),
            _chunk("c2", "charlie delta"),
        ]
        self.index = {"chunks": self.chunks, "schema_version": 2}

    def test_cache_hit_returns_same_object(self) -> None:
        first = get_or_build_bm25(self.index, "shared", "regex")
        second = get_or_build_bm25(self.index, "shared", "regex")
        # Cache hit → same tuple returned (same BM25 object identity).
        self.assertIs(first[0], second[0])
        self.assertIs(first[1], second[1])

    def test_schema_version_change_invalidates_cache(self) -> None:
        first = get_or_build_bm25(self.index, "shared", "regex")
        # Schema bump (e.g. v2 → v3 added a per-chunk field BM25
        # tokens key off) should invalidate the cache automatically.
        self.index["schema_version"] = 3
        second = get_or_build_bm25(self.index, "shared", "regex")
        self.assertIsNot(first[0], second[0])

    def test_chunk_count_change_invalidates_cache(self) -> None:
        first = get_or_build_bm25(self.index, "shared", "regex")
        # In-place mutation of the chunks list (the failure mode this
        # test exists to catch).
        self.chunks.append(_chunk("c3", "echo foxtrot"))
        second = get_or_build_bm25(self.index, "shared", "regex")
        self.assertIsNot(first[0], second[0])
        # The new build must reflect the new chunk_ids — this is the
        # silent corruption symptom we are preventing.
        self.assertEqual(second[1], ["c1", "c2", "c3"])

    def test_different_profile_or_tokenizer_invalidates_cache(self) -> None:
        # Existing behavior: orthogonal axes still produce different
        # cache entries.
        shared_regex = get_or_build_bm25(self.index, "shared", "regex")
        bm25_extra_regex = get_or_build_bm25(self.index, "bm25_extra", "regex")
        self.assertIsNot(shared_regex[0], bm25_extra_regex[0])


if __name__ == "__main__":
    unittest.main()
