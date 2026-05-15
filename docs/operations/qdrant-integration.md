# Qdrant integration

Production-server smoke for the `qdrant` index backend.  Pairs with [`rag_vector_store.QdrantVectorStore`](../../rag_vector_store.py) and the env-var routing added in PR #837.

## When to run

Use this surface when you need to confirm:

- A real (non-`:memory:`) Qdrant HTTP server is reachable from the BidMate process.
- Ranking parity holds between the in-memory backend and the network path (ADR 0001 baseline).
- A Qdrant Cloud / self-hosted deployment is ready to receive traffic from the production preset.

The default smoke (`make smoke`) does **not** start Qdrant.  CI does not run these tests either — they are opt-in to keep the synthetic eval delta and ADR 0001 baseline guard unaffected.

## Local workflow

```bash
make qdrant-up                      # docker compose up -d
make test-qdrant-integration        # pytest -m qdrant_integration
make qdrant-down                    # docker compose down -v
```

The container image is pinned in [`docker-compose.qdrant.yml`](../../docker-compose.qdrant.yml) (`qdrant/qdrant:v1.11.0`).  Do not move to `latest` — the in-memory ↔ HTTP parity tests assume an exact cosine top-k contract, and newer Qdrant builds can drift the ranking math (issue #176 Stage 2b covenant).

## Pointing at a different server

`BIDMATE_QDRANT_INTEGRATION_URL` overrides the default `http://localhost:6333` so the same suite can drive a Qdrant Cloud instance, a remote dev server, or a different local port:

```bash
BIDMATE_QDRANT_INTEGRATION_URL=https://your-cluster.qdrant.io:6333 \
    pytest tests/test_qdrant_integration.py -m qdrant_integration
```

The integration suite still uses `BIDMATE_INDEX_BACKEND=qdrant` + `BIDMATE_QDRANT_URL` internally (PR #837 contract); the override env var only chooses *which* server.  TLS / API-key auth is a follow-up (see ADR 0046 §"Out of scope" and the F4 capacity-bench backlog).

## What is tested

[`tests/test_qdrant_integration.py`](../../tests/test_qdrant_integration.py) covers, against a live server:

| Check | What it proves |
|-------|----------------|
| Build round-trip | Collection upsert with the expected dimension + point count |
| `get(idx)` parity | Stage 2a invariant: the matrix row, not a Qdrant fetch |
| `query` self-similarity | The query vector matches itself with cosine ≈ 1 |
| `query` ranking parity vs in-memory | ADR 0001 cosine top-k invariance through the HTTP path |
| `query_by_indices` local path | The matrix-dot shortcut, not a Qdrant round-trip |

Each test isolates the collection via `_drop_collection_if_exists` so back-to-back runs do not collide on point IDs.

## What is *not* tested here

- Concurrency / lock behaviour during index build — F3 backlog (issue TBD).
- 1k / 10k capacity benchmarks — F4 backlog.
- pgvector backend (ADR 0020 Stage 3).
- Authentication / TLS — production Qdrant Cloud config is a separate concern.

## Failure modes

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| All tests `SKIP` | Server not reachable | `make qdrant-up` and wait for the healthcheck |
| Skip with `connection refused` | Container port mapping mismatch | Inspect `docker compose -f docker-compose.qdrant.yml ps` |
| Parity test fails | Qdrant image drifted | Re-pin `docker-compose.qdrant.yml` to the previous known-good tag |
| `qdrant_client` import skipped | qdrant-client not installed | `pip install qdrant-client` (optional dep, not in `requirements.txt`) |
