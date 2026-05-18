"""Embedding primitives extracted from ``rag_core.py`` (ADR 0045, issue #843).

This module owns the *bytes-in, vectors-out* path of the BidMate pipeline:

- ``embed_texts`` — the public entry point, dispatching on the
  ``backend`` argument ("auto" / "sentence-transformers" / "hashing"
  / "openai") to the appropriate concrete implementation.
- ``hashing_embeddings`` — deterministic local fallback (the
  ``EMBEDDING_BACKEND=hashing`` path used by ``make smoke`` and CI).
- ``_embed_with_openai`` — OpenAI batch-embed adapter.
- ``sentence_transformer_cache_available`` — HF cache probe used by
  the auto-routing decision in ``embed_texts``.
- ``huggingface_offline`` — context manager that flips HF environment
  variables so SentenceTransformer never hits the network when the
  weights are already cached locally.
- ``expand_features`` — unigram + bigram feature expansion for the
  hashing backend.
- ``EmbeddingResult`` — dataclass returned by ``embed_texts``.
- ``MODEL_CACHE`` — process-level cache for SentenceTransformer
  instances (keyed by ``(model_name, local_only, adapter_path)``).
- ``DEFAULT_EMBEDDING_MODEL`` / ``DEFAULT_HASH_DIM`` — constants.

Leaf status: depends only on ``rag_text_processing.tokenize`` plus the
stdlib + optional third-party packages (``sentence-transformers``,
``openai``, ``huggingface_hub``, ``peft``) that are lazy-imported.
``rag_core.py`` and ``rag_retrieval.py`` import from here; this module
imports nothing from them, eliminating the function-local late-imports
that ADR 0045 flagged. ``rag_core`` re-exports every public symbol so
existing call sites (``from rag_core import embed_texts``, etc.) keep
working unchanged — the migration is purely structural.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from typing import Any

import numpy as np

from rag_text_processing import tokenize


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_HASH_DIM = 384

# Process-level cache for SentenceTransformer instances. Key:
# ``(model_name, local_only, adapter_path)`` — adapter_path is part of
# the key so ADR 0027 LoRA-adapted variants don't clobber unadapted
# weights of the same base model.
MODEL_CACHE: dict[tuple[str, bool, str | None], Any] = {}


def clear_model_caches() -> None:
    """Drop all process-level model caches.

    Issue #841 — RAG senior-review critique #7.2. ``MODEL_CACHE``
    accumulates SentenceTransformer instances across calls (and, by
    extension, across pytest sessions) for cost amortization. The
    instances themselves are stateless after load, so steady-state
    behavior is fine — but if a future test asserts "uncached load
    happens with these args", or a teardown wants to free GPU /
    page-cache memory, the test needs an explicit reset hook.

    Pytest wires this via the autouse session-scope
    ``_clear_model_caches_at_session_end`` fixture in
    ``tests/conftest.py``; non-pytest callers (notebooks, REPL) can
    invoke it directly. Also clears ``visual_ingestion._DONUT_MODEL_CACHE``
    when the visual_ingestion module has been imported, so the same
    "drop all model caches" intent covers both surfaces.

    ADR 0045 / issue #843 — this function lives in ``rag_embedding``
    (alongside ``MODEL_CACHE``) and is re-exported via ``rag_core`` so
    existing call sites (``from rag_core import clear_model_caches``)
    keep working unchanged.
    """
    MODEL_CACHE.clear()
    # ``visual_ingestion`` is an optional surface (HWP visual path);
    # only clear if the module was loaded so we don't pay the import
    # cost just to no-op. ``sys.modules`` lookup avoids forcing the
    # import.
    import sys

    visual_ingestion = sys.modules.get("visual_ingestion")
    if visual_ingestion is not None:
        donut_cache = getattr(visual_ingestion, "_DONUT_MODEL_CACHE", None)
        if isinstance(donut_cache, dict):
            donut_cache.clear()


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: np.ndarray
    backend: str
    model: str


def embed_texts(
    texts: list[str],
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    backend: str = "auto",
    local_only: bool = False,
) -> EmbeddingResult:
    if backend not in {"auto", "sentence-transformers", "hashing", "openai"}:
        raise ValueError(
            "--embedding_backend must be one of: auto, sentence-transformers, hashing, openai"
        )

    if backend == "openai":
        return _embed_with_openai(texts, model_name=model_name)

    should_try_sentence_transformers = backend == "sentence-transformers" or (
        backend == "auto" and sentence_transformer_cache_available(model_name)
    )

    if should_try_sentence_transformers:
        try:
            with huggingface_offline(local_only or backend == "auto"):
                from sentence_transformers import SentenceTransformer

                # ADR 0027 — additive LoRA adapter, gated by env var so
                # the default (env unset) path remains byte-identical
                # to pre-#434 behavior. ``adapter_path`` is part of the
                # cache key so adapted / unadapted variants of the same
                # base model don't clobber each other.
                adapter_path = os.environ.get("BIDMATE_EMBEDDING_LORA_ADAPTER") or None
                cache_key = (model_name, local_only or backend == "auto", adapter_path)
                model = MODEL_CACHE.get(cache_key)
                if model is None:
                    # ``BIDMATE_TORCH_DEVICE`` is an opt-in device override
                    # (Phase 3.5 closeout, issue #957). Default unset =
                    # sentence-transformers' own auto-detect (CUDA → MPS
                    # → CPU). Force ``cpu`` on Apple Silicon when MPS
                    # backend hangs on large indexes (BGE-M3 26k chunks
                    # observed an indefinite MPSStream::synchronize on
                    # a 16GB MBP — CPU is ~2x slower per batch but
                    # predictable and avoids unified-memory thrashing).
                    torch_device = os.environ.get("BIDMATE_TORCH_DEVICE", "").strip()
                    st_kwargs: dict[str, Any] = {}
                    if torch_device:
                        st_kwargs["device"] = torch_device
                    model = SentenceTransformer(model_name, **st_kwargs)
                    if adapter_path:
                        # PEFT is lazy-imported (optional dep in
                        # requirements-lora.txt) — the hashing-only CI
                        # path never executes this branch and so never
                        # needs the package installed.
                        from peft import PeftModel  # type: ignore[import-not-found]

                        underlying = model[0].auto_model
                        adapted = PeftModel.from_pretrained(underlying, adapter_path)
                        model[0].auto_model = adapted.merge_and_unload()
                    MODEL_CACHE[cache_key] = model
            # ``BIDMATE_ST_BATCH_SIZE`` is an opt-in memory-pressure knob
            # for large indexes on memory-constrained hardware (Phase 3.5
            # closeout, issue #957). Default is sentence-transformers' own
            # default (32) which is fine for short corpora but for the
            # real100_m3 BGE-M3 build (26k chunks, ~196 avg tokens) it
            # causes MPS unified-memory pressure + swap thrash on 16GB
            # MBPs. ``BIDMATE_ST_BATCH_SIZE=8`` cuts the peak ~4x with
            # no impact on the produced vectors (sentence-transformers
            # is deterministic across batch boundaries by construction —
            # each text is encoded independently).
            st_batch_size = os.environ.get("BIDMATE_ST_BATCH_SIZE", "").strip()
            encode_kwargs: dict[str, Any] = {
                "convert_to_numpy": True,
                "normalize_embeddings": True,
                "show_progress_bar": False,
            }
            if st_batch_size:
                try:
                    encode_kwargs["batch_size"] = int(st_batch_size)
                except ValueError:
                    pass
            vectors = model.encode(texts, **encode_kwargs)
            return EmbeddingResult(
                vectors=np.asarray(vectors, dtype=np.float32),
                backend="sentence-transformers",
                model=model_name,
            )
        except Exception as exc:
            if backend == "sentence-transformers":
                raise RuntimeError(f"Failed to load embedding model {model_name}: {exc}") from exc

    return EmbeddingResult(
        vectors=hashing_embeddings(texts, DEFAULT_HASH_DIM),
        backend="hashing",
        model="local-hashing-bow",
    )


def _embed_with_openai(texts: list[str], *, model_name: str) -> EmbeddingResult:
    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(
            "openai backend requires the openai SDK. "
            "Install with `pip install openai` or use --embedding_backend sentence-transformers."
        ) from exc
    api_key = os.environ.get("BIDMATE_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "BIDMATE_OPENAI_API_KEY (or OPENAI_API_KEY) is not set for embedding_backend=openai."
        )
    client = OpenAI(api_key=api_key)
    vectors: list[list[float]] = []
    batch_size = 100
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        resp = client.embeddings.create(model=model_name, input=batch)
        vectors.extend(item.embedding for item in resp.data)
    arr = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True).clip(min=1e-12)
    return EmbeddingResult(
        vectors=arr / norms,
        backend="openai",
        model=model_name,
    )


def sentence_transformer_cache_available(model_name: str) -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache
    except Exception:
        return False
    for filename in ("modules.json", "config_sentence_transformers.json", "config.json"):
        cached = try_to_load_from_cache(model_name, filename)
        if isinstance(cached, str):
            return True
    return False


class huggingface_offline:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.previous: dict[str, str | None] = {}

    def __enter__(self) -> None:
        if not self.enabled:
            return
        for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
            self.previous[key] = os.environ.get(key)
            os.environ[key] = "1"

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if not self.enabled:
            return
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def hashing_embeddings(texts: list[str], dim: int) -> np.ndarray:
    vectors = np.zeros((len(texts), dim), dtype=np.float32)
    for row, text in enumerate(texts):
        for token in expand_features(tokenize(text)):
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            idx = int(digest[:8], 16) % dim
            sign = 1.0 if int(digest[8:10], 16) % 2 == 0 else -1.0
            vectors[row, idx] += sign
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def expand_features(tokens: list[str]) -> list[str]:
    features = list(tokens)
    for left, right in zip(tokens, tokens[1:]):
        features.append(f"{left}_{right}")
    return features
