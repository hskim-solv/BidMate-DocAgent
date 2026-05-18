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
  ``NOT SIGNIFICANT`` (CI crosses 0) per absolute rule #5

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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

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
    categories_from_case,
    compute_deltas,
)


@dataclass(frozen=True)
class VariantSpec:
    name: str
    retrieval_backend: str  # "dense" | "hybrid" | "m3"
    rrf_k: int | None       # 60 for hybrid_bm25_k60_m3; None for dense_m3 + m3
    index_dir: Path         # 3 entries share data/index/real100_m3


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
    independent. For the real100_m3 csv_text-fallback index (898 chunks ×
    long avg tokens/chunk), per-chunk Python-loop matmul dominates wall
    time (>50s/query observed on PID 25363); batched matmul drops the m3
    phase from ~3h to <10min on the same MPS box.

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
        q_colbert: np.ndarray, d_colbert: np.ndarray
    ) -> float:
        if q_colbert.size == 0 or d_colbert.size == 0:
            return 0.0
        key = id(q_colbert)
        scores = score_cache.get(key)
        if scores is None:
            # Single big matmul: (T_q, D) @ (total_tokens, D).T
            # -> (T_q, total_tokens). Row-wise max per chunk slice
            # gives the colbert max-sim. Sum over query tokens then.
            sims = q_colbert @ big.T
            scores = np.zeros(len(chunk_colberts), dtype=np.float32)
            for i, (start, end) in enumerate(
                zip(boundaries[:-1], boundaries[1:])
            ):
                if start == end:
                    continue
                scores[i] = float(np.sum(np.max(sims[:, int(start):int(end)], axis=1)))
            score_cache[key] = scores
        idx = chunk_id_map.get(id(d_colbert))
        if idx is None:
            # Safety net: any d_colbert not in our cache falls through
            # to the original per-chunk matmul. Should never fire for
            # primed indexes (rag_retrieval reads cache.colbert by
            # chunk_idx, so the ndarray identity matches what we built).
            return original_colbert_score(q_colbert, d_colbert)
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
            "qid": qid,
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
        f"# Phase 3.5 retrieval-eval — m3 mode ablation "
        f"(real100 n={config['num_cases']}, semantic embeddings)"
    )
    lines.append("")
    lines.append(
        f"Run: `{config['run_id']}` · commit `{config['git_commit'][:10]}` · "
        f"index_dir=`{config['index_dir']}` · "
        f"eval_config=`{config['eval_config']}` · "
        f"seeds={config['seeds']} · top_k={config['top_k']} · ks={config['ks']}"
    )
    lines.append("")
    lines.append("## Variants")
    lines.append("")
    lines.append("| Variant | Backend | RRF k | Docs | Chunks |")
    lines.append("|---|---|---|---|---|")
    for spec in specs:
        rrf = spec.get("rrf_k")
        rrf_str = str(rrf) if rrf is not None else "—"
        lines.append(
            f"| `{spec['name']}` | {spec['retrieval_backend']} | {rrf_str} | "
            f"{spec['num_documents']} | {spec['num_chunks']} |"
        )
    lines.append("")
    lines.append("## Latency (ms)")
    lines.append("")
    lines.append("| Variant | p50 | p95 | mean | n |")
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
        header_cols = ["Category"] + [f"`{s['name']}`" for s in specs]
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
        lines.append(f"### {metric} — paired CI delta vs `{baseline}` (seed-averaged)")
        lines.append("")
        header_cols = ["Category"] + [
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

    lines.append("## Per-category winner")
    lines.append("")
    lines.append(
        f"Winner = variant with highest `chunk_recall@10` mean AND paired CI vs "
        f"`{baseline}` fully above 0. \"NOT SIGNIFICANT\" = no variant's CI clears 0 "
        f"(absolute rule #5)."
    )
    lines.append("")
    lines.append("| Category | Winner | Mean recall@10 | Delta CI vs " + f"`{baseline}` |")
    lines.append("|---|---|---|---|")
    for category in categories:
        winner = "NOT SIGNIFICANT"
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
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "* Planner-bypass: full query as the only sub-query, identity expansion, "
        "no rerank, `metadata_first=False` — isolates retrieval-mode impact from "
        "expansion / rerank / metadata-filter effects (same discipline as Phase 3)."
    )
    lines.append(
        "* All 3 variants share `data/index/real100_m3` (BGE-M3 1024-dim dense). "
        "`hybrid_bm25_k60_m3` uses BM25 lazy-built on the index dict; `m3` populates "
        "`index['_m3_cache']` (sparse + colbert per chunk, in-memory only per ADR 0025 "
        "spike-mode, no disk persist) on its first call. `--warmup` absorbs the "
        "~2 min cache cold-start so per-case latency reflects cache-hit cost."
    )
    lines.append(
        "* m3's RRF dense channel reuses the index's existing dense channel "
        "(`rag_retrieval.py:449-454`) — for this run it IS the BGE-M3 dense (the "
        "index was built with `--model BAAI/bge-m3`), so the 3 channels are all "
        "BGE-M3 (dense + sparse + colbert). On hashing-built indexes the dense "
        "channel would be hashing, mixing embedding families."
    )
    lines.append(
        "* `chunk_recall@k` is None for cases without `expected_terms` / "
        "`expected_doc_ids` (e.g. abstention) — those are dropped pairwise to "
        "preserve case alignment between variants."
    )
    lines.append(
        "* Seeds drive only the bootstrap RNG; retrieval itself is deterministic "
        "for the same query+index+backend+rrf_k (dense + BM25 + m3 sparse/colbert)."
    )
    lines.append(
        "* Category bucketing uses `hardcase_categories` (semantic difficulty tags). "
        "Multi-tag cases appear in multiple buckets, so per-category counts overlap "
        "and per-category paired CIs share cases."
    )
    lines.append(
        f"* `{baseline}` is the delta baseline because Phase 3.5 isolates "
        "**multi-channel vs single-channel under semantic embeddings**. Deltas above "
        "0 favor the multi-channel variant (hybrid or m3); below 0 favor dense alone."
    )
    lines.append(
        "* **Phase 3 cross-ref + runner bug retraction**: "
        "`reports/retrieval/phase3_mode_20260518T032404Z/` reported all 3 "
        "`hybrid_bm25_k{30,60,100}` variants byte-identical and attributed it to "
        "BM25 channel dominance. **That conclusion was wrong**: the Phase 3 "
        "runner called `retrieve_candidates` (candidate generation only) without "
        "the second-stage `apply_fusion_and_reranking` (RRF fusion + final top-k). "
        "For hybrid + m3 backends `retrieve_candidates` returns `score=0.0` "
        "placeholders, so the per-case ranking collapsed to chunk_id insertion "
        "order — making every k value byte-identical. Phase 3.5 fixes the wire-up "
        "(both calls in `run_single_case`); the hashing-index re-run is a "
        "follow-up. Cross-backend delta math (hashing `dense` vs `dense_m3`) "
        "remains confounded by the embedding family swap and is NOT computed."
    )
    lines.append(
        "* **Chunk count caveat**: the BGE-M3 index used the `data_list_csv_text` "
        "loader for both HWP and PDF (per ADR 0049 graceful fallback), yielding "
        "~9 chunks/doc vs real100's ~264 chunks/doc with `kordoc` full extraction. "
        "Re-embedding 26k kordoc chunks with BGE-M3 on MPS would take >2h (per-batch "
        "GPU dispatch overhead); the csv_text fallback keeps the build under 20 min "
        "while preserving the within-Phase-3.5 paired CI claim. Absolute "
        "`chunk_recall@k` on this index is NOT directly comparable to Phase 3's "
        "kordoc-built numbers — only Phase 3.5 internal deltas are."
    )
    lines.append(
        "* **Runner-side m3 batching (measurement-only optimization)**: per-query "
        "colbert max-sim is the dominant cost on this index (per-chunk Python-loop "
        "matmul × ~900 chunks × ~50s/query observed on the unoptimized path). The "
        "runner concatenates all chunk colbert vectors into one `(Σ T_d, 1024)` "
        "matrix and does **one** matmul per unique query, then splits the columns "
        "back per chunk for the row-wise max+sum. Mathematically identical to the "
        "per-chunk path (each chunk's column slice is independent), but ~100× faster. "
        "The patch lives in the runner (`_prime_m3_index_cache_and_colbert`); "
        "`rag_m3.py` / `rag_retrieval.py` unchanged."
    )
    lines.append(
        "* **Out of scope**: per-channel m3 ablation (sparse-only, colbert-only — "
        "see ADR 0010 'Alternatives considered'); RRF-k sweep on hybrid_bm25 (Phase 3 "
        "already showed k=30/60/100 byte-identical on hashing); cross-encoder rerank "
        "stacked on top (Phase 4)."
    )
    lines.append(
        "* ADR cross-refs: ADR 0010 (BGE-M3 multi-channel deferred), ADR 0021 "
        "(m3_full analysis row), ADR 0032 (torch>=2.6 unblock — closes the install "
        "blocker that originally deferred this measurement)."
    )
    if config.get("reaggregate_source"):
        lines.append(
            "* This report was regenerated via `--reaggregate` from "
            f"`{config['reaggregate_source']}` — categorization re-derived from "
            "`hardcase_categories`; retrieval scores in `raw_results.json` are "
            "unchanged byte-for-byte modulo the injected `categories` field."
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
    return [
        VariantSpec(name="dense_m3", retrieval_backend="dense", rrf_k=None, index_dir=index_dir),
        VariantSpec(
            name="hybrid_bm25_k60_m3",
            retrieval_backend="hybrid",
            rrf_k=60,
            index_dir=index_dir,
        ),
        VariantSpec(name="m3", retrieval_backend="m3", rrf_k=None, index_dir=index_dir),
    ]


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
    cases_by_qid = {str(c.get("id")): c for c in cases}

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
