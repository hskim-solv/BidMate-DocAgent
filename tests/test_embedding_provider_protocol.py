"""Regression guards for the EmbeddingProvider Protocol interface."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_embedding import (  # noqa: E402
    EmbeddingProvider,
    EmbeddingResult,
    default_embedding_provider,
    ensure_embedding_dimension,
)


def test_default_embedding_provider_is_protocol_instance() -> None:
    provider = default_embedding_provider(backend="hashing", expected_dimension=384)
    assert isinstance(provider, EmbeddingProvider)

    docs = provider.embed_documents(["alpha", "beta"])
    query = provider.embed_query("alpha")

    assert docs.backend == "hashing"
    assert docs.vectors.shape == (2, 384)
    assert query.vectors.shape == (1, 384)


def test_embedding_dimension_mismatch_raises_explicit_error() -> None:
    result = EmbeddingResult(
        vectors=np.zeros((2, 3), dtype=np.float32),
        backend="fake",
        model="fake-model",
    )

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        ensure_embedding_dimension(result, 4)


def test_embedding_dimension_validation_rejects_non_matrix_vectors() -> None:
    result = EmbeddingResult(
        vectors=np.zeros(4, dtype=np.float32),
        backend="fake",
        model="fake-model",
    )

    with pytest.raises(ValueError, match="expected 4, got None"):
        ensure_embedding_dimension(result, 4)


def test_embedding_dimension_match_returns_original_result() -> None:
    result = EmbeddingResult(
        vectors=np.zeros((1, 4), dtype=np.float32),
        backend="fake",
        model="fake-model",
    )

    assert ensure_embedding_dimension(result, 4) is result


def test_embedding_dimension_none_skips_validation() -> None:
    result = EmbeddingResult(
        vectors=np.zeros(4, dtype=np.float32),
        backend="fake",
        model="fake-model",
    )

    assert ensure_embedding_dimension(result, None) is result
