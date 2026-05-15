"""FastAPI demo surface around :func:`rag_core.run_rag_query`.

Goals (issue #75):
* Reviewers can start the demo with a documented local container flow.
* Health check and at least one representative query endpoint.
* API output preserves the repo's grounded answer / citation contract
  (we pass the raw ``run_rag_query`` dict through).
* CLI evaluation flow stays the source of truth — this module never
  builds an index itself; it only loads one prepared on disk.

Environment variables:
* ``BIDMATE_INDEX_DIR`` — directory containing ``index.json``.
  Defaults to ``data/index``.
* ``BIDMATE_DEFAULT_PIPELINE`` — pipeline name used when a request does
  not specify one. Defaults to ``agentic_full`` (the full demo
  pipeline), falling back to the CLI default if that name is not in the
  registry.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request

from bidmate_security import screen_query
from rag_core import (
    DEFAULT_CLI_PIPELINE_NAME,
    arun_rag_query,
    load_index,
    pipeline_cli_choices,
)

from .schemas import QueryRequest

logger = logging.getLogger("bidmate.api")

DEFAULT_INDEX_DIR = "data/index"
# ADR 0024 / PR-I (issue #405): API surface defaults to the
# `agentic_full_llm` preset (ADR 0011 additive LLM synthesis path). The
# *backend* default is still `BIDMATE_SYNTHESIS_BACKEND=stub` (ADR 0011)
# so CI / public reviewers see a deterministic response with the LLM
# preset selected; real LLM backends activate only when an operator
# sets `BIDMATE_SYNTHESIS_BACKEND=anthropic` (or `openai_compatible`).
# CLI (`app.py`) keeps `naive_baseline` per ADR 0001.
DEFAULT_API_PIPELINE = "agentic_full_llm"


def _resolve_default_pipeline() -> str:
    """Pick the default pipeline for unspecified requests.

    Prefers ``BIDMATE_DEFAULT_PIPELINE`` from the environment, then
    ``agentic_full_llm`` (ADR 0024), then the CLI default. The fallback
    chain keeps the API working even if the registry is reshuffled.
    """
    env = (os.environ.get("BIDMATE_DEFAULT_PIPELINE") or "").strip()
    choices = set(pipeline_cli_choices())
    for candidate in (env, DEFAULT_API_PIPELINE, DEFAULT_CLI_PIPELINE_NAME):
        if candidate and candidate in choices:
            return candidate
    return DEFAULT_CLI_PIPELINE_NAME


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the index once at startup and stash it on ``app.state``.

    Eager loading keeps per-request latency clean and makes ``/health``
    a meaningful readiness signal. If the index is missing we still
    start (so ``/health`` can report the failure) instead of crashing
    the worker.
    """
    index_dir = Path(os.environ.get("BIDMATE_INDEX_DIR") or DEFAULT_INDEX_DIR)
    app.state.index_dir = index_dir
    app.state.default_pipeline = _resolve_default_pipeline()
    app.state.index = None
    app.state.index_load_error = None
    try:
        app.state.index = load_index(index_dir)
        logger.info(
            "Loaded RAG index from %s (chunks=%d, default_pipeline=%s)",
            index_dir,
            len(app.state.index.get("chunks") or []),
            app.state.default_pipeline,
        )
    except Exception as exc:  # pragma: no cover - logged for operators
        app.state.index_load_error = str(exc)
        logger.exception("Failed to load RAG index from %s", index_dir)
    yield


app = FastAPI(
    title="BidMate-DocAgent demo API",
    description=(
        "Thin HTTP surface around the RAG pipeline. See docs/operations/api-demo.md "
        "for the local + container startup flow."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


def get_index(request: Request) -> dict[str, Any]:
    """Dependency that returns the loaded index or 503s."""
    index = getattr(request.app.state, "index", None)
    if index is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "index_not_loaded",
                "index_dir": str(getattr(request.app.state, "index_dir", "")),
                "load_error": getattr(request.app.state, "index_load_error", None),
                "hint": "Run scripts/build_index.py or restart with BIDMATE_INDEX_DIR set.",
            },
        )
    return index


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    """Readiness probe: 200 once the index is loaded, otherwise 503.

    The body is the same shape in both cases so operators can read the
    status without parsing the HTTP code.
    """
    state = request.app.state
    index = getattr(state, "index", None)
    payload: dict[str, Any] = {
        "status": "ok" if index is not None else "degraded",
        "index_dir": str(getattr(state, "index_dir", "")),
        "index_loaded": index is not None,
        "default_pipeline": getattr(state, "default_pipeline", DEFAULT_CLI_PIPELINE_NAME),
    }
    if index is not None:
        payload["chunk_count"] = len(index.get("chunks") or [])
        payload["doc_count"] = len({c.get("doc_id") for c in index.get("chunks") or []})
    else:
        payload["load_error"] = getattr(state, "index_load_error", None)
        raise HTTPException(status_code=503, detail=payload)
    return payload


@app.get("/pipelines")
def pipelines(request: Request) -> dict[str, Any]:
    """List pipeline presets accepted by ``POST /query``."""
    return {
        "default": getattr(request.app.state, "default_pipeline", DEFAULT_CLI_PIPELINE_NAME),
        "available": pipeline_cli_choices(),
    }


@app.post("/query")
async def query(
    body: QueryRequest,
    request: Request,
    index: dict[str, Any] = Depends(get_index),
) -> dict[str, Any]:
    """Run one RAG query and return the raw answer dict.

    The response shape is intentionally **not** wrapped in a pydantic
    model — it passes through whatever ``arun_rag_query`` returns so
    the API never drifts from the canonical answer / citation contract.
    ``arun_rag_query`` runs the sync RAG pipeline on a worker thread
    (``asyncio.to_thread``) so the event loop stays free for the next
    request (#173 Stage 1). Fan-out parallelism of comparison-query
    branches is Stage 2.
    """
    pipeline = body.pipeline or request.app.state.default_pipeline
    # Issue #455 / ADR 0028: screen the user query for prompt-injection
    # patterns before retrieval. Diagnostic-only — flagged queries still
    # run, but the diagnostic is attached to the response so downstream
    # consumers can log, alert, or block. The screen is regex-only,
    # never raises, and adds <100µs to request latency.
    injection_screen = screen_query(body.query)
    try:
        result = await arun_rag_query(
            index,
            body.query,
            pipeline=pipeline,
            top_k=body.top_k,
            context_entities=body.context_entities or [],
            retrieval_mode=body.retrieval_mode,
            conversation_state=body.conversation_state,
        )
    except Exception as exc:
        logger.exception("RAG query failed for query=%r pipeline=%r", body.query, pipeline)
        raise HTTPException(
            status_code=500,
            detail={"error": "rag_query_failed", "message": str(exc)},
        )
    # Attach the injection-screen result under diagnostics. ADR 0003's
    # answer-contract schema_version does NOT bump — adding a key under
    # `diagnostics` is contract-compatible per ADR 0011 / 0013 / 0015's
    # additive-key convention. If a future pipeline returns a result
    # without a `diagnostics` block, create one.
    diagnostics = result.get("diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
        result["diagnostics"] = diagnostics
    diagnostics["injection_screen"] = injection_screen
    return result
