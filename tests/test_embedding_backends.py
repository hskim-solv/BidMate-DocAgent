"""Embedding backend tests (issue #161).

Locks the contract for ``rag_core.embed_texts`` and ``embed_query_for_index``
across the three production code paths plus the new opt-in OpenAI backend:

* whitelist guard rejects unknown backends
* OpenAI backend requires the SDK and an API key (clean error path)
* OpenAI backend lazy-imports — ``rag_core`` import must not pull ``openai``
* OpenAI vectors are L2-normalized (cosine-via-dot-product invariant
  matching sentence-transformers' ``normalize_embeddings=True``)
* run_embedding_ablation slug is filesystem-safe for OpenAI model IDs

The tests stub the network: no live OpenAI calls. CI runs with
``EMBEDDING_BACKEND=hashing`` so this module's tests are CI-safe.
"""

from __future__ import annotations

import os
import sys
import unittest
from dataclasses import dataclass
from unittest import mock


class EmbedTextsBackendWhitelistTest(unittest.TestCase):
    def test_unknown_backend_raises(self) -> None:
        import rag_core

        with self.assertRaises(ValueError) as ctx:
            rag_core.embed_texts(["x"], backend="bogus")
        msg = str(ctx.exception)
        self.assertIn("auto", msg)
        self.assertIn("openai", msg)


class OpenAIBackendErrorPathTest(unittest.TestCase):
    def test_missing_api_key_raises(self) -> None:
        import rag_core

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BIDMATE_OPENAI_API_KEY", None)
            os.environ.pop("OPENAI_API_KEY", None)
            with mock.patch.dict(sys.modules, {"openai": mock.MagicMock()}):
                with self.assertRaises(RuntimeError) as ctx:
                    rag_core.embed_texts(["x"], backend="openai")
                self.assertIn("BIDMATE_OPENAI_API_KEY", str(ctx.exception))

    def test_missing_sdk_raises_with_install_hint(self) -> None:
        import rag_core

        with mock.patch.dict(sys.modules, {"openai": None}):
            with self.assertRaises(RuntimeError) as ctx:
                rag_core.embed_texts(["x"], backend="openai")
            self.assertIn("pip install openai", str(ctx.exception))


class OpenAILazyImportTest(unittest.TestCase):
    def test_rag_core_does_not_import_openai_at_module_load(self) -> None:
        # rag_core may already be cached in sys.modules from earlier tests —
        # the contract is that loading rag_core itself does not require openai.
        # Verify by checking the module's source-level imports rather than a
        # fresh reload (a reload would also pull rag_synthesis et al.).
        import rag_core

        source = open(rag_core.__file__, "r", encoding="utf-8").read()
        # Anything at module scope that says ``import openai`` would defeat
        # the lazy-import contract. The only ``openai`` reference must live
        # inside ``_embed_with_openai``.
        top_level_lines = [
            line for line in source.splitlines()
            if line.startswith("import openai") or line.startswith("from openai")
        ]
        self.assertEqual(top_level_lines, [], "openai must be lazy-imported only inside _embed_with_openai")


@dataclass
class _FakeEmbeddingItem:
    embedding: list[float]


@dataclass
class _FakeEmbeddingResponse:
    data: list[_FakeEmbeddingItem]


class _FakeOpenAIClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.embeddings = self

    def create(self, *, model: str, input: list[str]) -> _FakeEmbeddingResponse:
        # Deterministic 4-dim vectors so the L2-normalization invariant is testable.
        # Each text maps to (i+1, 0, 0, 0); after L2-normalize each becomes (1, 0, 0, 0).
        return _FakeEmbeddingResponse(
            data=[_FakeEmbeddingItem(embedding=[float(i + 1), 0.0, 0.0, 0.0]) for i, _ in enumerate(input)]
        )


class OpenAIVectorNormalizationTest(unittest.TestCase):
    def test_returned_vectors_are_l2_normalized(self) -> None:
        import numpy as np
        import rag_core

        fake_openai = mock.MagicMock()
        fake_openai.OpenAI = _FakeOpenAIClient

        with mock.patch.dict(sys.modules, {"openai": fake_openai}):
            with mock.patch.dict(os.environ, {"BIDMATE_OPENAI_API_KEY": "test-key"}):
                result = rag_core.embed_texts(
                    ["hello", "world", "again"],
                    model_name="text-embedding-3-large",
                    backend="openai",
                )

        self.assertEqual(result.backend, "openai")
        self.assertEqual(result.model, "text-embedding-3-large")
        self.assertEqual(result.vectors.shape, (3, 4))
        norms = np.linalg.norm(result.vectors, axis=1)
        for n in norms:
            self.assertAlmostEqual(float(n), 1.0, places=5)


class EmbedQueryForIndexOpenAITest(unittest.TestCase):
    def test_openai_backend_routes_through_embed_texts(self) -> None:
        import rag_core

        fake_openai = mock.MagicMock()
        fake_openai.OpenAI = _FakeOpenAIClient

        with mock.patch.dict(sys.modules, {"openai": fake_openai}):
            with mock.patch.dict(os.environ, {"BIDMATE_OPENAI_API_KEY": "test-key"}):
                vec = rag_core.embed_query_for_index(
                    "안녕",
                    {"backend": "openai", "model": "text-embedding-3-large", "dimension": 4},
                )
        self.assertEqual(vec.shape, (4,))

    def test_openai_falls_back_to_hashing_when_sdk_missing(self) -> None:
        import rag_core

        with mock.patch.dict(sys.modules, {"openai": None}):
            vec = rag_core.embed_query_for_index(
                "안녕",
                {"backend": "openai", "model": "text-embedding-3-large", "dimension": 8},
            )
        # Should silently fall back, matching the sentence-transformers branch's
        # try/except path. Hashing returns dim=8 vectors.
        self.assertEqual(vec.shape, (8,))


class RunEmbeddingAblationSlugTest(unittest.TestCase):
    def test_openai_model_slug_is_filesystem_safe(self) -> None:
        sys.path.insert(0, str(_repo_scripts_dir()))
        try:
            from run_embedding_ablation import _slug, _derive_backend
        finally:
            sys.path.pop(0)

        slug = _slug("text-embedding-3-large")
        self.assertNotIn("/", slug)
        self.assertNotIn(".", slug)
        self.assertEqual(_derive_backend("text-embedding-3-large"), "openai")
        self.assertEqual(
            _derive_backend("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
            "sentence-transformers",
        )
        self.assertEqual(_derive_backend("BAAI/bge-m3"), "sentence-transformers")


def _repo_scripts_dir() -> "object":
    from pathlib import Path

    return Path(__file__).resolve().parent.parent / "scripts"


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
