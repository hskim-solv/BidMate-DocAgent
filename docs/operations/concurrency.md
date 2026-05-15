# Concurrency contract

> Issue #868 (F3) — what callers of `run_rag_query` may assume when multiple
> threads (FastAPI workers, batch eval drivers, notebooks) hit the same
> in-memory index dict.

## Contract

`run_rag_query(index, query, ...)` is **safe to call concurrently from
multiple threads against the same `index` dict**, with one invariant:
all concurrent callers receive byte-identical evidence rankings
(`(chunk_id, score)` pairs in `evidence` / `citations`) regardless of
scheduling order.

This is enforced by [`tests/test_concurrency_regression.py`](../../tests/test_concurrency_regression.py)
(8 threads × 5 queries × 4 reps for both `naive_baseline` and
`agentic_full`, plus a first-touch BM25 cache race with 16 threads).

## What this does *not* promise

* **Throughput.** The pipeline is CPU-bound and holds the GIL through
  embedding + BM25 scoring. Two threads do not give 2× QPS — they share
  one core. Use a process pool (uvicorn workers, gunicorn) for parallel
  serving, threads only to overlap I/O with retrieval.
* **Concurrent index mutation.** `build_index_payload` /
  `write_index` are *not* safe to call while queries are in flight on
  the same dict. Treat the index as read-only after build.
* **External resources.** Qdrant adapter (issue #832,
  [`docs/operations/qdrant-integration.md`](qdrant-integration.md))
  delegates concurrency to the Qdrant server itself.

## Race-prone surfaces (documented, not bugs)

These caches are populated lazily and *can* be touched by two threads
simultaneously. They are safe today because every winning write
produces an equivalent value:

* **`get_or_build_bm25`** ([`rag_retrieval.py:685`](../../rag_retrieval.py))
  — `dict.setdefault` pattern. Cache key is
  `(stopword_profile, tokenizer, schema_version, chunk_count)`
  (issue #833). Two threads on a cache-miss path both build a
  `BM25Okapi` from the same `chunks`; the last writer wins, but
  `BM25Okapi(...)` is deterministic given the same input, so the
  surviving entry produces identical scores.
* **`MODEL_CACHE`** ([`rag_embedding.py`](../../rag_embedding.py)) —
  keyed by `(model, normalize, device)`. SentenceTransformer cold-load
  is >5s; concurrent first-touch wastes work (both threads load) but
  the resulting weights are deterministic and the dict assignment is
  GIL-atomic.
* **`_DONUT_MODEL_CACHE`** ([`visual_ingestion.py`](../../visual_ingestion.py))
  — same shape as `MODEL_CACHE`, only touched during ingestion (not
  during query), so it does not interact with `run_rag_query` at all.

If a future PR introduces a lazy cache whose value is *not*
deterministic across reloads (e.g. a learned reranker with stochastic
init), it MUST add explicit locking or pre-build the cache at index
load time. The regression test will catch any drift that slips
through.

## Why threading (and not just multiprocessing)

The API serves requests from a `ThreadPoolExecutor` underneath
`asyncio.to_thread` (issue #173 Stage 1, `arun_rag_query`). Without
this contract the async path would be racy under load — the regression
test is the durable proof that the seam holds.
