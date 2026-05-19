"""BGE-M3 multi-channel encoder for ``retrieval_backend = "m3"`` (issue #151).

BGE-M3 emits three retrieval-relevant outputs in a single forward pass:

* **dense** — a single L2-normalized vector per text (used like any other
  sentence embedding).
* **sparse** — a lexical-weight dict ``{token_id: weight}`` per text
  (SPLADE-style; a score against another text is the weighted dot
  product on the shared vocabulary).
* **multi-vector / ColBERT** — a per-token ``(T_i, 1024)`` matrix per
  text (late-interaction max-sim sum).

This module is the **measurement-spike wrapper** for those outputs. It
exists as a separate leaf module (no imports from ``rag_core``) so that
the heavy ``FlagEmbedding`` dependency stays opt-in: the default
``dense`` / ``hybrid`` retrieval paths never import it, the public
synthetic CI (``EMBEDDING_BACKEND=hashing``) never installs it, and
absence raises a clear ``RuntimeError`` only when the user actually opts
into ``retrieval_backend = "m3"``.

See ``docs/vision/m3-multichannel-spike.md`` for the measurement methodology and
ADR 0010's "Alternatives considered" (lines 72-85) for why the channel
extraction was deferred to its own ablation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np


DEFAULT_M3_MODEL = "BAAI/bge-m3"


@dataclass(frozen=True)
class M3Output:
    """Three-channel BGE-M3 forward-pass output.

    ``dense`` is shape ``(N, D)`` (D=1024 for BGE-M3, L2-normalized).
    ``sparse`` is a list of N dicts mapping ``token_id -> weight``; only
    non-zero tokens are present (per-text sparsity).
    ``colbert`` is a list of N per-token matrices shape ``(T_i, D)``;
    ``T_i`` varies per text (BGE-M3 returns one vector per kept token).
    ``colbert_scales`` is the per-chunk dequantization scale when colbert
    matrices are stored at ``np.int8`` (issue #1010 — symmetric
    per-chunk quantization cuts ``_m3_cache`` RAM by an additional ~50%
    on top of fp16). Empty list when colbert is fp16/fp32 (no scale
    needed; numpy matmul auto-upcasts in ``colbert_score``).
    """

    dense: np.ndarray
    sparse: list[dict[int, float]]
    colbert: list[np.ndarray]
    colbert_scales: list[float] = field(default_factory=list)


class M3Encoder:
    """Thin wrapper around ``FlagEmbedding.BGEM3FlagModel`` that returns
    the three channels in a single forward pass.

    The encoder is heavy (~2GB weights, GPU-preferred). Callers should
    use the module-level ``get_m3_encoder()`` singleton rather than
    constructing one per query — see ``rag_core.MODEL_CACHE`` pattern.
    """

    def __init__(self, model_name: str = DEFAULT_M3_MODEL) -> None:
        try:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover — install path
            raise RuntimeError(
                "m3 backend requires FlagEmbedding. "
                "Install with `pip install -r requirements-m3.txt` "
                "or use `retrieval_backend=hybrid`."
            ) from exc
        # ``BIDMATE_M3_USE_FP16=1`` opts into half-precision weights AND
        # fp16 colbert cache storage — cuts peak RAM ~2x at the cost of
        # <0.1% recall on the BGE-M3 paper benchmarks. Default fp32
        # preserves byte-identical reproducibility of every existing m3
        # result; the env var is for memory-constrained measurement (e.g.
        # Phase 3.5 on 16GB MPS systems where the _m3_cache for 26k+ chunks
        # at fp32 would otherwise OOM-kill the process). The cache dtype
        # mirrors the model dtype because the colbert per-token vectors
        # are the dominant footprint (issue #1006 evidence: 26k chunks ×
        # ~196 avg tokens × 1024 dim × 4 bytes fp32 = 19.8GB, vs 9.9GB
        # at fp16; the model weights themselves are <2GB regardless).
        use_fp16 = os.environ.get("BIDMATE_M3_USE_FP16", "").strip() in {"1", "true", "True"}
        self._model = BGEM3FlagModel(model_name, use_fp16=use_fp16)
        self._cache_dtype = np.float16 if use_fp16 else np.float32
        # ``BIDMATE_M3_INT8_CACHE=1`` opts into per-chunk symmetric int8
        # quantization of the colbert cache (issue #1010 — on-top-of fp16
        # cuts ``_m3_cache`` 9.9GB → 5.0GB on the 26k-chunk kordoc index
        # so a 16GB MBP can run the full BGE-M3 multi-channel measurement
        # without swap thrash). Encoding stays fp16 on MPS; quantization
        # happens after the model returns. Score paths dequant on demand
        # (cost: per-query int8 → fp32 cast + scale multiply, dominated
        # by the matmul itself).
        self._int8_cache = os.environ.get(
            "BIDMATE_M3_INT8_CACHE", ""
        ).strip() in {"1", "true", "True"}
        self.model_name = model_name

    def encode(self, texts: list[str]) -> M3Output:
        """Return all three channels for ``texts``. Empty input is
        a no-op (returns an empty ``M3Output``). The encoder is
        symmetric — query and document texts use the same call (BGE-M3
        does not distinguish; the asymmetry is in the scoring, not the
        encoding).
        """
        if not texts:
            return M3Output(
                dense=np.zeros((0, 0), dtype=np.float32),
                sparse=[],
                colbert=[],
                colbert_scales=[],
            )
        # BGE-M3 returns:
        #   {"dense_vecs": (N, 1024) float, L2-normalized
        #    "lexical_weights": list[dict[str, float]]  # token-id keys as strings
        #    "colbert_vecs":   list[ndarray (T_i, 1024)]}
        raw = self._model.encode(
            texts,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=True,
        )
        dense = np.asarray(raw["dense_vecs"], dtype=np.float32)
        # Normalize the sparse dict keys to int so the scorer can do a
        # straightforward dict intersection without per-call str() casts.
        sparse_raw = raw.get("lexical_weights") or []
        sparse: list[dict[int, float]] = []
        for sd in sparse_raw:
            sparse.append({int(tok): float(weight) for tok, weight in sd.items()})
        colbert_raw = raw.get("colbert_vecs") or []
        # Issue #1006 — colbert per-token cache dominates memory footprint.
        # Honor ``BIDMATE_M3_USE_FP16=1`` here too so cache halves alongside
        # weights (line 81). numpy matmul auto-upcasts fp16 → fp32 in
        # ``colbert_score`` so the scoring path is unaffected.
        colbert: list[np.ndarray]
        colbert_scales: list[float]
        if self._int8_cache:
            # Issue #1010 — per-chunk symmetric int8 quantization.
            # ``scale = max(|v|) / 127`` per chunk (independent dynamic
            # range), then int8 = round(v / scale).clip(-127, 127).
            # Empty / zero vectors: scale=1.0 keeps the dequant identity
            # well-defined (multiply by 0 stays 0).
            colbert = []
            colbert_scales = []
            for vec in colbert_raw:
                arr = np.asarray(vec, dtype=np.float32)
                if arr.size == 0:
                    colbert.append(arr.astype(np.int8))
                    colbert_scales.append(1.0)
                    continue
                max_abs = float(np.max(np.abs(arr)))
                scale = max_abs / 127.0 if max_abs > 0.0 else 1.0
                quant = np.clip(
                    np.round(arr / scale), -127, 127
                ).astype(np.int8)
                colbert.append(quant)
                colbert_scales.append(scale)
        else:
            colbert = [np.asarray(vec, dtype=self._cache_dtype) for vec in colbert_raw]
            colbert_scales = []
        return M3Output(
            dense=dense,
            sparse=sparse,
            colbert=colbert,
            colbert_scales=colbert_scales,
        )

    @staticmethod
    def sparse_score(q_sparse: dict[int, float], d_sparse: dict[int, float]) -> float:
        """SPLADE-style weighted dot product on the shared vocabulary.

        Non-negative — both sides come from ReLU'd projections in BGE-M3.
        """
        if not q_sparse or not d_sparse:
            return 0.0
        # Iterate the smaller dict for the intersection.
        if len(q_sparse) > len(d_sparse):
            q_sparse, d_sparse = d_sparse, q_sparse
        total = 0.0
        for tok, q_w in q_sparse.items():
            d_w = d_sparse.get(tok)
            if d_w is not None:
                total += float(q_w) * float(d_w)
        return total

    @staticmethod
    def colbert_score(
        q_colbert: np.ndarray,
        d_colbert: np.ndarray,
        q_scale: float = 1.0,
        d_scale: float = 1.0,
    ) -> float:
        """ColBERT max-sim sum (sum over query tokens of the max similarity
        across document tokens). BGE-M3's per-token outputs are
        L2-normalized so the dot is bounded by ``T_q`` (one per query token,
        each ≤ 1). Bounded ``[0, T_q]`` — callers normalize against the
        observed maximum if a ``[0, 1]`` projection is needed.

        ``q_scale`` / ``d_scale`` are the per-chunk dequantization scales
        when the input matrices are ``np.int8`` (issue #1010 — int8 cache
        path). Default 1.0 = no quantization (fp16/fp32 caller path);
        scalar multiplication after the matmul preserves the max-sim
        ordering modulo round-off (BGE-M3 paper benchmark: <0.5% recall
        delta at per-chunk symmetric int8).
        """
        if q_colbert.size == 0 or d_colbert.size == 0:
            return 0.0
        # (T_q, T_d) similarity matrix → row-wise max → sum. Cast to
        # fp32 first when int8 inputs: numpy's int8 @ int8 → int8 would
        # overflow on the accumulated sum; explicit fp32 cast keeps the
        # math identical to the fp16/fp32 path.
        if q_colbert.dtype == np.int8 or d_colbert.dtype == np.int8:
            sims = (
                q_colbert.astype(np.float32) @ d_colbert.astype(np.float32).T
            ) * (q_scale * d_scale)
        else:
            sims = q_colbert @ d_colbert.T
        return float(np.sum(np.max(sims, axis=1)))


_ENCODER_CACHE: dict[str, M3Encoder] = {}


def get_m3_encoder(model_name: str = DEFAULT_M3_MODEL) -> M3Encoder:
    """Module-level lazy singleton. Loads the weights once per process;
    repeat calls return the cached encoder. Mirrors the
    ``rag_core.MODEL_CACHE`` and ``rag_rerank._RERANKER_CACHE``
    patterns.
    """
    cached = _ENCODER_CACHE.get(model_name)
    if cached is not None:
        return cached
    encoder = M3Encoder(model_name)
    _ENCODER_CACHE[model_name] = encoder
    return encoder


def compute_m3_index_cache(
    encoder: M3Encoder,
    chunks: list[dict[str, Any]],
) -> M3Output:
    """One-shot forward pass over every chunk in the index.

    Called the first time ``retrieval_backend = "m3"`` is used against
    an index. The result is attached to the index dict under
    ``_m3_cache`` (underscore-prefix convention, matching
    ``_vector_store``). Nothing is persisted to disk for this spike —
    see ``docs/vision/m3-multichannel-spike.md`` decision rule.
    """
    texts = [str(c.get("text") or "") for c in chunks]
    return encoder.encode(texts)
