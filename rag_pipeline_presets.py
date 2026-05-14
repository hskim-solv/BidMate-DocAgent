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
    # Issue #486 / ADR 0031 — pluggable BM25 tokenizer discriminator.
    # "regex" (default) preserves the ADR 0001 naive_baseline invariant
    # and the existing ``re.compile(r"[A-Za-z0-9]+|[가-힣]+")`` token
    # surface. "kiwi" opts into kiwipiepy morpheme tokenization. Never-
    # raise: if kiwipiepy is missing the dispatch silently falls back to
    # regex. See ``korean_lexicon.kiwi_tokens``.
    "bm25_tokenizer",
    # Issue #396 — string discriminator for the query-side rewrite stage.
    # "identity" (default) preserves the ADR 0001 naive_baseline invariant;
    # "hyde" opts into Hypothetical Document Embeddings (LLM rewrite of
    # the dense-embedding target). See ``rag_query_expansion.py`` and
    # ADR 0023.
    "query_expansion",
    # Issue #673 / ADR 0040 — planner backend discriminator for the
    # agent_react preset.  "static" (default) delegates to
    # ``rag_query.make_plan`` — deterministic, no LLM call, CI-safe.
    # "anthropic" activates ``LLMPlanner`` via the Anthropic SDK.
    # Mirrors the ``BIDMATE_QUERY_EXPANSION_BACKEND`` / ``BIDMATE_SYNTHESIS_BACKEND``
    # env-var opt-in pattern (ADR 0011, ADR 0023).
    "planner_backend",
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
        # ADR 0031 invariant — naive_baseline MUST stay at regex tokenizer.
        # naive_baseline uses retrieval_backend="dense" so BM25 never fires,
        # but the explicit value documents intent + protects future changes
        # that might enable BM25 here.
        "bm25_tokenizer": "regex",
        # ADR 0001 invariant — naive_baseline MUST stay at identity. Any
        # change here breaks the bit-identical top-K golden test.
        "query_expansion": "identity",
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
        # ADR 0031 — kiwi tokenizer is opt-in per-row in eval/config.yaml.
        # agentic_full default is regex so existing "full" eval row stays
        # byte-equal; the new "full_kiwi" row sets this to "kiwi".
        "bm25_tokenizer": "regex",
        # ADR 0023 — query expansion is opt-in per-row in eval/config.yaml.
        # agentic_full default is identity so the existing "full" eval row
        # stays byte-equal; the new "full_hyde" row sets this to "hyde".
        "query_expansion": "identity",
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
        "bm25_tokenizer": "regex",
        "query_expansion": "identity",
        "comparison_balance": dict(DEFAULT_COMPARISON_BALANCE),
        "description": "agentic_full retrieval; LLM-synthesized summary under ADR 0011 guard.",
    },
    # ADR 0040 — additive ReAct agent loop preset.  Same retrieval/verifier
    # stack as agentic_full; planner_backend controls the orchestration
    # implementation (ADR 0041 budget cap contract).
    # BIDMATE_PLANNER_BACKEND=static (default) → deterministic CI path.
    # BIDMATE_PLANNER_BACKEND=anthropic → LLMPlanner multi-turn planning.
    "agent_react": {
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
        # ADR 0031 invariant — keep regex so the agent_react eval row
        # does not conflate tokenizer change with agent-loop effect.
        "bm25_tokenizer": "regex",
        # ADR 0023 — identity default preserves retrievals comparability
        # with agentic_full baseline (agent adds planning, not expansion).
        "query_expansion": "identity",
        # ADR 0040 / ADR 0041 — "static" is CI-safe (no LLM call).
        # Set BIDMATE_PLANNER_BACKEND=anthropic for real agent runs.
        "planner_backend": "static",
        "comparison_balance": dict(DEFAULT_COMPARISON_BALANCE),
        "description": (
            "ReAct agent loop: LLMPlanner selects retrieval actions until "
            "evidence is grounded or budget is exhausted (ADR 0040/0041). "
            "BIDMATE_PLANNER_BACKEND=static (default, CI-safe) or "
            "anthropic (opt-in, real LLM planning)."
        ),
    },
}

