"""Tests for clear_model_caches() — issue #841.

RAG senior-review critique #7.2. ``MODEL_CACHE`` and (when loaded)
``visual_ingestion._DONUT_MODEL_CACHE`` are process-level dicts that
accumulate model instances across calls. This module pins the
explicit-reset contract that ``tests/conftest.py``'s autouse
session-scope fixture relies on.

ADR 0045 / issue #843 — ``clear_model_caches`` lives in
``rag_embedding`` and is re-exported via ``rag_core``. These tests
intentionally import from ``rag_core`` to lock the re-export surface
that existing call sites depend on.
"""
from __future__ import annotations

import sys

import pytest

from rag_core import MODEL_CACHE, clear_model_caches


class TestClearModelCaches:
    """Behavioral contract for the explicit-reset hook."""

    def setup_method(self) -> None:
        # Each test starts with a known-clean state — the autouse
        # session-end fixture runs at session teardown, not per-test.
        MODEL_CACHE.clear()

    def test_clears_model_cache(self) -> None:
        """``MODEL_CACHE.clear()`` is invoked unconditionally."""
        MODEL_CACHE[("dummy-model", False, None)] = object()
        assert len(MODEL_CACHE) == 1
        clear_model_caches()
        assert len(MODEL_CACHE) == 0

    def test_idempotent_on_empty_cache(self) -> None:
        """Calling on an already-empty cache is a no-op (no exception)."""
        assert len(MODEL_CACHE) == 0
        clear_model_caches()  # should not raise
        clear_model_caches()  # twice in a row should also not raise
        assert len(MODEL_CACHE) == 0

    def test_does_not_force_visual_ingestion_import(self) -> None:
        """Calling the helper does not import ``visual_ingestion``.

        The ``sys.modules.get(...)`` lookup is load-bearing: the
        hashing-only test path must not pay the optional-dep import
        cost just to no-op the donut cache clear.
        """
        if "visual_ingestion" in sys.modules:
            pytest.skip(
                "visual_ingestion was already imported by an earlier test "
                "in this pytest session; the negative assertion only holds "
                "from a cold-import baseline."
            )
        clear_model_caches()
        assert "visual_ingestion" not in sys.modules, (
            "clear_model_caches() must not force visual_ingestion import — "
            "use sys.modules.get() lookup, not direct `import visual_ingestion`."
        )

    def test_clears_donut_cache_when_module_loaded(self) -> None:
        """Once ``visual_ingestion`` is loaded, its donut cache is also cleared."""
        # Synthesize a minimal visual_ingestion-shaped module without
        # paying the real import cost. This proves the helper consults
        # sys.modules and clears the dict it finds, regardless of how
        # the module got there.
        import types

        stub = types.ModuleType("visual_ingestion")
        stub._DONUT_MODEL_CACHE = {"fake-donut-key": object()}  # type: ignore[attr-defined]
        sys.modules["visual_ingestion"] = stub
        try:
            assert stub._DONUT_MODEL_CACHE  # type: ignore[attr-defined]
            clear_model_caches()
            assert stub._DONUT_MODEL_CACHE == {}, (  # type: ignore[attr-defined]
                "clear_model_caches() must clear visual_ingestion._DONUT_MODEL_CACHE "
                "when the module is loaded."
            )
        finally:
            sys.modules.pop("visual_ingestion", None)
