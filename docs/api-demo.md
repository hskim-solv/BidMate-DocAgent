# API demo (FastAPI + container)

This page documents the **reviewer-facing demo surface** added in
issue #75. It is intentionally separate from the CLI evaluation flow:

| Flow | Entry point | What it's for |
|---|---|---|
| **CLI eval** | `scripts/build_index.py`, `app.py`, `eval/run_eval.py` | Reproducible measurement, ablations, benchmark reports. Source of truth. |
| **API demo** | `api/main.py` (this doc) | Letting a reviewer poke the system over HTTP without stitching commands together. |

The API never builds an index itself; it loads one prepared on disk
and wraps `rag_core.run_rag_query` behind three small endpoints.

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Readiness probe. 200 once the index is loaded, 503 otherwise. Reports `chunk_count`, `doc_count`, `default_pipeline`. |
| `GET` | `/pipelines` | Lists pipeline presets accepted by `POST /query`, plus the configured default. |
| `POST` | `/query` | Runs one RAG query. Body matches the CLI flags in `app.py`. Response is the raw `run_rag_query` dict — same shape `outputs/answer.json` would have. |
| `GET` | `/docs` | FastAPI's built-in Swagger UI (auto-generated). |

### `POST /query` body

```json
{
  "query": "기관 A의 보안 통제 요구사항은?",
  "pipeline": "agentic_full",        // optional
  "top_k": 8,                         // optional
  "retrieval_mode": "flat",           // optional: "flat" | "hierarchical"
  "context_entities": ["기관 A"],    // optional, for follow-up turns
  "conversation_state": null          // optional, pass back the prior response's value
}
```

Only `query` is required. The response preserves the grounded
answer / citation contract — see `docs/answer-policy.md` and
`docs/citation-grounding-eval.md` for the schema specifics.

## Local startup (no Docker)

```bash
make index          # builds data/index from data/raw (one-time)
make api            # uvicorn on :8000 with --reload
```

Then:

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/query \
  -H 'content-type: application/json' \
  -d '{"query":"기관 A와 기관 B의 AI 요구사항 차이 알려줘"}'
```

## Container startup (single command)

```bash
make api-docker
# equivalent to:
#   docker build -t bidmate-demo .
#   docker run --rm -p 8000:8000 bidmate-demo
```

`docker-entrypoint.sh` checks for `data/index/index.json` inside the
container and builds it from `data/raw` on first start using the
hashing embedding backend (no network needed). Subsequent starts
reuse the existing index.

To persist the index across runs, mount a host volume:

```bash
docker run --rm -p 8000:8000 -v "$(pwd)/data/index:/app/data/index" bidmate-demo
```

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `BIDMATE_INDEX_DIR` | `data/index` (local), `/app/data/index` (container) | Where the API looks for `index.json`. |
| `BIDMATE_DEFAULT_PIPELINE` | `agentic_full` | Pipeline used when a request omits `"pipeline"`. Falls back to the CLI default if the name is not registered. |
| `BIDMATE_API_HOST` / `BIDMATE_API_PORT` | `0.0.0.0` / `8000` | Container entrypoint binding. |
| `EMBEDDING_BACKEND` | `hashing` (container) | Passed to `scripts/build_index.py` when the entrypoint auto-builds the index. |

## Expected artifacts

A successful demo run produces:

- A live HTTP server on `:8000` (`/health` returning 200).
- `data/index/index.json` if the container built one on first start.
- No `outputs/answer.json` is written — the API returns the answer
  inline. Use `make ask` / `app.py` for the file-emitting CLI flow.

## What this demo deliberately does **not** do

- No authentication, rate limiting, or persistence layer — out of
  scope for a reviewer-facing demo.
- No HTML UI — the OpenAPI Swagger page at `/docs` is enough.
- No multi-stage Docker build / image size optimization — tracked
  separately if it becomes a concern.
- The container does not run `make eval` or any benchmark. Those are
  CLI evaluation concerns and stay there.
