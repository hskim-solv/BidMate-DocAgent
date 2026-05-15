"""Regression: clear_model_caches() drops MODEL_CACHE entries (issue #841).

RAG senior-review critique #7.2. ``rag_embedding.MODEL_CACHE`` is a
process-level dict that accumulates SentenceTransformer instances
across calls. The new ``clear_model_caches()`` helper exposes an
explicit reset hook for the autouse session-teardown fixture in
``tests/conftest.py`` and for non-pytest callers (notebooks, REPL).

This test pins the contract:

1. ``clear_model_caches()`` empties ``rag_embedding.MODEL_CACHE``.
2. ``clear_model_caches()`` is safe to call when the cache is
   already empty (idempotent).
3. ``clear_model_caches()`` does not force the import of
   ``visual_ingestion`` if it has not already been loaded.
4. ``clear_model_caches()`` clears
   ``visual_ingestion._DONUT_MODEL_CACHE`` when that module IS loaded.
5. The helper is reachable from ``rag_core`` for backward-compat
   callers (PR #847 moved MODEL_CACHE to rag_embedding; the
   ``from rag_core import ...`` path must still work).
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import sentinel

import rag_core
import rag_embedding
from rag_embedding import MODEL_CACHE, clear_model_caches


class TestClearModelCaches(unittest.TestCase):
    def setUp(self) -> None:
        # Snapshot whatever entries are already there (the autouse
        # session fixture clears at session end, not before each
        # test). We restore at tearDown to keep the test isolated.
        self._snapshot = dict(MODEL_CACHE)
        MODEL_CACHE.clear()

    def tearDown(self) -> None:
        MODEL_CACHE.clear()
        MODEL_CACHE.update(self._snapshot)

    def test_clears_model_cache(self) -> None:
        # Plant a fake entry that mimics the real cache shape
        # (``(model_name, local_only, adapter_path)`` → SentenceTransformer).
        MODEL_CACHE[("fake-model", True, None)] = sentinel.fake_model_instance
        self.assertEqual(len(MODEL_CACHE), 1)
        clear_model_caches()
        self.assertEqual(len(MODEL_CACHE), 0)

    def test_idempotent_on_empty_cache(self) -> None:
        # Already empty (setUp); calling again must not raise.
        self.assertEqual(len(MODEL_CACHE), 0)
        clear_model_caches()
        self.assertEqual(len(MODEL_CACHE), 0)

    def test_does_not_force_visual_ingestion_import(self) -> None:
        # If visual_ingestion has not been imported elsewhere in the
        # test session, the helper must not import it (cost / side
        # effect avoidance). We can only assert the negative when the
        # module is genuinely absent — skip if it was already loaded
        # by an earlier test.
        if "visual_ingestion" in sys.modules:
            self.skipTest(
                "visual_ingestion already imported by another test; "
                "this assertion only meaningful in cold-import order"
            )
        clear_model_caches()
        self.assertNotIn("visual_ingestion", sys.modules)

    def test_clears_donut_cache_when_module_loaded(self) -> None:
        # When visual_ingestion IS loaded, the helper should clear
        # its cache too. Import explicitly here to set up the case.
        import visual_ingestion

        cache_attr = getattr(visual_ingestion, "_DONUT_MODEL_CACHE", None)
        if not isinstance(cache_attr, dict):
            self.skipTest(
                "visual_ingestion._DONUT_MODEL_CACHE not a dict — "
                "implementation drift; helper still safe (no-op)"
            )
        # Plant a fake entry; clear; assert empty.
        cache_attr["fake-donut-model"] = (sentinel.proc, sentinel.model)
        self.assertEqual(len(cache_attr), 1)
        clear_model_caches()
        self.assertEqual(len(cache_attr), 0)

    def test_reachable_from_rag_core_re_export(self) -> None:
        # PR #847 moved MODEL_CACHE + embed_texts + friends to
        # rag_embedding. ``rag_core`` re-exports them so existing
        # ``from rag_core import ...`` consumers (this PR's
        # conftest.py fixture, future test code) keep working.
        self.assertIs(rag_core.clear_model_caches, clear_model_caches)
        self.assertIs(rag_core.MODEL_CACHE, MODEL_CACHE)
        self.assertIs(rag_core.MODEL_CACHE, rag_embedding.MODEL_CACHE)


if __name__ == "__main__":
    unittest.main()
