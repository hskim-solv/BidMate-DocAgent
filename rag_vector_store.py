"""VectorStore abstraction for the RAG index (issue #232, Stage 1 of #176).

Sits behind ``index["_vector_store"]`` so that future PRs can plug in
Qdrant / pgvector adapters without touching the chunk-metadata payload
or the retrieval loop's call site. Stage 1 introduces the seam only —
``InMemoryVectorStore`` is a thin wrapper around the existing float32
matrix, so the on-disk format (``embeddings.npy`` sidecar from #207) is
unchanged and ranking is bit-identical.

The Protocol is deliberately minimal: ``get(idx)`` is what the current
retrieval loop in ``rag_core.py`` actually needs. A ``query(qvec, top_k)``
method (filter-pushdown for Qdrant) is reserved for Stage 2 — adding it
now would duplicate candidate-filter logic and break the no-behavior-
change invariant.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np


INDEX_FILENAME = "index.json"
EMBEDDINGS_FILENAME = "embeddings.npy"

ENV_INDEX_BACKEND = "BIDMATE_INDEX_BACKEND"
DEFAULT_INDEX_BACKEND = "memory"
SUPPORTED_BACKENDS = frozenset({"memory"})


@runtime_checkable
class VectorStore(Protocol):
    """Minimum surface used by the retrieval loop and the write/load paths.

    Implementations are constructed by ``load_vector_store`` (read path)
    or ``vector_store_from_matrix`` (build path), and are attached to the
    in-memory index payload under the ``_vector_store`` key.
    """

    dimension: int

    def __len__(self) -> int: ...

    def get(self, idx: int) -> np.ndarray: ...

    def persist(self, output_dir: Path) -> None: ...


@dataclass
class InMemoryVectorStore:
    """numpy-backed VectorStore — the Stage 1 default.

    Wraps a ``(N, D)`` float32 L2-normalized matrix. ``get`` returns a
    view into the underlying array (not a copy), matching the prior
    ``vectors_matrix[i]`` behavior in ``rag_core.retrieve``.
    """

    vectors: np.ndarray

    @property
    def dimension(self) -> int:
        return int(self.vectors.shape[1])

    def __len__(self) -> int:
        return int(self.vectors.shape[0])

    def get(self, idx: int) -> np.ndarray:
        return self.vectors[idx]

    def persist(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        np.save(
            output_dir / EMBEDDINGS_FILENAME,
            np.asarray(self.vectors, dtype=np.float32),
        )


def vector_store_from_matrix(vectors: np.ndarray) -> VectorStore:
    """Wrap an in-memory float32 matrix as the default VectorStore."""
    return InMemoryVectorStore(vectors=np.asarray(vectors, dtype=np.float32))


def _resolve_backend() -> str:
    return os.environ.get(ENV_INDEX_BACKEND, DEFAULT_INDEX_BACKEND).strip().lower()


def load_vector_store(
    index_dir: Path,
    schema_version: int,
    chunks: list[dict] | None = None,
) -> VectorStore | None:
    """Materialize a VectorStore from the on-disk index artifacts.

    For ``schema_version >= 2`` (current), reads ``embeddings.npy``. For
    legacy schema 1, materializes from inline per-chunk ``embedding``
    lists if ``chunks`` is provided; returns ``None`` if no inline
    vectors exist (matches the prior ``payload["_vectors"] = None``
    fallback in ``rag_core.load_index``).

    Selects the concrete implementation by ``$BIDMATE_INDEX_BACKEND``
    (Stage 1 only accepts ``memory``).
    """
    backend = _resolve_backend()
    if backend not in SUPPORTED_BACKENDS:
        raise NotImplementedError(
            f"Index backend {backend!r} is not yet implemented; "
            f"Stage 1 only ships the in-memory backend. See issue #176 "
            f"(Stage 2 = Qdrant, Stage 3 = pgvector)."
        )

    if schema_version >= 2:
        embeddings_path = index_dir / EMBEDDINGS_FILENAME
        if not embeddings_path.exists():
            raise ValueError(
                f"Index schema_version={schema_version} requires sidecar "
                f"{embeddings_path}. Rebuild via scripts/build_index.py."
            )
        matrix = np.load(embeddings_path)
        return InMemoryVectorStore(vectors=np.asarray(matrix, dtype=np.float32))

    if chunks is None:
        return None
    inline = [c.get("embedding") for c in chunks]
    if not inline or any(v is None for v in inline):
        return None
    return InMemoryVectorStore(vectors=np.asarray(inline, dtype=np.float32))
