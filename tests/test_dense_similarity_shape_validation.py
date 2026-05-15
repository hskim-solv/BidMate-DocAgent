"""Regression: dense_similarity raises on shape mismatch (issue #784).

RAG senior-review critique #4. The function used to return ``0.0`` for
a vector-shape mismatch between query and chunk embeddings, which
silently produced a zero-similarity score across the index when the
sidecar was rebuilt with a different model dimension or fixture math
disagreed with the embedding backend. The bug surfaced as flat eval
discriminating power with no observable signal.

This test pins the new contract:

1. ``chunk_vector is None`` continues to return ``0.0`` (legitimate
   "no embedding for this chunk" case for metadata-only fixture rows).
2. Shape mismatch raises ``ValueError`` with both shapes in the
   message (so the failing call site is grep-able from the traceback).
3. Matching-shape vectors still return the existing ``(cosine + 1) / 2``
   affine clamp — i.e. the happy path is unchanged.
"""

from __future__ import annotations

import unittest

import numpy as np

from rag_retrieval import dense_similarity


class TestDenseSimilarityShapeValidation(unittest.TestCase):
    def test_none_chunk_vector_returns_zero(self) -> None:
        # The "no embedding" contract for metadata-only chunks must
        # be preserved — None is not a corruption signal.
        score = dense_similarity(np.zeros(8, dtype=np.float32), None)
        self.assertEqual(score, 0.0)

    def test_matching_shape_returns_affine_clamped_cosine(self) -> None:
        # Sanity: parallel unit vectors → cosine 1.0 → clamp = 1.0.
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        self.assertAlmostEqual(dense_similarity(v, v), 1.0, places=6)
        # Anti-parallel → cosine -1.0 → clamp = 0.0.
        anti = -v
        self.assertAlmostEqual(dense_similarity(v, anti), 0.0, places=6)

    def test_shape_mismatch_raises_with_both_shapes(self) -> None:
        # The bug we are fixing: previously this returned 0.0
        # silently, corrupting retrieval ranking. Now it raises so
        # the index-vs-query dimension mismatch surfaces at the
        # failing call site.
        query = np.zeros(8, dtype=np.float32)
        chunk = np.zeros(16, dtype=np.float32)
        with self.assertRaises(ValueError) as cm:
            dense_similarity(query, chunk)
        message = str(cm.exception)
        # Both shapes should be mentioned so the developer can tell
        # immediately which dimension is wrong.
        self.assertIn("(8,)", message)
        self.assertIn("(16,)", message)

    def test_shape_mismatch_chunk_as_list_also_raises(self) -> None:
        # ``chunk_vector`` is typed ``Any`` and frequently comes in
        # as a Python list from JSON-loaded fixtures. The shape
        # check must still apply after np.asarray().
        query = np.zeros(4, dtype=np.float32)
        chunk_as_list = [0.0, 0.0, 0.0]  # length 3, mismatch
        with self.assertRaises(ValueError):
            dense_similarity(query, chunk_as_list)


if __name__ == "__main__":
    unittest.main()
