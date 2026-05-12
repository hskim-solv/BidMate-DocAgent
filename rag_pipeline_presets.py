"""Pipeline preset registry for the BidMate RAG core.

Extracted from ``rag_core.py`` in issue #364 (PR-E, stage 1 of the
``rag_core.py`` decomposition epic — external senior review 2026-05
finding #3). This module is the **canonical home** for:

- The CLI / API default pipeline names (ADR 0001 reproducibility
  invariant for ``naive_baseline``; ADR 0011 for ``agentic_full_llm``).
- The static ``PIPELINE_PRESETS`` dict and its ``PIPELINE_ALIASES``.
- ``RRF_K`` / ``VALID_RRF_K_RANGE`` — the canonical RRF fusion default
  used both inside the preset dict and by hybrid retrieval functions in
  ``rag_core`` (which import them back).
- ``DEFAULT_COMPARISON_BALANCE`` — comparison-aware top-k defaults.
- The lookup helpers ``is_pipeline_name`` / ``pipeline_cli_choices`` /
  ``canonical_pipeline_name`` whose behavior is pure-data (no
  retrieval-side dependencies).

This module is a **leaf** — it imports nothing from ``rag_core``.
``rag_core`` re-exports every public symbol so existing call sites
(``app.py``, ``api/main.py``, ``scripts/run_benchmark.py``,
``demo/streamlit_app.py``, ``eval/run_eval.py`` and the test suite)
continue to use ``from rag_core import ...`` unchanged.

Validation / coercion (``resolve_pipeline_config``) stays in
``rag_core`` for stage 1 because it depends on ``VALID_RETRIEVAL_MODES``
and ``VALID_BM25_STOPWORD_PROFILES``. Stage 2 of the decomposition epic
revisits that split.
"""

from __future__ import annotations

from typing import Any


DEFAULT_CLI_PIPELINE_NAME = "naive_baseline"
DEFAULT_RAG_PIPELINE_NAME = "agentic_full"

# Canonical RRF fusion parameter. Imported back into ``rag_core`` for
# the hybrid retrieval helpers and ``resolve_pipeline_config``.
RRF_K = 60

# Inclusive bounds for the hybrid RRF k knob (issue #149). The lower
# bound rules out k=0 (division-by-zero); the upper bound is a sanity
# cap — beyond ~1000 the fusion is effectively a flat sum of ranks.
VALID_RRF_K_RANGE: tuple[int, int] = (1, 1000)

PIPELINE_CONFIG_KEYS = (
    "top_k",
    "metadata_first",
    "rerank",
    "rerank_cross_encoder",
    "verifier_retry",
    "retrieval_mode",
    "retrieval_backend",
    "prompt_profile",
    "rrf_k",
    "bm25_stopword_profile",
)

DEFAULT_COMPARISON_BALANCE: dict[str, Any] = {
    "enabled": True,
    "min_per_target": 1,
    "k_per_target": 3,
    "headroom": 2,
    "max_top_k": 12,
}

PIPELINE_PRESETS: dict[str, dict[str, Any]] = {
    "naive_baseline": {
        "top_k": 4,
        "metadata_first": False,
        "rerank": False,
        "rerank_cross_encoder": False,
        "verifier_retry": False,
        "retrieval_mode": "flat",
        "retrieval_backend": "dense",
        "prompt_profile": "minimal_grounded_extractive",
        "rrf_k": RRF_K,
        "bm25_stopword_profile": "shared",
        "description": (
            "Fixed-size chunks with dense top-k retrieval only; no metadata-first "
            "filtering, reranking, or verifier retry."
        ),
    },
    "agentic_full": {
        "top_k": None,
        "metadata_first": True,
        "rerank": True,
        "rerank_cross_encoder": False,
        "verifier_retry": True,
        "retrieval_mode": "flat",
        "retrieval_backend": "dense",
        "prompt_profile": "structured_grounded_claims",
        "rrf_k": RRF_K,
        "bm25_stopword_profile": "shared",
        "comparison_balance": dict(DEFAULT_COMPARISON_BALANCE),
        "description": "Metadata-first retrieval with lexical/metadata rerank and verifier retry.",
    },
    # ADR 0011 — additive LLM synthesis path. Same retrieval/verifier as
    # agentic_full; only the summary/answer_text rendering swaps to a
    # backend-pluggable LLM under the "no new chunk_ids" guard. Claims
    # and citations remain extractive (ADR 0003 preserved).
    "agentic_full_llm": {
        "top_k": None,
        "metadata_first": True,
        "rerank": True,
        "rerank_cross_encoder": False,
        "verifier_retry": True,
        "retrieval_mode": "flat",
        "prompt_profile": "llm_synthesis",
        "rrf_k": RRF_K,
        "bm25_stopword_profile": "shared",
        "comparison_balance": dict(DEFAULT_COMPARISON_BALANCE),
        "description": "agentic_full retrieval; LLM-synthesized summary under ADR 0011 guard.",
    },
}

PIPELINE_ALIASES = {"full": "agentic_full", "full_llm": "agentic_full_llm"}


def is_pipeline_name(value: Any) -> bool:
    name = str(value or "")
    return name in PIPELINE_PRESETS or name in PIPELINE_ALIASES


def pipeline_cli_choices() -> list[str]:
    # ADR 0001 explicit signal: this list is the source of truth for
    # which pipeline names are surfaced to the CLI. Adding/removing an
    # entry is the explicit revisit of that ADR (or, for additive
    # changes like ADR 0011, the explicit follow-on).
    return [DEFAULT_CLI_PIPELINE_NAME, DEFAULT_RAG_PIPELINE_NAME, "agentic_full_llm"]


def canonical_pipeline_name(value: str | None, default: str = DEFAULT_RAG_PIPELINE_NAME) -> str:
    requested = str(value or default)
    canonical = PIPELINE_ALIASES.get(requested, requested)
    if canonical not in PIPELINE_PRESETS:
        choices = ", ".join(sorted([*PIPELINE_PRESETS, *PIPELINE_ALIASES]))
        raise ValueError(f"pipeline must be one of: {choices}")
    return canonical
