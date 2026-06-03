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

        # Attest a public surface so the ADR 0061 ③ guard passes and the
        # missing-key path (not the data-boundary block) is exercised (#1195).
        with mock.patch.dict(
            os.environ, {"BIDMATE_DATA_SURFACE": "public_fixture"}, clear=False
        ):
            os.environ.pop("BIDMATE_OPENAI_API_KEY", None)
            os.environ.pop("OPENAI_API_KEY", None)
            with mock.patch.dict(sys.modules, {"openai": mock.MagicMock()}):
                with self.assertRaises(RuntimeError) as ctx:
                    rag_core.embed_texts(["x"], backend="openai")
                self.assertIn("BIDMATE_OPENAI_API_KEY", str(ctx.exception))

    def test_missing_sdk_raises_with_install_hint(self) -> None:
        import rag_core

        # Public-surface attestation passes the ADR 0061 ③ guard so the
        # missing-SDK install hint (not the boundary block) is asserted (#1195).
        with mock.patch.dict(
            os.environ, {"BIDMATE_DATA_SURFACE": "public_fixture"}, clear=False
        ), mock.patch.dict(sys.modules, {"openai": None}):
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
            # BIDMATE_DATA_SURFACE attests public so the ADR 0061 ③ guard
            # passes and the fake client (not the boundary block) runs (#1195).
            with mock.patch.dict(
                os.environ,
                {
                    "BIDMATE_OPENAI_API_KEY": "test-key",
                    "BIDMATE_DATA_SURFACE": "public_fixture",
                },
            ):
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
            # Public-surface attestation passes the ADR 0061 ③ guard so this
            # genuinely routes through the openai backend, not hashing (#1195).
            with mock.patch.dict(
                os.environ,
                {
                    "BIDMATE_OPENAI_API_KEY": "test-key",
                    "BIDMATE_DATA_SURFACE": "public_fixture",
                },
            ):
                vec = rag_core.embed_query_for_index(
                    "안녕",
                    {"backend": "openai", "model": "text-embedding-3-large", "dimension": 4},
                )
        self.assertEqual(vec.shape, (4,))

    def test_openai_falls_back_to_hashing_when_sdk_missing(self) -> None:
        import rag_core

        # Public-surface attestation passes the ADR 0061 ③ guard so the
        # SDK-missing branch (not the boundary block) drives the graceful
        # hashing fallback this test asserts (#1195).
        with mock.patch.dict(
            os.environ, {"BIDMATE_DATA_SURFACE": "public_fixture"}, clear=False
        ), mock.patch.dict(sys.modules, {"openai": None}):
            vec = rag_core.embed_query_for_index(
                "안녕",
                {"backend": "openai", "model": "text-embedding-3-large", "dimension": 8},
            )
        # Should silently fall back, matching the sentence-transformers branch's
        # try/except path. Hashing returns dim=8 vectors.
        self.assertEqual(vec.shape, (8,))


class _CapturingSentenceTransformer:
    """Fake SentenceTransformer that records constructor + encode kwargs so the
    opt-in ``BIDMATE_ST_FP16`` / ``BIDMATE_ST_PROGRESS`` knobs can be asserted
    without a real model download (issue #1359 real100 ablation memory/ETA)."""

    last_init_kwargs: dict = {}
    last_encode_kwargs: dict = {}

    def __init__(self, model_name: str, **kwargs: object) -> None:
        type(self).last_init_kwargs = dict(kwargs)

    def encode(self, texts: list[str], **kwargs: object):
        import numpy as np

        type(self).last_encode_kwargs = dict(kwargs)
        return np.ones((len(texts), 4), dtype=np.float32)


class StEncodeKnobTest(unittest.TestCase):
    """``BIDMATE_ST_FP16`` / ``BIDMATE_ST_PROGRESS`` are opt-in: default unset
    keeps fp32 + silent (byte-identical to pre-#1359); set propagates to the
    SentenceTransformer constructor / encode call respectively."""

    def _run(self, env: dict) -> tuple[dict, dict]:
        import importlib

        _CapturingSentenceTransformer.last_init_kwargs = {}
        _CapturingSentenceTransformer.last_encode_kwargs = {}
        fake_st = mock.MagicMock()
        fake_st.SentenceTransformer = _CapturingSentenceTransformer
        rag_embedding = importlib.import_module("rag_embedding")
        # Fresh cache so the constructor (and its kwargs) actually runs.
        rag_embedding.MODEL_CACHE.clear()
        with mock.patch.dict(sys.modules, {"sentence_transformers": fake_st}), \
                mock.patch.dict(os.environ, env, clear=False):
            for k in ("BIDMATE_ST_FP16", "BIDMATE_ST_PROGRESS"):
                if k not in env:
                    os.environ.pop(k, None)
            rag_embedding.embed_texts(["x"], model_name="dummy/model", backend="sentence-transformers")
        return (
            _CapturingSentenceTransformer.last_init_kwargs,
            _CapturingSentenceTransformer.last_encode_kwargs,
        )

    def test_default_is_fp32_and_silent(self) -> None:
        init_kwargs, encode_kwargs = self._run({})
        self.assertNotIn("model_kwargs", init_kwargs)
        self.assertFalse(encode_kwargs["show_progress_bar"])

    def test_fp16_sets_torch_dtype(self) -> None:
        import torch

        init_kwargs, _ = self._run({"BIDMATE_ST_FP16": "1"})
        self.assertEqual(init_kwargs["model_kwargs"], {"torch_dtype": getattr(torch, "float16")})

    def test_progress_enables_bar(self) -> None:
        _, encode_kwargs = self._run({"BIDMATE_ST_PROGRESS": "1"})
        self.assertTrue(encode_kwargs["show_progress_bar"])


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


class ExpandFeaturesTest(unittest.TestCase):
    """Direct unit coverage for rag_embedding.expand_features (issue #2105).

    expand_features is only exercised transitively via hashing_embeddings;
    these lock the unigram + bigram expansion contract and its edge cases.
    """

    def test_empty_returns_empty(self) -> None:
        import rag_embedding

        self.assertEqual(rag_embedding.expand_features([]), [])

    def test_single_token_has_no_bigram(self) -> None:
        import rag_embedding

        self.assertEqual(rag_embedding.expand_features(["a"]), ["a"])

    def test_pair_appends_one_bigram(self) -> None:
        import rag_embedding

        self.assertEqual(
            rag_embedding.expand_features(["a", "b"]), ["a", "b", "a_b"]
        )

    def test_triple_appends_adjacent_bigrams(self) -> None:
        import rag_embedding

        self.assertEqual(
            rag_embedding.expand_features(["a", "b", "c"]),
            ["a", "b", "c", "a_b", "b_c"],
        )

    def test_unigrams_precede_bigrams(self) -> None:
        import rag_embedding

        result = rag_embedding.expand_features(["x", "y", "z"])
        self.assertEqual(result[:3], ["x", "y", "z"])
        self.assertTrue(all("_" in bigram for bigram in result[3:]))

    def test_duplicate_adjacent_tokens(self) -> None:
        import rag_embedding

        self.assertEqual(
            rag_embedding.expand_features(["a", "a"]), ["a", "a", "a_a"]
        )

    def test_does_not_mutate_input(self) -> None:
        import rag_embedding

        tokens = ["a", "b"]
        rag_embedding.expand_features(tokens)
        self.assertEqual(tokens, ["a", "b"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
