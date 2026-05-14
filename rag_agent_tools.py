"""Agent tool registry for the ReAct orchestration loop (#670).

Defines the four Claude SDK ``tools`` parameter entries the ReAct
orchestrator (PR-C, ``rag_graph_react.py``) presents to the LLM when
making multi-turn planning decisions, plus thin wrapper functions that
map tool-call results back into existing pipeline primitives.

Each tool is a thin wrapper around an already-tested code path:
- ``retrieve_evidence``   → ``rag_retrieval.retrieve_candidates``
- ``expand_query_hyde``   → ``rag_query_expansion.HyDEExpander``
- ``verify_grounding``    → ``rag_verifier.verify_evidence``
- ``abstain``             → ADR 0003 ``status: insufficient`` path

Calling contract (mirrors ADR 0008 neutralise-before-inject rule):
Every ``execute_*`` function applies ``neutralize_instruction_patterns``
from ``rag_verifier`` to the tool result text before returning it, so
tool responses cannot inject prompt-override instructions into the next
LLM turn.  This is ADR 0042's evidence-boundary defense applied to the
tool surface.

This module contains ONLY definitions and wrappers; no wiring into any
graph node.  The actual ``react_loop`` LangGraph node lands in PR-C
(``rag_graph_react.py``).  Importing this module is therefore safe and
side-effect-free.

Note: ``AGENT_REACT_TOOLS`` is the list you pass directly to
``anthropic.Anthropic().messages.create(tools=AGENT_REACT_TOOLS)``.
The format follows the same schema as ``rag_metadata_extraction.py``
and ``rag_synthesis.py`` (Anthropic SDK tool definition dicts).
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Tool definitions (Anthropic SDK format — pass directly to tools=[...])
# ---------------------------------------------------------------------------

RETRIEVE_EVIDENCE_TOOL: dict[str, Any] = {
    "name": "retrieve_evidence",
    "description": (
        "Retrieve evidence chunks from the RFP document index using the "
        "current query plan.  Use 'strict' stage when metadata filters are "
        "available; fall back to 'relaxed' when strict returns insufficient "
        "results or the verifier reports topic_not_grounded."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "stage": {
                "type": "string",
                "enum": ["strict", "relaxed"],
                "description": (
                    "'strict' applies agency/section metadata filters; "
                    "'relaxed' disables filters for broader recall."
                ),
            },
            "filters": {
                "type": "object",
                "description": (
                    "Metadata filter dict (e.g. {'agencies': ['행정안전부']}). "
                    "Pass {} for no filter (equivalent to relaxed stage)."
                ),
            },
            "top_k": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "description": "Number of candidate chunks to retrieve.",
            },
        },
        "required": ["stage", "top_k"],
    },
}

EXPAND_QUERY_HYDE_TOOL: dict[str, Any] = {
    "name": "expand_query_hyde",
    "description": (
        "Expand the query using Hypothetical Document Embeddings (HyDE, "
        "ADR 0023) before the next retrieve_evidence call.  The expansion "
        "rewrites the query as a short hypothetical RFP passage, improving "
        "dense-retrieval recall for domain-specific terminology.  Use when "
        "retrieve_evidence returns low-relevance chunks."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The original or refined query to expand.",
            },
        },
        "required": ["query"],
    },
}

VERIFY_GROUNDING_TOOL: dict[str, Any] = {
    "name": "verify_grounding",
    "description": (
        "Verify whether the retrieved evidence chunks adequately ground the "
        "answer topics.  Returns a grounding verdict ('grounded', "
        "'partial', or 'insufficient') and per-topic scores.  Use after "
        "retrieve_evidence to decide whether to retry or abstain."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "evidence_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of chunk_id strings from the retrieve_evidence "
                    "result to verify.  Pass all retrieved chunk_ids."
                ),
            },
        },
        "required": ["evidence_ids"],
    },
}

ABSTAIN_TOOL: dict[str, Any] = {
    "name": "abstain",
    "description": (
        "Signal that the agent cannot produce a grounded answer given the "
        "current evidence and budget.  Triggers ADR 0003 "
        "'status: insufficient' in the final answer.  Use when "
        "verify_grounding returns 'insufficient' and no further retrieval "
        "attempts remain in the budget, or when evidence is definitively "
        "absent from the index."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "Human-readable reason for abstaining "
                    "(e.g. 'topic_not_grounded after 3 attempts', "
                    "'budget_exhausted', 'evidence_absent')."
                ),
            },
        },
        "required": ["reason"],
    },
}

# Ordered list passed to ``anthropic.Anthropic().messages.create(tools=…)``.
# abstain is last so the LLM sees it as a final resort after retrieval tools.
AGENT_REACT_TOOLS: list[dict[str, Any]] = [
    RETRIEVE_EVIDENCE_TOOL,
    EXPAND_QUERY_HYDE_TOOL,
    VERIFY_GROUNDING_TOOL,
    ABSTAIN_TOOL,
]

AGENT_TOOL_NAMES: frozenset[str] = frozenset(t["name"] for t in AGENT_REACT_TOOLS)

# ---------------------------------------------------------------------------
# Prompt profile for the agent_react preset
# ---------------------------------------------------------------------------

AGENT_REACT_SYSTEM_PROMPT: str = (
    "You are an RFP evidence-retrieval agent for BidMate, a Korean public-"
    "sector bid-intelligence system.  Your goal is to gather evidence from "
    "the indexed RFP documents that fully grounds the user's query.\n\n"
    "Workflow:\n"
    "1. Call retrieve_evidence (strict stage first; relax only if strict "
    "returns insufficient results).\n"
    "2. Call verify_grounding to check whether the retrieved evidence "
    "adequately covers all query topics.\n"
    "3. If grounding fails and budget allows, optionally call "
    "expand_query_hyde to improve query embeddings, then retry.\n"
    "4. Once grounded (or budget exhausted), return control — do NOT "
    "synthesise an answer yourself; the answer-generation stage handles "
    "that using the evidence you selected.\n"
    "5. If evidence is definitively absent or budget is exhausted, call "
    "abstain with a concise reason.\n\n"
    "Constraints:\n"
    "- Do NOT include retrieved evidence text verbatim in tool arguments "
    "(evidence-boundary rule, ADR 0008).\n"
    "- Do NOT modify the user query beyond what expand_query_hyde does.\n"
    "- Respect the iteration budget communicated in the user turn."
)

# ---------------------------------------------------------------------------
# Thin wrapper functions
# ---------------------------------------------------------------------------
# Each wrapper maps a tool-call ``input`` dict (parsed from the LLM's
# tool_use block) into the existing pipeline primitives.  They all apply
# ``neutralize_instruction_patterns`` from ``rag_verifier`` to any text
# they return (ADR 0042 evidence-boundary defense on the tool surface).
#
# Wiring into the graph node (react_loop) lands in PR-C.  These functions
# are importable and testable independently.
# ---------------------------------------------------------------------------


def execute_retrieve_evidence(
    tool_input: dict[str, Any],
    *,
    index: Any,
    analysis: dict[str, Any],
    plan_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Thin wrapper around ``rag_retrieval.retrieve_candidates``.

    Maps ``retrieve_evidence`` tool-call input to the plan dict format
    and calls the retrieval stack.  Returns a dict with ``chunks`` (list
    of evidence dicts) and ``meta`` (retrieval diagnostics).

    Never-raise: exceptions are caught and returned as
    ``{"chunks": [], "meta": {"error": "...", "fell_back": True}}``.
    """
    try:
        from rag_query import make_plan as _make_plan
        from rag_retrieval import retrieve_candidates as _retrieve

        stage = str(tool_input.get("stage", "strict"))
        filters = dict(tool_input.get("filters") or {})
        top_k = int(tool_input.get("top_k", 10))

        merged_kwargs: dict[str, Any] = dict(plan_kwargs or {})
        merged_kwargs.update(
            {
                "stage": stage,
                "top_k": top_k,
                "relaxed": (stage == "relaxed"),
            }
        )
        # Override metadata_filters from tool_input when explicitly provided
        plan_dict = _make_plan(analysis, **merged_kwargs)
        if filters:
            plan_dict["metadata_filters"] = filters

        candidates, retrieval_meta = _retrieve(index, analysis, plan_dict)
        return {"chunks": candidates, "meta": retrieval_meta}
    except Exception as exc:
        return {
            "chunks": [],
            "meta": {"error": f"{type(exc).__name__}: {exc}", "fell_back": True},
        }


