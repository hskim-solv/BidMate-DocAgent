#!/usr/bin/env python3
"""Phase 3.5 retrieval-eval — m3 (BGE-M3 semantic) mode ablation on real100 (n=221).

Runs 3 retrieval-mode variants against the same ``data/index/real100_m3``
index (BGE-M3 1024-dim dense, built once with
``scripts/build_index.py --embedding_backend sentence-transformers
--model BAAI/bge-m3``) and computes paired bootstrap CI deltas vs the
``dense_m3`` baseline per category:

* ``dense_m3``             — single-channel semantic dense baseline
* ``hybrid_bm25_k60_m3``   — RRF over (semantic dense, BM25), k=60.
  Re-tests Phase 3's hybrid-vs-dense question on semantic embeddings,
  resolving the "hashing-only" caveat in Phase 3's REPORT.md.
* ``m3``                   — 3-way RRF over (semantic dense, BGE-M3 sparse,
  BGE-M3 colbert). The ADR 0010 deferred multi-channel ablation.

Output lives under ``reports/retrieval/phase35_m3_<TIMESTAMP>/``:

* ``mode_specs.json``  — variant metadata
* ``raw_results.json`` — per-case scores for all 3 variants
* ``deltas.json``      — paired CI vs dense_m3 per (variant, metric, category)
* ``REPORT.md``        — <=200 line markdown with per-category winner or
  ``유의하지 않음`` (CI crosses 0) per absolute rule #5

Reuses (no new abstraction — absolute rule #3):

* ``rag_retrieval.retrieve_candidates`` (planner bypass — full query as the
  only sub-query, identity expansion, no rerank, ``metadata_first=False``).
  m3 dispatch + 3-way RRF live in ``rag_retrieval.py`` itself; the runner
  only sets ``plan["retrieval_backend"]`` and ``plan["rrf_k"]``.
* ``rag_indexing.load_index``
* ``eval.scorers.chunk_metrics.{derive_gold_chunk_ids, chunk_recall_at_k,
  chunk_mrr, chunk_ndcg_at_k}``
* ``scripts._ablation_common`` — paired CI aggregation + report formatting
  helpers extracted in PR #954 (issue #953)

The ``_m3_cache`` (sparse + colbert per chunk) lives on the index dict
in-memory only (ADR 0025 spike-mode, no disk persist). Cold-start
~2 min for 26k chunks; absorbed by ``--warmup 3`` so the per-case latency
stats for the ``m3`` variant reflect cache-hit cost, not cache-build cost.

Cross-references: ADR 0010 (BGE-M3 deferred), ADR 0021 (m3_full row),
ADR 0032 (torch>=2.6 unblock). Phase 3 REPORT:
``reports/retrieval/phase3_mode_20260518T032404Z/REPORT.md``.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

PRIVATE_REAL_MIN_DOCS = 50
LOW_CHUNK_REAL_MAX = 1000

from eval.scorers.chunk_metrics import (  # noqa: E402
    chunk_mrr,
    chunk_ndcg_at_k,
    chunk_recall_at_k,
    derive_gold_chunk_ids,
)
from rag_indexing import load_index  # noqa: E402
from rag_retrieval import apply_fusion_and_reranking, retrieve_candidates  # noqa: E402
from rag_text_processing import tokenize  # noqa: E402
from scripts._ablation_common import (  # noqa: E402
    _fmt_ci,
    _fmt_mean,
    anon_qid,
    categories_from_case,
    compute_deltas,
)


@dataclass(frozen=True)
class VariantSpec:
    name: str
    retrieval_backend: str  # "dense" | "hybrid" | "m3"
    rrf_k: int | None       # 60 for hybrid_bm25_k60_m3; None for dense_m3 + m3
    index_dir: Path         # 3 entries share data/index/real100_m3


def index_build_counts(index: dict[str, Any]) -> tuple[int | None, int | None]:
    build = index.get("build")
    if not isinstance(build, dict):
        build = {}
    docs = build.get("num_documents")
    chunks = build.get("num_chunks")
    if docs is None:
        docs = len(index.get("documents") or [])
    if chunks is None:
        chunks = len(index.get("chunks") or [])
    try:
        docs_int = int(docs) if docs is not None else None
    except (TypeError, ValueError):
        docs_int = None
    try:
        chunks_int = int(chunks) if chunks is not None else None
    except (TypeError, ValueError):
        chunks_int = None
    return docs_int, chunks_int


def guard_private_real100_chunk_count(index: dict[str, Any], index_dir: Path) -> None:
    docs, chunks = index_build_counts(index)
    if (
        docs is not None
        and chunks is not None
        and docs >= PRIVATE_REAL_MIN_DOCS
        and 0 < chunks <= LOW_CHUNK_REAL_MAX
    ):
        raise ValueError(
            f"{index_dir} looks like a stale/invalid CSV-fallback real100 index "
            f"({docs} docs, {chunks} chunks). Rebuild from kordoc cache/source "
            "before running phase35_m3 measurement."
        )


def _plan_for_variant(spec: VariantSpec, top_k: int) -> dict[str, Any]:
    """Build a plan dict that exercises exactly the variant's retrieval
    mode — everything else (expansion, rerank, metadata-first) is held
    flat across variants to isolate the mode effect.
    """
    plan: dict[str, Any] = {
        "retrieval_backend": spec.retrieval_backend,
        "metadata_filters": {},
        "metadata_first": False,
        "rerank": False,
        "query_expansion": "identity",
        "bm25_stopword_profile": "shared",
        "bm25_tokenizer": "regex",
        "top_k": top_k,
    }
    if spec.rrf_k is not None:
        plan["rrf_k"] = spec.rrf_k
    return plan


def _analysis_stub(query: str) -> dict[str, Any]:
    return {
        "query_type": "single_doc",
        "tokens": list(tokenize(query)),
        "topics": [],
        "entities": [],
        "metadata_filters_by_stage": {"strict": {}, "reduced": {}, "relaxed": {}},
    }


def run_single_case(
    index: dict[str, Any], case: dict[str, Any], spec: VariantSpec, top_k: int
) -> tuple[list[str], float]:
    query = str(case.get("query") or "")
    analysis = _analysis_stub(query)
    plan = _plan_for_variant(spec, top_k)
    t0 = time.perf_counter()
    # retrieve_candidates is the candidate-generation stage only; for
    # hybrid + m3 backends it returns score=0.0 placeholders with the
    # raw per-channel signals living in score_parts. The RRF fusion +
    # final top-k truncation live in apply_fusion_and_reranking — without
    # this second call hybrid/m3 ranks degenerate to chunk_id alphabetic
    # order (every score equal so Python's stable sort falls back to
    # insertion order). Phase 3 PR #956 had this same omission, which is
    # why all 3 RRF-k variants looked byte-identical there. The fix here
    # is the runner-side wire-up; rag_retrieval is unchanged.
    candidates = retrieve_candidates(index, query, analysis, plan)
    final = apply_fusion_and_reranking(candidates, index, query, analysis, plan)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return [str(c["chunk_id"]) for c in final[:top_k]], latency_ms


def _prime_m3_query_cache(cases: list[dict[str, Any]]) -> None:
    """Batch-encode every distinct query through BGEM3FlagModel once
    upfront and patch ``M3Encoder.encode`` to serve later single-query
    calls from this dict. Without batching, every per-case call in
    ``retrieve_candidates`` (line 445: ``encoder.encode([query])``) pays
    a multi-minute MPS round-trip cost per query — 221 cases would
    take >10h. Pre-encoding in one batch of len(cases) cuts that to a
    single ~9 min forward pass (same cost as the chunk-cache build).

    Behavior is purely cache-warming: the patched ``encode`` falls
    through to the underlying model for any query not in the cache
    (e.g., a third-party caller invoking the encoder), so production
    code paths are unaffected.
    """
    queries = [str(case.get("query") or "") for case in cases]
    if not queries:
        return
    from rag_m3 import M3Encoder, M3Output, get_m3_encoder

    encoder = get_m3_encoder()
    print(
        f"[measure][m3-prime] batch-encoding {len(queries)} queries via "
        "BGEM3FlagModel (one MPS round-trip)",
        flush=True,
    )
    t0 = time.perf_counter()
    bulk = encoder.encode(queries)
    print(
        f"[measure][m3-prime] batch encode done in "
        f"{time.perf_counter() - t0:.1f}s",
        flush=True,
    )
    cache: dict[str, M3Output] = {}
    for i, q in enumerate(queries):
        cache[q] = M3Output(
            dense=bulk.dense[i : i + 1],
            sparse=[bulk.sparse[i]] if i < len(bulk.sparse) else [],
            colbert=[bulk.colbert[i]] if i < len(bulk.colbert) else [],
            # Carry the query's own dequant scale (issue #1010). Dropping
            # it forced ``retrieve_candidates`` to read an empty
            # ``colbert_scales`` → q_scale=1.0 → int8 query colbert scored
            # without dequant (measurement contamination, issue #1012).
            colbert_scales=(
                [bulk.colbert_scales[i]]
                if i < len(bulk.colbert_scales)
                else []
            ),
        )
    original_encode = encoder.encode

    def cached_encode(texts: list[str]) -> M3Output:
        if len(texts) == 1 and texts[0] in cache:
            return cache[texts[0]]
        return original_encode(texts)

    # Attach the cache to the encoder instance so it survives across
    # variants in the same run (only m3 backend reads it).
    encoder.encode = cached_encode  # type: ignore[method-assign]


def _prime_m3_index_cache_and_colbert(index: dict[str, Any]) -> None:
    """Eagerly build ``_m3_cache`` then patch
    ``M3Encoder.colbert_score`` to do **one large matmul per unique query**
    (cached) instead of N per-chunk matmuls (where N = len(chunks)).
    Mathematically identical to the per-chunk path — colbert max-sim is
    decomposable per chunk because each chunk's column slice is
    independent. This was introduced after the retired low-chunk CSV fallback
    run exposed per-chunk Python-loop matmul overhead; the current measurement
    path rejects that insufficient corpus before execution and expects a
    kordoc-scale index.

    Cache lifetime: per-process. The score cache uses ``id(q_colbert)`` as
    the key — primed queries always return the same ndarray (from the
    cache_map in ``_prime_m3_query_cache``), so identity is stable.
    Chunk lookup uses ``id(d_colbert)`` against a one-time-built map; the
    ``rag_m3.compute_m3_index_cache`` cache.colbert list lives on
    ``index["_m3_cache"]`` and is never mutated post-build.
    """
    from rag_m3 import compute_m3_index_cache, get_m3_encoder

    encoder = get_m3_encoder()
    cache = index.get("_m3_cache")
    if cache is None:
        chunks = index.get("chunks") or []
        cache = compute_m3_index_cache(encoder, chunks)
        index["_m3_cache"] = cache
    chunk_colberts = list(cache.colbert)
    if not chunk_colberts:
        return
    chunk_sizes = [int(vec.shape[0]) for vec in chunk_colberts]
    total_tokens = sum(chunk_sizes)
    if total_tokens == 0:
        return
    # Per-chunk dequantization scale (issue #1010 int8 cache). Empty when
    # the cache is fp16/fp32 → default 1.0 per chunk so the fast-path
    # math collapses to the unquantized case. Built here once so the
    # batched matmul below can apply the same dequant the per-chunk
    # ``M3Encoder.colbert_score`` does — otherwise int8 caches would be
    # scored on raw int8 dot products and the measurement is invalid.
    raw_scales = list(getattr(cache, "colbert_scales", []) or [])
    chunk_scales = [
        float(raw_scales[i]) if i < len(raw_scales) else 1.0
        for i in range(len(chunk_colberts))
    ]
    # Boundaries: cumulative chunk token offsets, length len(chunks)+1.
    boundaries = np.cumsum([0] + chunk_sizes, dtype=np.int64)
    # Concat all chunk colbert into (total_tokens, D); empty chunks
    # contribute zero rows so the slice [start:end] is empty and we
    # short-circuit max+sum to 0.0 below.
    big = np.concatenate(
        [v for v in chunk_colberts if v.shape[0] > 0], axis=0
    )
    # id(d_colbert) -> chunk index for O(1) lookup. Stable for the
    # lifetime of cache.colbert (a list of ndarrays that this function
    # owns from the build above).
    chunk_id_map: dict[int, int] = {
        id(vec): i for i, vec in enumerate(chunk_colberts)
    }
    # Per-query cache: id(q_colbert) -> precomputed per-chunk scores.
    score_cache: dict[int, np.ndarray] = {}

    original_colbert_score = type(encoder).colbert_score

    def patched_colbert_score(
        q_colbert: np.ndarray,
        d_colbert: np.ndarray,
        q_scale: float = 1.0,
        d_scale: float = 1.0,
    ) -> float:
        # Signature mirrors ``M3Encoder.colbert_score`` (issue #1010):
        # ``retrieve_candidates`` calls with ``q_scale=``/``d_scale=``
        # kwargs, so dropping them here raised ``TypeError`` on the first
        # primed scoring (issue #1012 regression). ``q_scale`` is the
        # query's dequant scale (constant per query → applied once at
        # cache-build time); the per-chunk ``d_scale`` is read from
        # ``chunk_scales`` so the cached row matches the d_colbert.
        if q_colbert.size == 0 or d_colbert.size == 0:
            return 0.0
        key = id(q_colbert)
        scores = score_cache.get(key)
        if scores is None:
            # Single big matmul: (T_q, D) @ (total_tokens, D).T
            # -> (T_q, total_tokens). Row-wise max per chunk slice
            # gives the colbert max-sim. Sum over query tokens then.
            # int8 cache: cast the (small) query to fp32 so the matmul
            # accumulates in float (numpy promotes the int8 ``big`` →
            # fp32), avoiding int8 overflow exactly like the per-chunk
            # scorer; then apply ``q_scale * chunk_scales[i]`` per chunk.
            if big.dtype == np.int8:
                sims = q_colbert.astype(np.float32) @ big.T
            else:
                sims = q_colbert @ big.T
            scores = np.zeros(len(chunk_colberts), dtype=np.float32)
            for i, (start, end) in enumerate(
                zip(boundaries[:-1], boundaries[1:])
            ):
                if start == end:
                    continue
                raw = float(np.sum(np.max(sims[:, int(start):int(end)], axis=1)))
                scores[i] = raw * q_scale * chunk_scales[i]
            score_cache[key] = scores
        idx = chunk_id_map.get(id(d_colbert))
        if idx is None:
            # Safety net: any d_colbert not in our cache falls through
            # to the original per-chunk matmul. Should never fire for
            # primed indexes (rag_retrieval reads cache.colbert by
            # chunk_idx, so the ndarray identity matches what we built).
            return original_colbert_score(
                q_colbert, d_colbert, q_scale=q_scale, d_scale=d_scale
            )
        return float(scores[idx])

    # Patch the static method on the class. The encoder is a process-
    # wide singleton (via get_m3_encoder), and the runner does only
    # measurement (no production retrieval reuses the patched encoder
    # in the same process), so leaving the patch in place is safe.
    type(encoder).colbert_score = staticmethod(patched_colbert_score)
    print(
        f"[measure][m3-prime] colbert batched: concat {len(chunk_colberts)} "
        f"chunks ({total_tokens} tokens, big.shape={big.shape}), "
        f"per-query matmul + O(1) per-chunk lookup",
        flush=True,
    )


def measure_variant(
    spec: VariantSpec,
    index: dict[str, Any],
    cases: list[dict[str, Any]],
    top_k: int,
    ks: list[int],
    warmup_n: int,
) -> dict[str, Any]:
    """Run ``cases`` through ``index`` for ``spec`` and return per-case +
    aggregate scores. Per-case rows preserve list order so paired CI in
    ``compute_deltas`` aligns across variants. The m3 variant builds the
    ``_m3_cache`` (sparse + colbert per chunk) on its first call — this
    cold-start is absorbed by warmup so latency stats stay honest.
    """
    print(f"[measure] {spec.name}: {len(cases)} cases (warmup {warmup_n})", flush=True)
    if spec.retrieval_backend == "m3":
        _prime_m3_query_cache(cases)
        _prime_m3_index_cache_and_colbert(index)
    for case in cases[:warmup_n]:
        run_single_case(index, case, spec, top_k)

    per_case_rows: list[dict[str, Any]] = []
    latency_vals: list[float] = []
    for idx, case in enumerate(cases, 1):
        qid = case.get("id") or case.get("qid") or f"?#{idx}"
        qt = case.get("query_type") or "unknown"
        gold_chunk_ids = derive_gold_chunk_ids(case, index)
        retrieved_chunk_ids, latency_ms = run_single_case(index, case, spec, top_k)
        latency_vals.append(latency_ms)
        row: dict[str, Any] = {
            "qid": anon_qid(qid),
            "query_type": qt,
            "categories": categories_from_case(case),
            "gold_chunk_n": len(gold_chunk_ids),
            "latency_ms": round(latency_ms, 3),
        }
        for k in ks:
            row[f"chunk_recall@{k}"] = chunk_recall_at_k(
                retrieved_chunk_ids, gold_chunk_ids, k
            )
        row["mrr"] = chunk_mrr(retrieved_chunk_ids, gold_chunk_ids)
        row["ndcg@10"] = chunk_ndcg_at_k(retrieved_chunk_ids, gold_chunk_ids, 10)
        per_case_rows.append(row)
        if idx % 50 == 0:
            print(f"[measure] {spec.name}: {idx}/{len(cases)}", flush=True)

    return {
        "variant": spec.name,
        "per_case": per_case_rows,
        "latency_ms": {
            "p50": round(statistics.median(latency_vals), 3) if latency_vals else None,
            "p95": (
                round(statistics.quantiles(latency_vals, n=20)[-1], 3)
                if len(latency_vals) > 1
                else (round(latency_vals[0], 3) if latency_vals else None)
            ),
            "mean": round(statistics.mean(latency_vals), 3) if latency_vals else None,
            "n": len(latency_vals),
        },
    }


def render_report(
    out_dir: Path,
    specs: list[dict[str, Any]],
    measurements: dict[str, dict[str, Any]],
    deltas: dict[str, dict[str, dict[str, dict[str, Any] | None]]],
    config: dict[str, Any],
) -> None:
    """Write REPORT.md (<=200 lines). ``deltas`` shape:
    ``{other_name: {metric: {category: ci}}}``.
    """
    baseline = config["baseline"]
    lines: list[str] = []
    lines.append(
        f"# Phase 3.5 retrieval-eval — m3 검색 모드(mode) ablation "
        f"(real100 n={config['num_cases']}, 의미 임베딩(semantic embeddings))"
    )
    lines.append("")
    lines.append(
        f"Run: `{config['run_id']}` · commit `{config['git_commit'][:10]}` · "
        f"index_dir=`{config['index_dir']}` · "
        f"eval_config=`{config['eval_config']}` · "
        f"seeds={config['seeds']} · top_k={config['top_k']} · ks={config['ks']}"
    )
    lines.append("")
    lines.append("## 변형(variants)")
    lines.append("")
    lines.append("| 변형 | backend | RRF k | 문서 | 청크 |")
    lines.append("|---|---|---|---|---|")
    for spec in specs:
        rrf = spec.get("rrf_k")
        rrf_str = str(rrf) if rrf is not None else "—"
        lines.append(
            f"| `{spec['name']}` | {spec['retrieval_backend']} | {rrf_str} | "
            f"{spec['num_documents']} | {spec['num_chunks']} |"
        )
    lines.append("")
    lines.append("## 지연시간(latency, ms)")
    lines.append("")
    lines.append("| 변형 | p50 | p95 | mean | n |")
    lines.append("|---|---|---|---|---|")
    for variant_name in [s["name"] for s in specs]:
        lat = measurements[variant_name]["latency_ms"]
        lines.append(
            f"| `{variant_name}` | {lat['p50']} | {lat['p95']} | {lat['mean']} | {lat['n']} |"
        )
    lines.append("")

    metrics_to_report = ["chunk_recall@5", "chunk_recall@10", "mrr", "ndcg@10"]
    categories = [
        "overall",
        "multi_hop",
        "distractor_heavy",
        "long_context",
        "no_answer",
        "ambiguous_query",
        "uncategorized",
    ]

    for metric in metrics_to_report:
        lines.append(f"## {metric}")
        lines.append("")
        header_cols = ["카테고리"] + [f"`{s['name']}`" for s in specs]
        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("|" + "|".join(["---"] * len(header_cols)) + "|")
        for category in categories:
            cells = [category]
            for spec in specs:
                cat_arg = None if category == "overall" else category
                cells.append(
                    _fmt_mean(measurements[spec["name"]]["per_case"], metric, cat_arg)
                )
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
        lines.append(f"### {metric} — `{baseline}` 대비 paired CI delta (seed 평균)")
        lines.append("")
        header_cols = ["카테고리"] + [
            f"`{s['name']}`" for s in specs if s["name"] != baseline
        ]
        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("|" + "|".join(["---"] * len(header_cols)) + "|")
        for category in categories:
            cells = [category]
            for spec in specs:
                if spec["name"] == baseline:
                    continue
                ci = deltas.get(spec["name"], {}).get(metric, {}).get(category)
                cells.append(_fmt_ci(ci))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    lines.append("## 카테고리별 winner")
    lines.append("")
    lines.append(
        f"winner = `chunk_recall@10` 평균이 가장 높으면서 `{baseline}` 대비 paired CI "
        f"가 완전히 0 위인 변형. \"유의하지 않음\" = 어떤 변형의 CI 도 0 을 넘지 못함 "
        f"(절대 규칙 #5)."
    )
    lines.append("")
    lines.append("| 카테고리 | winner | 평균 recall@10 | " + f"`{baseline}` 대비 delta CI |")
    lines.append("|---|---|---|---|")
    for category in categories:
        winner = "유의하지 않음"
        winner_mean: float | None = None
        winner_ci: dict[str, Any] | None = None
        for spec in specs:
            if spec["name"] == baseline:
                continue
            ci = deltas.get(spec["name"], {}).get("chunk_recall@10", {}).get(category)
            if ci is None:
                continue
            if ci["ci_lo"] > 0 and (winner_mean is None or ci["mean_other"] > winner_mean):
                winner = spec["name"]
                winner_mean = ci["mean_other"]
                winner_ci = ci
        mean_str = f"{winner_mean:.3f}" if winner_mean is not None else "—"
        ci_str = _fmt_ci(winner_ci) if winner_ci is not None else "—"
        lines.append(f"| {category} | `{winner}` | {mean_str} | {ci_str} |")
    lines.append("")
    lines.append("## 비고(notes)")
    lines.append("")
    lines.append(
        "* Planner-bypass: 전체 query 를 유일한 sub-query 로, identity expansion, "
        "rerank 없음, `metadata_first=False` — 검색 모드 효과를 expansion / rerank / "
        "metadata-filter 효과로부터 격리한다 (Phase 3 과 동일 규율)."
    )
    lines.append(
        "* 3 변형 모두 `data/index/real100_m3`(BGE-M3 1024-dim dense)를 공유한다. "
        "`hybrid_bm25_k60_m3` 는 index dict 에 lazy-build 된 BM25 를 쓰고; `m3` 는 첫 "
        "호출 시 `index['_m3_cache']`(청크별 sparse + colbert, ADR 0025 spike-mode 라 "
        "in-memory only, 디스크 미persist)를 채운다. `--warmup` 이 ~2 분 캐시 "
        "cold-start 를 흡수하므로 케이스별 지연시간은 캐시 hit 비용을 반영한다."
    )
    lines.append(
        "* m3 의 RRF dense 채널은 인덱스의 기존 dense 채널을 재사용한다"
        "(`rag_retrieval.py:449-454`) — 이 run 에서는 그것이 BGE-M3 dense 다(인덱스가 "
        "`--model BAAI/bge-m3` 로 빌드됨), 따라서 3 채널 모두 BGE-M3(dense + sparse + "
        "colbert)다. hashing 으로 빌드된 인덱스에서는 dense 채널이 hashing 이라 임베딩 "
        "패밀리가 섞이게 된다."
    )
    lines.append(
        "* `chunk_recall@k` 는 `expected_terms` / `expected_doc_ids` 가 없는 케이스"
        "(예: abstention(보류))에서 None 이다 — 변형 간 케이스 정렬을 보존하기 위해 "
        "pairwise 에서 제외된다."
    )
    lines.append(
        "* Seed 는 bootstrap RNG 만 구동한다; retrieval 자체는 동일 "
        "query+index+backend+rrf_k 에 대해 결정적(deterministic)이다 "
        "(dense + BM25 + m3 sparse/colbert)."
    )
    lines.append(
        "* 카테고리 버킷팅은 `hardcase_categories`(의미 난이도 태그)를 쓴다. 멀티태그 "
        "케이스는 여러 버킷에 나타나므로 카테고리별 카운트는 겹치고 paired CI 가 "
        "케이스를 공유한다."
    )
    lines.append(
        f"* `{baseline}` 이 delta baseline 인 이유: Phase 3.5 는 **의미 임베딩 위에서 "
        "multi-channel vs single-channel** 을 격리하기 때문이다. 0 위 delta 는 "
        "multi-channel 변형(hybrid 또는 m3)에, 0 아래는 dense 단독에 유리하다."
    )
    lines.append(
        "* **Phase 3 cross-ref + runner 버그 retraction(철회)**: "
        "`reports/retrieval/phase3_mode_20260518T032404Z/` 는 3 개 "
        "`hybrid_bm25_k{30,60,100}` 변형이 byte-identical 이라 보고하고 이를 BM25 채널 "
        "dominance 로 귀인했다. **그 결론은 틀렸다**: Phase 3 runner 가 "
        "`retrieve_candidates`(후보 생성만)를 호출하고 2단계 "
        "`apply_fusion_and_reranking`(RRF fusion + 최종 top-k)를 누락했다. hybrid + m3 "
        "backend 에서 `retrieve_candidates` 는 `score=0.0` placeholder 를 반환하므로 "
        "케이스별 순위가 chunk_id 삽입 순서로 붕괴해 모든 k 값이 byte-identical 이 됐다. "
        "Phase 3.5 는 wire-up 을 고친다(`run_single_case` 에 두 호출 모두); hashing "
        "인덱스 재측정은 후속이다. Cross-backend delta(hashing `dense` vs `dense_m3`)는 "
        "임베딩 패밀리 교체로 confounded 되어 산출하지 않는다."
    )
    lines.append(
        "* **청크 수 caveat**: BGE-M3 인덱스가 HWP/PDF 모두에 `data_list_csv_text` "
        "loader 를 썼고(ADR 0049 graceful fallback), doc 당 ~9 청크였다(`kordoc` 전체 "
        "추출의 real100 ~264 청크/doc 대비). 26k kordoc 청크를 BGE-M3 로 MPS 에서 "
        "재임베딩하면 >2h 걸린다(배치별 GPU dispatch overhead); csv_text fallback 은 "
        "build 를 20 분 미만으로 유지하면서 Phase 3.5 내부 paired CI 주장을 보존한다. "
        "이 인덱스의 절대 `chunk_recall@k` 는 Phase 3 의 kordoc 빌드 수치와 직접 비교 "
        "불가 — Phase 3.5 내부 delta 만 비교 가능하다."
    )
    lines.append(
        "* **Runner 측 m3 batching (측정 전용 최적화)**: 이 인덱스에서 query 별 colbert "
        "max-sim 이 지배적 비용이다(청크별 Python-loop matmul × ~900 청크 × 최적화 전 "
        "경로에서 관측된 ~50s/query). runner 는 모든 청크 colbert 벡터를 하나의 "
        "`(Σ T_d, 1024)` 행렬로 concat 해 unique query 당 **1회** matmul 후 행별 "
        "max+sum 을 위해 컬럼을 청크별로 다시 split 한다. 청크별 경로와 수학적으로 "
        "동일하나(각 청크의 컬럼 슬라이스는 독립) ~100× 빠르다. 패치는 runner 에 "
        "있다(`_prime_m3_index_cache_and_colbert`); `rag_m3.py` / `rag_retrieval.py` "
        "는 미변경."
    )
    lines.append(
        "* **범위 외**: 채널별 m3 ablation(sparse-only, colbert-only — ADR 0010 "
        "'Alternatives considered' 참조); hybrid_bm25 의 RRF-k sweep(Phase 3 이 이미 "
        "hashing 에서 k=30/60/100 byte-identical 을 보임); 위에 stack 된 cross-encoder "
        "rerank(Phase 4)."
    )
    lines.append(
        "* ADR cross-ref: ADR 0010(BGE-M3 multi-channel deferred), ADR 0021"
        "(m3_full 분석 행), ADR 0032(torch>=2.6 unblock — 본 측정을 원래 미뤘던 install "
        "blocker 를 해소)."
    )
    if config.get("reaggregate_source"):
        lines.append(
            "* 이 리포트는 `--reaggregate` 로 "
            f"`{config['reaggregate_source']}` 로부터 재생성됨 — 카테고리는 "
            "`hardcase_categories` 에서 재유도; `raw_results.json` 의 retrieval "
            "점수는 주입된 `categories` 필드를 제외하면 byte-for-byte 불변."
        )

    report_path = out_dir / "REPORT.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[report] wrote {report_path} ({len(lines)} lines)", flush=True)


def _git_state() -> tuple[str, bool]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        )
        return commit, dirty
    except Exception:
        return "unknown", True


def _resolve_specs(args: argparse.Namespace) -> list[VariantSpec]:
    index_dir = Path(args.index_dir_m3)
    specs = [
        VariantSpec(name="dense_m3", retrieval_backend="dense", rrf_k=None, index_dir=index_dir),
        VariantSpec(
            name="hybrid_bm25_k60_m3",
            retrieval_backend="hybrid",
            rrf_k=60,
            index_dir=index_dir,
        ),
        VariantSpec(name="m3", retrieval_backend="m3", rrf_k=None, index_dir=index_dir),
    ]
    # Phase 3.5 closeout (2026-05-19): BIDMATE_SKIP_M3_VARIANT env var to skip
    # the m3 (3-way RRF) variant. On CPU mode the m3 cache build (sparse +
    # colbert encoding of 26k chunks) takes 20h+ (observed 12 min/batch x 104
    # batches). MPS attempts hung in earlier closeout runs. Setting this env
    # var measures only dense_m3 + hybrid_bm25_k60_m3 (Phase 3 BM25 question
    # on semantic embeddings) while m3 multi-channel question stays deferred.
    if os.environ.get("BIDMATE_SKIP_M3_VARIANT", "").strip() == "1":
        specs = [s for s in specs if s.name != "m3"]
    return specs


def _spec_meta(
    spec: VariantSpec, payload: dict[str, Any]
) -> dict[str, Any]:
    return {
        "name": spec.name,
        "retrieval_backend": spec.retrieval_backend,
        "rrf_k": spec.rrf_k,
        "index_dir": str(spec.index_dir),
        "num_documents": len(payload.get("documents", [])),
        "num_chunks": len(payload.get("chunks", [])),
    }


def _run_reaggregate(
    args: argparse.Namespace,
    out_dir: Path,
    seeds: list[int],
    ks: list[int],
) -> int:
    """Re-derive ``row['categories']`` from ``hardcase_categories`` and
    regenerate deltas + REPORT.md without re-running retrieval. Useful
    when the categorization schema changes between runs but raw scores
    are still trustworthy.
    """
    raw_path = Path(args.reaggregate)
    if not raw_path.exists():
        print(f"[ERROR] --reaggregate path not found: {raw_path}", file=sys.stderr)
        return 2
    print(f"[reaggregate] loading {raw_path}", flush=True)
    measurements = json.loads(raw_path.read_text(encoding="utf-8"))

    cfg = yaml.safe_load(Path(args.eval_config).read_text(encoding="utf-8"))
    cases = cfg.get("cases", []) or []
    cases_by_qid = {}
    for _c in cases:
        _cid = str(_c.get("id"))
        # Tolerant join: committed real-eval artifacts carry anonymized
        # qids (anon_qid maps Hangul ids -> real_<hash>); synthetic /
        # legacy files carry the raw id. Map both so re-aggregation
        # works regardless of which the persisted row used.
        cases_by_qid[_cid] = _c
        cases_by_qid[anon_qid(_cid)] = _c

    for variant_name, m in measurements.items():
        rows = m.get("per_case", []) or []
        untagged = 0
        for row in rows:
            case = cases_by_qid.get(str(row.get("qid")))
            tags = categories_from_case(case or {})
            row["categories"] = tags
            if tags == ["uncategorized"]:
                untagged += 1
        print(
            f"[reaggregate] {variant_name}: {len(rows)} rows, {untagged} uncategorized",
            flush=True,
        )

    specs_path = raw_path.parent / "mode_specs.json"
    if not specs_path.exists():
        print(
            f"[ERROR] mode_specs.json not found beside raw: {specs_path}",
            file=sys.stderr,
        )
        return 2
    spec_metas = json.loads(specs_path.read_text(encoding="utf-8"))
    (out_dir / "mode_specs.json").write_text(
        json.dumps(spec_metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "raw_results.json").write_text(
        json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[phase] deltas (reaggregate)", flush=True)
    metrics_to_delta = [f"chunk_recall@{k}" for k in ks] + ["mrr", "ndcg@10"]
    deltas: dict[str, dict[str, dict[str, dict[str, Any] | None]]] = {}
    baseline = args.baseline
    baseline_rows = measurements[baseline]["per_case"]
    for variant_name in measurements:
        if variant_name == baseline:
            continue
        deltas[variant_name] = {
            metric: compute_deltas(
                baseline_rows, measurements[variant_name]["per_case"], metric, seeds
            )
            for metric in metrics_to_delta
        }
    (out_dir / "deltas.json").write_text(
        json.dumps(deltas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    git_commit, git_dirty = _git_state()
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        + "-phase35-m3-reaggregate"
    )
    baseline_spec = next(
        (s for s in spec_metas if s.get("name") == baseline),
        {"index_dir": "unknown"},
    )
    config = {
        "run_id": run_id,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "index_dir": baseline_spec.get("index_dir", "unknown"),
        "eval_config": args.eval_config,
        "seeds": seeds,
        "top_k": args.top_k,
        "ks": ks,
        "num_cases": len(baseline_rows),
        "baseline": baseline,
        "reaggregate_source": str(raw_path),
    }
    print("[phase] render (reaggregate)", flush=True)
    render_report(out_dir, spec_metas, measurements, deltas, config)
    print(f"[done] output_dir={out_dir}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index_dir_m3",
        default="data/index/real100_m3",
        help="Shared semantic index for all 3 variants (default: data/index/real100_m3).",
    )
    parser.add_argument("--eval_config", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument(
        "--reaggregate",
        default=None,
        help=(
            "Path to an existing raw_results.json. Skips measurement, "
            "re-derives row['categories'] from hardcase_categories in --eval_config, "
            "and regenerates deltas + REPORT.md into --output_dir. "
            "Companion mode_specs.json must sit beside raw_results.json."
        ),
    )
    parser.add_argument("--seeds", default="17,23,29")
    parser.add_argument("--top_k", type=int, default=20)
    parser.add_argument("--ks", default="5,10")
    parser.add_argument(
        "--warmup",
        type=int,
        default=3,
        help=(
            "Per-variant warmup cases before latency measurement. The m3 variant's "
            "first call builds `_m3_cache` (~2 min cold-start for 26k chunks); "
            "default 3 absorbs this so latency stats reflect cache-hit cost."
        ),
    )
    parser.add_argument(
        "--cases_subset_n",
        type=int,
        default=None,
        help="Truncate to first N cases (for pre-flight dry-runs).",
    )
    parser.add_argument(
        "--baseline",
        default="dense_m3",
        choices=["dense_m3", "hybrid_bm25_k60_m3", "m3"],
        help="Baseline variant for paired CI deltas (default: dense_m3).",
    )
    args = parser.parse_args(argv)

    seeds = [int(x) for x in args.seeds.split(",")]
    ks = [int(x) for x in args.ks.split(",")]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.reaggregate:
        return _run_reaggregate(args, out_dir, seeds, ks)

    specs = _resolve_specs(args)

    print("[phase] measure", flush=True)
    cfg = yaml.safe_load(Path(args.eval_config).read_text(encoding="utf-8"))
    cases = cfg.get("cases", []) or []
    if args.cases_subset_n is not None:
        cases = cases[: args.cases_subset_n]
        print(f"[measure] truncated to first {len(cases)} cases", flush=True)
    print(f"[measure] {len(cases)} cases", flush=True)

    # All 3 variants share the same semantic index; load once and reuse
    # so the m3 cache populated by the first m3 call (during warmup) is
    # available for the variant's measurement loop. dense_m3 and
    # hybrid_bm25_k60_m3 never trigger _m3_cache compute (they take the
    # dense / hybrid branches of retrieve_candidates).
    print(f"[measure] loading shared semantic index from {args.index_dir_m3}", flush=True)
    index = load_index(Path(args.index_dir_m3))
    try:
        guard_private_real100_chunk_count(index, Path(args.index_dir_m3))
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    spec_metas = [_spec_meta(spec, index) for spec in specs]
    (out_dir / "mode_specs.json").write_text(
        json.dumps(spec_metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    measurements: dict[str, dict[str, Any]] = {}
    for spec in specs:
        measurements[spec.name] = measure_variant(
            spec, index, cases, args.top_k, ks, args.warmup
        )

    raw_path = out_dir / "raw_results.json"
    raw_path.write_text(
        json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[measure] wrote {raw_path}", flush=True)

    print("[phase] deltas", flush=True)
    metrics_to_delta = [f"chunk_recall@{k}" for k in ks] + ["mrr", "ndcg@10"]
    deltas: dict[str, dict[str, dict[str, dict[str, Any] | None]]] = {}
    baseline = args.baseline
    baseline_rows = measurements[baseline]["per_case"]
    for spec in specs:
        if spec.name == baseline:
            continue
        deltas[spec.name] = {
            metric: compute_deltas(
                baseline_rows, measurements[spec.name]["per_case"], metric, seeds
            )
            for metric in metrics_to_delta
        }
    (out_dir / "deltas.json").write_text(
        json.dumps(deltas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    git_commit, git_dirty = _git_state()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M") + "-phase35-m3"
    config = {
        "run_id": run_id,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "index_dir": str(specs[0].index_dir),
        "eval_config": args.eval_config,
        "seeds": seeds,
        "top_k": args.top_k,
        "ks": ks,
        "num_cases": len(cases),
        "baseline": baseline,
    }

    print("[phase] render", flush=True)
    render_report(out_dir, spec_metas, measurements, deltas, config)
    print(f"[done] output_dir={out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
