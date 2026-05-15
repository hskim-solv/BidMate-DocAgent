"""Concurrent-query determinism regression (issue #868, F3 of GEF loop).

``run_rag_query`` is called from FastAPI workers (``api/main.py``) and may
also be fanned out from notebooks / batch eval drivers. The retrieval path
mutates the index dict to install lazy caches:

* ``index["_bm25_by_profile"]`` — :func:`rag_retrieval.get_or_build_bm25`
  populates this on first BM25 build (issue #833 cache key includes
  ``schema_version`` + ``chunk_count`` so corpus identity changes
  invalidate, but two threads can still race on the *initial* build).
* ``MODEL_CACHE`` in :mod:`rag_embedding` — keyed by ``(model, normalize,
  device)``. ST cold-load is >5s, so concurrent callers will both attempt
  the load; ``dict[...] = ...`` last-write-wins, but the model is
  deterministic across loads so the *result* is unchanged.

The senior contract this test guards: **regardless of how many threads
enter ``run_rag_query`` concurrently against the same ``index`` dict,
they MUST all return byte-identical evidence rankings + scores.** A
ranking drift under contention would be a silent correctness bug —
``naive_baseline`` golden (ADR 0001) catches single-threaded drift, this
catches multi-threaded drift.

We use the ``hashing`` embedding backend so the test is deterministic
across machines and does not need a 500 MB ST model download in CI.
"""
from __future__ import annotations

import concurrent.futures
from pathlib import Path

import pytest

from rag_core import run_rag_query


ROOT_DIR = Path(__file__).resolve().parents[1]


QUERIES = [
    "기관 A의 보안 통제 요구사항은?",
    "기관 C의 챗봇 응답 시간 목표는?",
    "기관 B의 개인정보 보안 요구사항은?",
    "공통 제출조건에서 모든 제안사가 제출해야 하는 것은?",
    "기관 A와 기관 B의 보안 요구사항 차이는?",
]


def _ranking_signature(result: dict) -> tuple[tuple[str, float], ...]:
    """Reduce a run_rag_query result to its deterministic ranking fingerprint.

    We compare ``(chunk_id, score)`` pairs on ``evidence`` / ``citations``
    — wall-clock fields (``diagnostics.latency_ms``, ``stage_latency``)
    legitimately differ between runs and must be excluded.
    """
    citations = result.get("citations") or result.get("evidence") or []
    return tuple(
        (c.get("chunk_id"), c.get("score")) for c in citations
    )


@pytest.fixture(scope="module")
def baseline_signatures(shared_raw_index) -> dict[tuple[str, str], tuple]:
    """Serial-execution baseline — every concurrent run must match this."""
    baseline: dict[tuple[str, str], tuple] = {}
    for pipeline in ("naive_baseline", "agentic_full"):
        for query in QUERIES:
            result = run_rag_query(shared_raw_index, query, pipeline=pipeline)
            baseline[(pipeline, query)] = _ranking_signature(result)
    return baseline


@pytest.mark.parametrize("pipeline", ["naive_baseline", "agentic_full"])
def test_concurrent_queries_match_serial_baseline(
    shared_raw_index, baseline_signatures, pipeline
):
    """8 threads × 5 queries × 4 reps must all match the serial baseline.

    Failure modes this catches:
      * BM25 cache corruption (two threads racing on initial build —
        if one writes a partially-tokenized BM25Okapi, downstream
        scores drift)
      * MODEL_CACHE clobber (deterministic by construction with the
        hashing backend — no cache writes — but parametrized over
        ``agentic_full`` exercises rerank/verifier surfaces too)
      * Any future shared-dict mutation introduced into retrieval /
        verifier / answer that breaks read-isolation
    """
    expected = {q: baseline_signatures[(pipeline, q)] for q in QUERIES}

    def _run(query: str) -> tuple[str, tuple]:
        result = run_rag_query(shared_raw_index, query, pipeline=pipeline)
        return query, _ranking_signature(result)

    futures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for _ in range(4):
            for query in QUERIES:
                futures.append(ex.submit(_run, query))
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    for query, signature in results:
        assert signature == expected[query], (
            f"concurrent ranking drift under pipeline={pipeline!r} "
            f"for query {query!r}:\n"
            f"  serial:     {expected[query]}\n"
            f"  concurrent: {signature}\n"
            "Two threads likely raced on a lazy-built cache "
            "(see rag_retrieval.get_or_build_bm25 / "
            "rag_embedding.MODEL_CACHE)."
        )


def test_bm25_cache_stable_under_concurrent_first_touch(shared_raw_index):
    """Drop the BM25 cache, then race 16 threads through retrieval.

    Targets the ``get_or_build_bm25`` race specifically: by deleting
    ``index["_bm25_by_profile"]`` we force every thread to enter the
    "first build" branch concurrently. The contract: regardless of
    which thread wins the ``dict.setdefault``, the final cache state
    must be a consistent ``(BM25Okapi, chunk_ids)`` tuple and all
    threads must observe the same ranking.
    """
    shared_raw_index.pop("_bm25_by_profile", None)
    shared_raw_index.pop("_bm25", None)
    shared_raw_index.pop("_bm25_chunk_ids", None)

    query = "기관 A의 보안 통제 요구사항은?"

    def _run() -> tuple:
        return _ranking_signature(
            run_rag_query(shared_raw_index, query, pipeline="agentic_full")
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        signatures = list(ex.map(lambda _: _run(), range(16)))

    first = signatures[0]
    for i, sig in enumerate(signatures[1:], start=1):
        assert sig == first, (
            f"BM25 cache race produced divergent rankings on thread #{i}:\n"
            f"  thread 0:  {first}\n"
            f"  thread {i}: {sig}\n"
            "get_or_build_bm25's setdefault is not preserving ranking "
            "invariance under concurrent first-touch."
        )