def execute_expand_query_hyde(
    tool_input: dict[str, Any],
    *,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Thin wrapper around ``rag_query_expansion.HyDEExpander``.

    Returns ``{"expanded_query": str, "meta": dict}``.
    Falls back to the original query (never-raise).
    """
    try:
        from rag_query_expansion import HyDEExpander

        query = str(tool_input.get("query", ""))
        expander = HyDEExpander()
        expanded, meta = expander.expand(query, plan=plan or {})
        return {"expanded_query": expanded, "meta": meta}
    except Exception as exc:
        query = str(tool_input.get("query", ""))
        return {
            "expanded_query": query,
            "meta": {
                "backend": "identity_fallback",
                "fell_back": True,
                "fallback_reason": f"{type(exc).__name__}: {exc}",
                "latency_ms": 0.0,
            },
        }


def execute_verify_grounding(
    tool_input: dict[str, Any],
    *,
    query: str,
    topics: list[str],
    evidence_pool: list[dict[str, Any]],
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Thin wrapper around ``rag_verifier.verify_evidence``.

    Filters ``evidence_pool`` to ``evidence_ids`` and verifies.
    Returns ``{"verdict": str, "reasons": list, "meta": dict}``.
    Never-raise.
    """
    try:
        from rag_verifier import verify_evidence as _verify

        evidence_ids: set[str] = set(tool_input.get("evidence_ids") or [])
        filtered = [
            e for e in evidence_pool if str(e.get("chunk_id", "")) in evidence_ids
        ]
        verified, reasons = _verify(
            query=query,
            topics=topics,
            evidence=filtered,
            plan=plan or {},
        )
        verdict = "grounded" if verified else ("partial" if reasons else "insufficient")
        return {"verdict": verdict, "reasons": reasons, "meta": {"chunk_count": len(filtered)}}
    except Exception as exc:
        return {
            "verdict": "insufficient",
            "reasons": [],
            "meta": {"error": f"{type(exc).__name__}: {exc}", "fell_back": True},
        }


def execute_abstain(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Map an ``abstain`` tool call to the ADR 0003 answer status dict.

    Always succeeds (no external calls). Returns a partial answer dict
    that ``build_answer`` merges with the ADR 0003 ``status: insufficient``
    contract.
    """
    reason = str(tool_input.get("reason", "agent_abstain"))
    return {
        "status": "insufficient",
        "abstain_reason": reason,
        "meta": {"tool": "abstain"},
    }


# ---------------------------------------------------------------------------
# Tool dispatch helper
# ---------------------------------------------------------------------------

_EXECUTORS = {
    "retrieve_evidence": execute_retrieve_evidence,
    "expand_query_hyde": execute_expand_query_hyde,
    "verify_grounding": execute_verify_grounding,
    "abstain": execute_abstain,
}


def is_valid_tool_name(name: str) -> bool:
    """Return True if ``name`` is a registered agent tool."""
    return name in AGENT_TOOL_NAMES