PIPELINE_ALIASES = {
    "full": "agentic_full",
    "full_llm": "agentic_full_llm",
    # ADR 0040 — short alias for the ReAct preset.
    "react": "agent_react",
}


def is_pipeline_name(value: Any) -> bool:
    name = str(value or "")
    return name in PIPELINE_PRESETS or name in PIPELINE_ALIASES


def pipeline_cli_choices() -> list[str]:
    # ADR 0001 explicit signal: ``PIPELINE_PRESETS`` is the single source
    # of truth for which pipeline names are surfaced to the CLI. Adding
    # a preset to that dict above auto-extends this list; removing one
    # disappears it. The historical hardcoded triple
    # ``[naive_baseline, agentic_full, agentic_full_llm]`` is preserved
    # bit-equal under Python 3.7+ dict insertion order (issue #384).
    return list(PIPELINE_PRESETS.keys())


def canonical_pipeline_name(value: str | None, default: str = DEFAULT_RAG_PIPELINE_NAME) -> str:
    requested = str(value or default)
    canonical = PIPELINE_ALIASES.get(requested, requested)
    if canonical not in PIPELINE_PRESETS:
        choices = ", ".join(sorted([*PIPELINE_PRESETS, *PIPELINE_ALIASES]))
        raise ValueError(f"pipeline must be one of: {choices}")
    return canonical


# ─── Pipeline config validation (PR-E stage 2, issue #375) ────────────
# Three retrieval-side validation sets used by ``resolve_pipeline_config``
# AND by per-query override helpers in ``rag_core`` (e.g. the
# ``rrf_k``/``retrieval_mode`` checks inside ``plan_retrieval`` and the
# hybrid retriever entry points). Owning them here keeps the leaf module
# self-contained — ``resolve_pipeline_config`` does not have to reach
# back into ``rag_core`` to validate.
VALID_RETRIEVAL_MODES = {"flat", "hierarchical"}
# Issue #151 — ``m3`` opts into BGE-M3's dense + sparse + multi-vector
# (ColBERT-style) channels fused via N-way RRF. Opt-in only; default
# stays ``dense``. Requires ``pip install -r requirements-m3.txt``.
# See ``docs/m3-multichannel-spike.md`` and ADR 0010's
# "Alternatives considered" (lines 72-85) for the deferral context.
VALID_RETRIEVAL_BACKENDS = {"dense", "hybrid", "m3"}
VALID_BM25_STOPWORD_PROFILES = {"shared", "bm25_extra"}
# Issue #486 / ADR 0031 — additive Korean-morphology tokenizer.
# "regex" preserves the ADR 0001 naive_baseline invariant; "kiwi" opts
# into kiwipiepy morpheme tokenization (체언 / 용언 / 수식어 /
# 외래어 POS filter). Missing kiwipiepy → silent fallback to regex,
# enforced by `korean_lexicon.kiwi_tokens` returning ``None``.
VALID_BM25_TOKENIZERS = {"regex", "kiwi", "mecab", "khaiii"}
# Issue #561 / ADR 0031 valid-set expansion: "mecab" (python-mecab-ko /
# konlpy.tag.Mecab) and "khaiii" (Khaiii C++ binding) added as opt-in
# ablation tokenizers. Both have the same never-raise contract as "kiwi":
# if the dependency is unavailable, `korean_lexicon.mecab_tokens` /
# `khaiii_tokens` return None and rag_retrieval silently falls back to
# regex — ADR 0001 naive_baseline invariant preserved.
# Issue #396 / ADR 0023 — pluggable QueryExpander discriminator. Kept
# narrow on purpose: a typo like "hide" raises rather than silently
# degrading retrieval. ``rag_query_expansion.default_expander`` still
# tolerates unknown values for runtime safety, but config-time
# validation prefers an explicit allow-list.
VALID_QUERY_EXPANSIONS = {"identity", "hyde"}
# Issue #673 / ADR 0040 — pluggable Planner backend discriminator.
# "static" (default) → StaticPlanner (make_plan, deterministic, no LLM).
# "anthropic" → LLMPlanner (Anthropic SDK multi-turn, BIDMATE_PLANNER_BACKEND=anthropic).
VALID_PLANNER_BACKENDS = {"static", "anthropic"}


