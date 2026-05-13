"""VectorStore abstraction for the RAG index (issue #176).

Sits behind ``index["_vector_store"]`` so that retrieval call sites in
``rag_core.py`` work against any registered backend without touching
chunk-metadata storage. The on-disk format (``embeddings.npy`` sidecar
from #207) is invariant across backends, so users can switch
``$BIDMATE_INDEX_BACKEND`` without rebuilding the index.

Stages of #176:

* **Stage 1** (#234, merged) — Protocol + ``InMemoryVectorStore``.
* **Stage 2a** (#288, merged) — Qdrant in-memory collection adapter.
  ``get(idx)`` is bit-identical to in-memory; the Qdrant collection
  holds the same points in parallel.
* **Stage 2b** (this PR) — Protocol-level ``query(qvec, top_k)``
  method exposing top-k cosine retrieval. ``InMemoryVectorStore``
  ships an exact brute-force implementation; ``QdrantVectorStore``
  delegates to ``client.search`` so the Qdrant collection actually
  earns its keep. ``rag_core.retrieve`` is not yet wired to
  ``query`` — that integration is Stage 2c so reviewers can read
  the API change without a load-bearing retrieve diff.
* **Stage 2c** (deferred) — wire ``rag_core.retrieve`` to
  ``store.query`` so both backends drive ranking through the same
  surface. Filter-pushdown (Qdrant payload filters) extends ``query``.
* **Stage 3** (deferred) — pgvector backend for SaaS-Postgres scale.

Convention: follows the four-property Protocol-based pluggability pattern
(ADR 0020). New backends implement ``VectorStore`` and register via
``default_vector_store()`` — ``rag_core.py`` is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np


INDEX_FILENAME = "index.json"
EMBEDDINGS_FILENAME = "embeddings.npy"

ENV_INDEX_BACKEND = "BIDMATE_INDEX_BACKEND"
DEFAULT_INDEX_BACKEND = "memory"
# ``pgvector`` is reserved for Stage 3 — selecting it today raises
# NotImplementedError.
SUPPORTED_BACKENDS = frozenset({"memory", "qdrant"})

# Qdrant in-memory collection name. Kept stable so introspection and
# future migrations can match against a single literal.
QDRANT_COLLECTION_NAME = "bidmate_index"


@runtime_checkable
class VectorStore(Protocol):
    """Minimum surface used by the retrieval loop and the write/load paths.

    Implementations are constructed by ``load_vector_store`` (read path)
    or ``vector_store_from_matrix`` (build path), and are attached to the
    in-memory index payload under the ``_vector_store`` key.

    ``query`` is the Stage 2b extension (#176): both backends MUST
    accept an L2-normalized float32 query vector and return the
    top-``k`` ``(idx, score)`` pairs sorted by score descending. Score
    is cosine similarity in ``[-1, 1]``.
    """

    dimension: int

    def __len__(self) -> int: ...

    def get(self, idx: int) -> np.ndarray: ...

    def query(
        self, qvec: np.ndarray, top_k: int
    ) -> list[tuple[int, float]]: ...

    def persist(self, output_dir: Path) -> None: ...


@dataclass
class InMemoryVectorStore:
    """numpy-backed VectorStore — the Stage 1 default.

    Wraps a ``(N, D)`` float32 L2-normalized matrix. ``get`` returns a
    view into the underlying array (not a copy), matching the prior
    ``vectors_matrix[i]`` behavior in ``rag_core.retrieve``. ``query``
    is a brute-force exact cosine top-k — the matrix is already
    L2-normalized so dot product equals cosine.
    """

    vectors: np.ndarray

    @property
    def dimension(self) -> int:
        return int(self.vectors.shape[1])

    def __len__(self) -> int:
        return int(self.vectors.shape[0])

    def get(self, idx: int) -> np.ndarray:
        return self.vectors[idx]

    def query(
        self, qvec: np.ndarray, top_k: int
    ) -> list[tuple[int, float]]:
        if len(self) == 0 or top_k <= 0:
            return []
        qvec_f32 = np.asarray(qvec, dtype=np.float32)
        if qvec_f32.shape[-1] != self.dimension:
            raise ValueError(
                f"Query vector dim {qvec_f32.shape[-1]} does not match "
                f"index dim {self.dimension}."
            )
        scores = self.vectors @ qvec_f32
        k = min(top_k, len(scores))
        if k == len(scores):
            order = np.argsort(-scores, kind="stable")
        else:
            # argpartition pulls the k highest-scoring rows, then we
            # sort within that slice. Stable sort ensures deterministic
            # tie-breaks by row index — matching the brute-force loop
            # in ``rag_core.retrieve`` today.
            partition = np.argpartition(-scores, k - 1)[:k]
            order = partition[np.argsort(-scores[partition], kind="stable")]
        return [(int(i), float(scores[i])) for i in order]

    def persist(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        np.save(
            output_dir / EMBEDDINGS_FILENAME,
            np.asarray(self.vectors, dtype=np.float32),
        )


@dataclass
class QdrantVectorStore:
    """Qdrant in-memory collection adapter (#176 Stage 2a + 2b).

    Wraps the same ``(N, D)`` float32 L2-normalized matrix as
    ``InMemoryVectorStore`` and mirrors it into a Qdrant collection
    opened in ``location=":memory:"`` mode. ``get(idx)`` returns the
    bit-identical row from the matrix; ``query`` delegates to
    ``client.search`` so the Qdrant collection actually drives the
    cosine top-k ranking.

    Native Qdrant collection persistence (``location=<path>``) is
    reserved for Stage 3 — Stage 2 writes the same
    ``embeddings.npy`` sidecar so users can switch backends without
    rebuilding the index.
    """

    vectors: np.ndarray
    client: Any = field(repr=False, compare=False)
    collection_name: str = QDRANT_COLLECTION_NAME

    @property
    def dimension(self) -> int:
        return int(self.vectors.shape[1])

    def __len__(self) -> int:
        return int(self.vectors.shape[0])

    def get(self, idx: int) -> np.ndarray:
        return self.vectors[idx]

    def query(
        self, qvec: np.ndarray, top_k: int
    ) -> list[tuple[int, float]]:
        if len(self) == 0 or top_k <= 0:
            return []
        qvec_f32 = np.asarray(qvec, dtype=np.float32)
        if qvec_f32.shape[-1] != self.dimension:
            raise ValueError(
                f"Query vector dim {qvec_f32.shape[-1]} does not match "
                f"index dim {self.dimension}."
            )
        # Qdrant's in-memory mode runs exact cosine search at this size
        # (no HNSW approximation kicks in for the small Korean RFP
        # corpora used in eval). For larger collections Qdrant uses an
        # HNSW index — the API contract here is "top-k cosine" and the
        # ranking ties are broken by Qdrant's stable point-id order.
        # ``query_points`` is the universal endpoint in qdrant-client
        # 1.10+; ``search`` was removed.
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=qvec_f32.tolist(),
            limit=top_k,
        )
        return [(int(p.id), float(p.score)) for p in response.points]

    def persist(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        np.save(
            output_dir / EMBEDDINGS_FILENAME,
            np.asarray(self.vectors, dtype=np.float32),
        )


def _build_qdrant_store(vectors: np.ndarray) -> QdrantVectorStore:
    """Build a QdrantVectorStore around an in-memory collection."""
    try:
        from qdrant_client import QdrantClient  # type: ignore[import-not-found]
        from qdrant_client.models import (  # type: ignore[import-not-found]
            Distance,
            PointStruct,
            VectorParams,
        )
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Qdrant backend requires the qdrant-client package. "
            "Install with `pip install qdrant-client` or use "
            "BIDMATE_INDEX_BACKEND=memory."
        ) from exc

    vectors_f32 = np.asarray(vectors, dtype=np.float32)
    client = QdrantClient(location=":memory:")
    # Empty matrices are valid (an index with zero chunks); the
    # collection still needs a dimension, so we default to 1 in that
    # degenerate case rather than crashing.
    dim = int(vectors_f32.shape[1]) if vectors_f32.size else 1
    # A fresh in-memory client never has the collection yet, but the
    # exists-then-create idiom is the post-1.7 qdrant-client
    # recommendation and survives any future code path that reuses a
    # client.
    if not client.collection_exists(QDRANT_COLLECTION_NAME):
        client.create_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
    if vectors_f32.shape[0] > 0:
        points = [
            PointStruct(id=i, vector=vectors_f32[i].tolist())
            for i in range(vectors_f32.shape[0])
        ]
        client.upsert(collection_name=QDRANT_COLLECTION_NAME, points=points)
    return QdrantVectorStore(vectors=vectors_f32, client=client)


def vector_store_from_matrix(vectors: np.ndarray) -> VectorStore:
    """Wrap a float32 matrix as the configured VectorStore backend.

    Backend selection (``BIDMATE_INDEX_BACKEND``):
      - ``memory`` (default) → ``InMemoryVectorStore``
      - ``qdrant``           → ``QdrantVectorStore`` (in-memory mode)
    ``pgvector`` is reserved for Stage 3 and raises NotImplementedError
    via ``load_vector_store``; build-path callers should not encounter
    it because configuration is checked before index build.
    """
    backend = _resolve_backend()
    vectors_f32 = np.asarray(vectors, dtype=np.float32)
    if backend == "qdrant":
        return _build_qdrant_store(vectors_f32)
    return InMemoryVectorStore(vectors=vectors_f32)


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

    Backend selection is delegated to ``vector_store_from_matrix`` so
    the build and read paths share one dispatch.
    """
    backend = _resolve_backend()
    if backend not in SUPPORTED_BACKENDS:
        raise NotImplementedError(
            f"Index backend {backend!r} is not yet implemented; "
            f"current support is {sorted(SUPPORTED_BACKENDS)}. See "
            f"issue #176 (Stage 3 = pgvector)."
        )

    if schema_version >= 2:
        embeddings_path = index_dir / EMBEDDINGS_FILENAME
        if not embeddings_path.exists():
            raise ValueError(
                f"Index schema_version={schema_version} requires sidecar "
                f"{embeddings_path}. Rebuild via scripts/build_index.py."
            )
        matrix = np.load(embeddings_path)
        return vector_store_from_matrix(matrix)

    if chunks is None:
        return None
    inline = [c.get("embedding") for c in chunks]
    if not inline or any(v is None for v in inline):
        return None
    return vector_store_from_matrix(np.asarray(inline, dtype=np.float32))
