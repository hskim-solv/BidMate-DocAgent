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
* **Stage 2b** (merged) — Protocol-level ``query(qvec, top_k)`` and
  ``query_by_indices(qvec, indices)`` methods. ``InMemoryVectorStore``
  ships exact brute-force implementations; ``QdrantVectorStore``
  delegates ``query`` to ``client.query_points``.
* **Stage 2c** (merged) — ``rag_retrieval.apply_fusion_and_reranking``
  drives ranking through ``store.query`` / ``store.query_by_indices``
  so both backends share one cosine surface (#795).
* **Stage 2d** (#834, this PR) — Qdrant connection target is selectable
  via ``BIDMATE_QDRANT_URL``: empty / ``:memory:`` keeps the in-process
  default; ``http(s)://`` routes to a production server; any other
  string is treated as a local path for file-based persistence. Filter
  pushdown (Qdrant payload filters) and TLS / API-key auth remain
  follow-ups.
* **ADR 0081** — Chroma is the canonical zero-env backend for
  ``naive_baseline``. ``memory`` remains an explicit legacy/control
  backend; Qdrant remains an ops comparison backend.
* **Stage 3** (deferred) — pgvector backend for SaaS-Postgres scale.

Convention: follows the four-property Protocol-based pluggability pattern
(ADR 0020). New backends implement ``VectorStore`` and register via
``default_vector_store()`` — ``rag_core.py`` is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
import uuid

import numpy as np


INDEX_FILENAME = "index.json"
EMBEDDINGS_FILENAME = "embeddings.npy"

ENV_INDEX_BACKEND = "BIDMATE_INDEX_BACKEND"
# ADR 0001/0081 — chroma is the only default/baseline backend. ``memory``
# stays a test-control (chroma/memory/qdrant ranking parity) and must never
# become the default; pinned by
# tests/test_memory_backend_default_guard_regression.py (issue #1765).
DEFAULT_INDEX_BACKEND = "chroma"
# ``pgvector`` is reserved for Stage 3 — selecting it today raises
# NotImplementedError.
SUPPORTED_BACKENDS = frozenset({"chroma", "memory", "qdrant"})

# Qdrant in-memory collection name. Kept stable so introspection and
# future migrations can match against a single literal.
QDRANT_COLLECTION_NAME = "bidmate_index"
CHROMA_COLLECTION_NAME = "bidmate_index"
CHROMA_VECTOR_DIGEST_METADATA_KEY = "bidmate:vector_digest"
CHROMA_SCORE_TIE_ATOL = 1e-6

# Optional Qdrant connection target (issue #834). Empty / unset /
# ``:memory:`` keeps the in-process ``:memory:`` mode that has always
# been the default. ``http(s)://...`` routes to a production server;
# any other string is treated as a filesystem path for file-based
# persistence — matching qdrant-client's own ``location`` semantics.
ENV_QDRANT_URL = "BIDMATE_QDRANT_URL"
ENV_CHROMA_PATH = "BIDMATE_CHROMA_PATH"


def _top_k_order_from_scores(scores: np.ndarray, top_k: int) -> np.ndarray:
    """Return the legacy dense top-k order for a complete score vector."""
    k = min(top_k, len(scores))
    if k == len(scores):
        return np.argsort(-scores, kind="stable")
    partition = np.argpartition(-scores, k - 1)[:k]
    return partition[np.argsort(-scores[partition], kind="stable")]


def _sort_pairs_by_score_then_id(pairs: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """Return deterministic order for backend-provided scored ids."""
    return sorted(pairs, key=lambda item: (-item[1], item[0]))


class ChromaRankingDriftError(ValueError):
    """Raised when Chroma omits locally better ids from a top-k result."""


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
    backend_name: str

    def __len__(self) -> int: ...

    def get(self, idx: int) -> np.ndarray: ...

    def query(
        self, qvec: np.ndarray, top_k: int
    ) -> list[tuple[int, float]]: ...

    def query_by_indices(
        self, qvec: np.ndarray, indices: list[int]
    ) -> list[tuple[int, float]]:
        """Score the requested indices against ``qvec``; preserve order.

        Issue #795 — RAG senior-review critique #3. The retrieval loop
        previously called ``query(top_k=len(self))`` to build a full
        ``raw_cosine_by_idx`` map even when the metadata filter had
        narrowed candidates to a small subset. ``query_by_indices``
        lets the loop fetch dense scores for **only** the surfaced
        candidate indices, restoring the cost benefit of a filtered
        retrieval path.

        Returns ``(idx, score)`` pairs in the SAME order as
        ``indices`` (callers build a per-index dict). Out-of-range
        indices raise ``IndexError`` to surface index/chunk drift at
        the failing call site rather than silently producing zero
        scores (mirrors the critique #4 ``dense_similarity`` change
        from issue #784).
        """
        ...

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
    backend_name: str = "memory"

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
        # Keep the long-standing dense baseline order, including numpy's
        # deterministic argpartition cutoff behavior for tied scores.
        order = _top_k_order_from_scores(scores, top_k)
        return [(int(i), float(scores[i])) for i in order]

    def query_by_indices(
        self, qvec: np.ndarray, indices: list[int]
    ) -> list[tuple[int, float]]:
        # Issue #795 — see Protocol docstring. Local matrix slice +
        # dot product is the cheapest scoring path; identical to a
        # per-index loop of ``get(idx)`` + cosine, just vectorized.
        if not indices:
            return []
        qvec_f32 = np.asarray(qvec, dtype=np.float32)
        if qvec_f32.shape[-1] != self.dimension:
            raise ValueError(
                f"Query vector dim {qvec_f32.shape[-1]} does not match "
                f"index dim {self.dimension}."
            )
        # IndexError surfaces drift instead of silent zero scores —
        # the chunk's ``embedding_idx`` was supposed to point into
        # this matrix.
        idx_array = np.asarray(indices, dtype=np.int64)
        rows = self.vectors[idx_array]
        scores = rows @ qvec_f32
        return [(int(i), float(s)) for i, s in zip(indices, scores)]

    def persist(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        np.save(
            output_dir / EMBEDDINGS_FILENAME,
            np.asarray(self.vectors, dtype=np.float32),
        )


@dataclass
class QdrantVectorStore:
    """Qdrant-backed VectorStore (#176 Stage 2a + 2b + #834).

    Wraps the same ``(N, D)`` float32 L2-normalized matrix as
    ``InMemoryVectorStore`` and mirrors it into a Qdrant collection.
    Connection target is selected by ``BIDMATE_QDRANT_URL``:

      - unset / empty / ``:memory:`` → in-process ``location=":memory:"``
        (default, no external dependency)
      - ``http(s)://...`` → production HTTP server
      - any other string → file-based ``location=<path>``

    ``get(idx)`` returns the bit-identical row from the in-memory
    matrix; ``query`` delegates to ``client.query_points`` so the Qdrant
    collection actually drives the cosine top-k ranking. The
    ``embeddings.npy`` sidecar is written regardless of connection
    target so users can switch backends without rebuilding the index.
    """

    vectors: np.ndarray
    client: Any = field(repr=False, compare=False)
    collection_name: str = QDRANT_COLLECTION_NAME
    backend_name: str = "qdrant"

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

    def query_by_indices(
        self, qvec: np.ndarray, indices: list[int]
    ) -> list[tuple[int, float]]:
        # Issue #795 — see Protocol docstring. Qdrant's value-add is
        # the search path (server-side top-K); for "score these N
        # specific points against this vector" the matrix dot is
        # both faster (no round-trip) and bit-identical to the
        # in-memory backend (the dataclass owns the same matrix as
        # the source of truth — see ``_build_qdrant_store``). This
        # keeps the in-memory ↔ Qdrant ranking parity guarantee
        # asserted by ``test_qdrant_query_matches_in_memory_top_k_ranking``.
        if not indices:
            return []
        qvec_f32 = np.asarray(qvec, dtype=np.float32)
        if qvec_f32.shape[-1] != self.dimension:
            raise ValueError(
                f"Query vector dim {qvec_f32.shape[-1]} does not match "
                f"index dim {self.dimension}."
            )
        idx_array = np.asarray(indices, dtype=np.int64)
        rows = self.vectors[idx_array]
        scores = rows @ qvec_f32
        return [(int(i), float(s)) for i, s in zip(indices, scores)]

    def persist(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        np.save(
            output_dir / EMBEDDINGS_FILENAME,
            np.asarray(self.vectors, dtype=np.float32),
        )


@dataclass
class ChromaVectorStore:
    """Chroma-backed VectorStore for the canonical naive baseline.

    The on-disk index remains ``embeddings.npy`` + ``index.json``. Chroma is
    materialized from that matrix at load/build time, so switching back to
    ``memory`` still does not require rebuilding the index.
    """

    vectors: np.ndarray
    client: Any = field(repr=False, compare=False)
    collection: Any = field(repr=False, compare=False)
    collection_name: str = CHROMA_COLLECTION_NAME
    backend_name: str = "chroma"

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
        limit = min(top_k, len(self))
        scores = self.vectors @ qvec_f32
        expected_order = _top_k_order_from_scores(scores, top_k)
        expected_ids = [int(i) for i in expected_order]
        pairs = self._query_chroma_pairs(qvec_f32, n_results=limit)
        actual_ids = [idx for idx, _ in pairs]
        if len(actual_ids) != limit:
            if limit == len(self):
                # Full-corpus scan: chroma's in-memory HNSW (search_ef ≪ k,
                # num_threads=cpu_count) can nondeterministically drop rows when
                # n_results ≈ collection size. We already hold the exact numpy
                # ranking, so fall back to it instead of crashing. Partial
                # top-k stays strict — a short result there is a real defect.
                # (#1841)
                return [(idx, float(scores[idx])) for idx in expected_ids]
            raise ValueError(
                "Chroma query returned "
                f"{len(actual_ids)} rows for requested top-k {limit}."
            )
        if len(set(actual_ids)) != len(actual_ids):
            raise ValueError(f"Chroma query returned duplicate ids: {actual_ids}.")
        if any(idx < 0 or idx >= len(self) for idx in actual_ids):
            raise ValueError(f"Chroma query returned out-of-range ids: {actual_ids}.")
        if actual_ids != expected_ids:
            actual_set = set(actual_ids)
            actual_min_score = min(float(scores[idx]) for idx in actual_ids)
            omitted_better_ids = [
                int(idx)
                for idx, score in enumerate(scores)
                if idx not in actual_set
                and float(score) > actual_min_score + CHROMA_SCORE_TIE_ATOL
            ]
            if omitted_better_ids:
                raise ChromaRankingDriftError(
                    "Chroma top-k ranking drift: "
                    f"expected {expected_ids}, got {actual_ids}; "
                    f"omitted better ids {omitted_better_ids}."
                )
            return [(idx, float(scores[idx])) for idx in expected_ids]
        return _sort_pairs_by_score_then_id(pairs)

    def _query_chroma_pairs(
        self,
        qvec_f32: np.ndarray,
        n_results: int,
    ) -> list[tuple[int, float]]:
        result = self.collection.query(
            query_embeddings=[qvec_f32.tolist()],
            n_results=n_results,
            include=["distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        return [
            (int(idx), float(1.0 - distance))
            for idx, distance in zip(ids, distances)
        ]

    def query_by_indices(
        self, qvec: np.ndarray, indices: list[int]
    ) -> list[tuple[int, float]]:
        if not indices:
            return []
        qvec_f32 = np.asarray(qvec, dtype=np.float32)
        if qvec_f32.shape[-1] != self.dimension:
            raise ValueError(
                f"Query vector dim {qvec_f32.shape[-1]} does not match "
                f"index dim {self.dimension}."
            )
        idx_array = np.asarray(indices, dtype=np.int64)
        rows = self.vectors[idx_array]
        scores = rows @ qvec_f32
        return [(int(i), float(s)) for i, s in zip(indices, scores)]

    def persist(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        np.save(
            output_dir / EMBEDDINGS_FILENAME,
            np.asarray(self.vectors, dtype=np.float32),
        )


def _make_qdrant_client(qdrant_client_cls: Any) -> Any:
    """Construct a Qdrant client according to ``BIDMATE_QDRANT_URL``.

    Routing (issue #834):
      - unset / empty / ``:memory:`` → ``location=":memory:"`` (default)
      - ``http://...`` / ``https://...`` → ``url=<URL>`` (production server)
      - any other string → ``location=<path>`` (file-based persistence)

    Receives ``qdrant_client_cls`` as a parameter so tests can inject a
    fake without monkey-patching the qdrant-client module.
    """
    url = os.environ.get(ENV_QDRANT_URL, "").strip()
    if not url or url == ":memory:":
        return qdrant_client_cls(location=":memory:")
    if url.startswith(("http://", "https://")):
        return qdrant_client_cls(url=url)
    return qdrant_client_cls(location=url)


def _make_chroma_client(chromadb_module: Any) -> Any:
    """Construct an embedded Chroma client.

    Empty ``BIDMATE_CHROMA_PATH`` keeps the in-memory client. A non-empty value
    opts into local persistence via ``PersistentClient(path=...)``.
    """
    from chromadb.config import Settings  # type: ignore[import-not-found]

    settings = Settings(anonymized_telemetry=False)
    path = os.environ.get(ENV_CHROMA_PATH, "").strip()
    if path:
        return chromadb_module.PersistentClient(path=path, settings=settings)
    return chromadb_module.Client(settings=settings)


def _build_qdrant_store(vectors: np.ndarray) -> QdrantVectorStore:
    """Build a QdrantVectorStore around the configured Qdrant client.

    Client target is selected by ``BIDMATE_QDRANT_URL`` — see
    ``_make_qdrant_client``. Default is in-process ``:memory:``.
    """
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
    client = _make_qdrant_client(QdrantClient)
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


def _chroma_index_digest(vectors: np.ndarray) -> str:
    vectors_f32 = np.ascontiguousarray(vectors, dtype=np.float32)
    h = hashlib.sha256()
    h.update(str(tuple(vectors_f32.shape)).encode("ascii"))
    h.update(vectors_f32.tobytes())
    return h.hexdigest()[:16]


def _chroma_collection_metadata(vector_digest: str | None = None) -> dict[str, str]:
    metadata = {"hnsw:space": "cosine"}
    if vector_digest is not None:
        metadata[CHROMA_VECTOR_DIGEST_METADATA_KEY] = vector_digest
    return metadata


def _create_chroma_collection(
    client: Any,
    collection_name: str,
    vector_digest: str | None = None,
) -> Any:
    metadata = _chroma_collection_metadata(vector_digest)
    try:
        return client.get_or_create_collection(
            name=collection_name,
            configuration={"hnsw": {"space": "cosine"}},
            metadata=metadata,
            embedding_function=None,
        )
    except TypeError:
        return client.get_or_create_collection(
            name=collection_name,
            metadata=metadata,
            embedding_function=None,
        )


def _chroma_batch_size(client: Any) -> int:
    try:
        size = int(client.get_max_batch_size())
    except Exception:
        size = 5000
    return max(1, size)


def _upsert_chroma_vectors(
    client: Any,
    collection: Any,
    vectors: np.ndarray,
) -> None:
    ids = [str(i) for i in range(vectors.shape[0])]
    batch_size = _chroma_batch_size(client)
    for start in range(0, vectors.shape[0], batch_size):
        end = min(start + batch_size, vectors.shape[0])
        collection.upsert(
            ids=ids[start:end],
            embeddings=vectors[start:end].tolist(),
        )


def _set_chroma_digest_metadata(collection: Any, vector_digest: str) -> None:
    metadata = {
        key: value
        for key, value in dict(collection.metadata or {}).items()
        if key != "hnsw:space"
    }
    metadata[CHROMA_VECTOR_DIGEST_METADATA_KEY] = vector_digest
    collection.modify(metadata=metadata)


def _stored_chroma_rows(
    collection: Any,
    ids: list[str],
) -> dict[int, np.ndarray]:
    result = collection.get(ids=ids, include=["embeddings"])
    returned_ids = result.get("ids") or []
    embeddings = result.get("embeddings")
    if embeddings is None:
        raise ValueError("Chroma collection did not return embeddings.")
    by_id = {
        int(idx): np.asarray(embedding, dtype=np.float32)
        for idx, embedding in zip(returned_ids, embeddings)
    }
    if len(by_id) != len(returned_ids):
        raise ValueError("Chroma collection returned duplicate ids.")
    return by_id


def _stored_chroma_matrix(
    collection: Any,
    expected: int,
) -> np.ndarray:
    ids = [str(i) for i in range(expected)]
    by_id = _stored_chroma_rows(collection, ids)
    if len(by_id) != expected:
        raise ValueError(
            f"Chroma collection returned {len(by_id)} rows for "
            f"{expected} expected ids."
        )
    if set(by_id) != set(range(expected)):
        raise ValueError("Chroma collection ids do not match embeddings sidecar ids.")
    return np.asarray([by_id[i] for i in range(expected)], dtype=np.float32)


def _verify_chroma_collection_integrity(
    collection: Any,
    collection_name: str,
    vectors: np.ndarray,
    vector_digest: str,
) -> None:
    expected = int(vectors.shape[0])
    stored_vectors = _stored_chroma_matrix(collection, expected)
    if not np.allclose(stored_vectors, vectors, rtol=0, atol=1e-6):
        stored_digest = _chroma_index_digest(stored_vectors)
        raise ValueError(
            f"Chroma collection {collection_name!r} vector digest {stored_digest} "
            f"does not match embeddings sidecar digest {vector_digest}."
        )
    metadata_digest = (collection.metadata or {}).get(CHROMA_VECTOR_DIGEST_METADATA_KEY)
    if metadata_digest != vector_digest:
        _set_chroma_digest_metadata(collection, vector_digest)


def _materialize_chroma_vectors(
    client: Any,
    collection: Any,
    collection_name: str,
    vectors: np.ndarray,
    vector_digest: str,
    verify_existing: bool,
) -> Any:
    expected = int(vectors.shape[0])
    count = int(collection.count())
    if count == expected:
        if verify_existing and expected > 0:
            _verify_chroma_collection_integrity(
                collection,
                collection_name,
                vectors,
                vector_digest,
            )
        return collection
    if count != 0:
        if not verify_existing or count > expected:
            raise ValueError(
                f"Chroma collection {collection_name!r} has {count} rows, "
                f"but embeddings sidecar has {expected} rows."
            )
        existing_rows = _stored_chroma_rows(
            collection,
            [str(i) for i in range(expected)],
        )
        if len(existing_rows) != count:
            raise ValueError(
                f"Chroma collection {collection_name!r} contains ids outside "
                "the deterministic embeddings sidecar id range."
            )
        for idx, stored_vector in existing_rows.items():
            if not np.allclose(stored_vector, vectors[idx], rtol=0, atol=1e-6):
                raise ValueError(
                    f"Chroma collection {collection_name!r} partial row {idx} "
                    "does not match embeddings sidecar."
                )
    if expected > 0:
        _upsert_chroma_vectors(client, collection, vectors)
        count = int(collection.count())
        if count != expected:
            raise ValueError(
                f"Chroma collection {collection_name!r} has {count} rows, "
                f"but embeddings sidecar has {expected} rows after materialization."
            )
        if verify_existing:
            _verify_chroma_collection_integrity(
                collection,
                collection_name,
                vectors,
                vector_digest,
            )
        else:
            _set_chroma_digest_metadata(collection, vector_digest)
    return collection


def _build_chroma_store(vectors: np.ndarray) -> ChromaVectorStore:
    try:
        import chromadb  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - dependency gate
        raise RuntimeError(
            "Chroma backend requires the chromadb package. "
            "Install with `pip install chromadb` or use "
            "BIDMATE_INDEX_BACKEND=memory."
        ) from exc

    vectors_f32 = np.asarray(vectors, dtype=np.float32)
    client = _make_chroma_client(chromadb)
    vector_digest = _chroma_index_digest(vectors_f32)
    if os.environ.get(ENV_CHROMA_PATH, "").strip():
        collection_name = f"{CHROMA_COLLECTION_NAME}_{vector_digest}"
        verify_existing = True
    else:
        collection_name = f"{CHROMA_COLLECTION_NAME}_{uuid.uuid4().hex}"
        verify_existing = False
    collection = _create_chroma_collection(client, collection_name, vector_digest)
    collection = _materialize_chroma_vectors(
        client=client,
        collection=collection,
        collection_name=collection_name,
        vectors=vectors_f32,
        vector_digest=vector_digest,
        verify_existing=verify_existing,
    )
    return ChromaVectorStore(
        vectors=vectors_f32,
        client=client,
        collection=collection,
        collection_name=collection_name,
    )


def vector_store_from_matrix(
    vectors: np.ndarray,
    backend: str | None = None,
) -> VectorStore:
    """Wrap a float32 matrix as the configured VectorStore backend.

    Backend selection (``BIDMATE_INDEX_BACKEND``):
      - ``chroma`` (default) → ``ChromaVectorStore`` (embedded)
      - ``memory``           → ``InMemoryVectorStore``
      - ``qdrant``           → ``QdrantVectorStore`` (in-memory mode)
    ``pgvector`` is reserved for Stage 3 and raises NotImplementedError
    via ``load_vector_store``; build-path callers should not encounter
    it because configuration is checked before index build.
    """
    backend = _resolve_backend(backend)
    vectors_f32 = np.asarray(vectors, dtype=np.float32)
    if backend not in SUPPORTED_BACKENDS:
        raise NotImplementedError(
            f"Index backend {backend!r} is not yet implemented; "
            f"current support is {sorted(SUPPORTED_BACKENDS)}. See "
            f"issue #176 (Stage 3 = pgvector)."
        )
    if backend == "chroma":
        return _build_chroma_store(vectors_f32)
    if backend == "qdrant":
        return _build_qdrant_store(vectors_f32)
    return InMemoryVectorStore(vectors=vectors_f32)


def _resolve_backend(backend: str | None = None) -> str:
    return (
        backend
        if backend is not None
        else os.environ.get(ENV_INDEX_BACKEND, DEFAULT_INDEX_BACKEND)
    ).strip().lower()


def load_vector_store(
    index_dir: Path,
    schema_version: int,
    chunks: list[dict] | None = None,
    backend: str | None = None,
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
    backend = _resolve_backend(backend)
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
        return vector_store_from_matrix(matrix, backend=backend)

    if chunks is None:
        return None
    inline = [c.get("embedding") for c in chunks]
    if not inline or any(v is None for v in inline):
        return None
    return vector_store_from_matrix(np.asarray(inline, dtype=np.float32), backend=backend)