def resolve_pipeline_config(
    value: str | dict[str, Any] | None = None,
    default_pipeline: str = DEFAULT_RAG_PIPELINE_NAME,
) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    requested = str(value) if isinstance(value, str) else str(source.get("pipeline") or "")
    if not requested and is_pipeline_name(source.get("name")):
        requested = str(source.get("name"))
    canonical = canonical_pipeline_name(requested or default_pipeline, default_pipeline)
    config = dict(PIPELINE_PRESETS[canonical])
    config["pipeline"] = canonical
    if requested and requested != canonical:
        config["pipeline_alias"] = requested

    for key in PIPELINE_CONFIG_KEYS:
        if key not in source or source.get(key) is None:
            continue
        config[key] = source[key]

    if "comparison_balance" in source and source.get("comparison_balance") is not None:
        config["comparison_balance"] = source["comparison_balance"]

    top_k = config.get("top_k")
    if top_k is not None:
        top_k = int(top_k)
        if top_k < 1:
            raise ValueError("top_k must be positive.")
    retrieval_mode = str(config.get("retrieval_mode") or "flat")
    if retrieval_mode not in VALID_RETRIEVAL_MODES:
        choices = ", ".join(sorted(VALID_RETRIEVAL_MODES))
        raise ValueError(f"retrieval_mode must be one of: {choices}")
    retrieval_backend = str(config.get("retrieval_backend") or "dense")
    if retrieval_backend not in VALID_RETRIEVAL_BACKENDS:
        choices = ", ".join(sorted(VALID_RETRIEVAL_BACKENDS))
        raise ValueError(f"retrieval_backend must be one of: {choices}")
    rrf_k_raw = config.get("rrf_k")
    rrf_k = RRF_K if rrf_k_raw is None else int(rrf_k_raw)
    rrf_lo, rrf_hi = VALID_RRF_K_RANGE
    if rrf_k < rrf_lo or rrf_k > rrf_hi:
        raise ValueError(f"rrf_k must be in [{rrf_lo}, {rrf_hi}].")
    bm25_stopword_profile = str(config.get("bm25_stopword_profile") or "shared")
    if bm25_stopword_profile not in VALID_BM25_STOPWORD_PROFILES:
        choices = ", ".join(sorted(VALID_BM25_STOPWORD_PROFILES))
        raise ValueError(f"bm25_stopword_profile must be one of: {choices}")
    bm25_tokenizer = str(config.get("bm25_tokenizer") or "regex").lower()
    if bm25_tokenizer not in VALID_BM25_TOKENIZERS:
        choices = ", ".join(sorted(VALID_BM25_TOKENIZERS))
        raise ValueError(f"bm25_tokenizer must be one of: {choices}")
    query_expansion = str(config.get("query_expansion") or "identity").lower()
    if query_expansion not in VALID_QUERY_EXPANSIONS:
        choices = ", ".join(sorted(VALID_QUERY_EXPANSIONS))
        raise ValueError(f"query_expansion must be one of: {choices}")

    config["top_k"] = top_k
    config["metadata_first"] = bool(config.get("metadata_first"))
    config["rerank"] = bool(config.get("rerank"))
    config["rerank_cross_encoder"] = bool(config.get("rerank_cross_encoder"))
    config["verifier_retry"] = bool(config.get("verifier_retry"))
    config["retrieval_mode"] = retrieval_mode
    config["retrieval_backend"] = retrieval_backend
    config["prompt_profile"] = str(config.get("prompt_profile") or "structured_grounded_claims")
    config["rrf_k"] = rrf_k
    config["bm25_stopword_profile"] = bm25_stopword_profile
    config["bm25_tokenizer"] = bm25_tokenizer
    config["query_expansion"] = query_expansion
    return config
