"""Request schema for the API demo.

The response is left as the raw ``run_rag_query`` dict so the API output
preserves the repo's grounded answer / citation contract verbatim. If
the underlying schema evolves, the API surface evolves with it without
a parallel pydantic model to drift out of sync.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Request body for ``POST /query``.

    Only ``query`` is required. Optional fields mirror the CLI flags of
    :mod:`app` so a reviewer can switch pipelines / retrieval modes from
    the HTTP surface without rebuilding anything.
    """

    query: str = Field(..., min_length=1, description="User query string.")
    pipeline: str | None = Field(
        default=None,
        description=(
            "Named RAG pipeline preset (e.g. 'naive_baseline', 'agentic_full'). "
            "Defaults to the API's configured default pipeline."
        ),
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        description="Override retrieval top-k.",
    )
    context_entities: list[str] | None = Field(
        default=None,
        description="Entities to carry across turns for follow-up queries.",
    )
    retrieval_mode: Literal["flat", "hierarchical"] | None = Field(
        default=None,
        description="Override the pipeline retrieval mode.",
    )
    conversation_state: dict | None = Field(
        default=None,
        description=(
            "Optional prior conversation state echoed back from a previous "
            "response. Pass this through unchanged for multi-turn flows."
        ),
    )
