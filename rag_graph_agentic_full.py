"""LangGraph orchestrator path for the agentic_full / agentic_full_llm presets.

Stage 1 of the PR-H epic (issue #401, ADR 0022). This module exposes
:func:`run_via_langgraph` as an alternative entry point to
:func:`rag_core.run_rag_query` that builds a one-node
:class:`langgraph.graph.StateGraph` and runs the existing query body
under it. The graph node delegates back to ``run_rag_query`` with a
recursion guard kwarg (`_skip_graph=True`) so the dispatch in
``rag_core.run_rag_query`` does not recurse.

Why a single passthrough node in stage 1
----------------------------------------
The full plan in ADR 0022 calls for multi-node decomposition
(``analyze`` → ``retrieve`` → ``build_answer`` with a conditional retry
edge), but the JSON-identity guarantee for ``agentic_full`` and
``agentic_full_llm`` is non-trivial: ``run_rag_query`` carries dozens
of cross-stage fields (timings, attempt index, query hash, conversation
state, trace blocks) and reproducing them through a multi-node graph
risks drift. Stage 1 lands the *dispatch infrastructure* — env var,
LangGraph dependency, regression-test harness — under a passthrough
node where JSON identity is structurally guaranteed. Multi-node
decomposition is a follow-up PR with its own regression budget.

LangGraph is an opt-in dependency (`requirements-graph.txt`); when not
installed, ``BIDMATE_ORCHESTRATOR=direct`` (the default) keeps the
existing call path and this module is never imported.
"""

from __future__ import annotations

from typing import Any, TypedDict

# Lazy import inside ``run_via_langgraph`` so a missing langgraph
# dependency only surfaces when the env var actually requests it. The
# module-level import would block ``import rag_core`` on plain installs.


class AgenticFullState(TypedDict, total=False):
    """LangGraph state shape for the agentic_full orchestrator path.

    Stage 1 only carries the call-time inputs and the final result —
    every intermediate field (analysis, evidence, plan, ...) is kept
    inside the passthrough node call so the JSON-identity guarantee is
    a tautology. Stage 2 expands this schema as nodes are split.
    """

    # Inputs (forwarded verbatim to run_rag_query under _skip_graph=True).
    index: dict[str, Any]
    query: str
    pipeline_kwargs: dict[str, Any]
    # Output of run_rag_query.
    result: dict[str, Any]


def _agentic_full_node(state: AgenticFullState) -> AgenticFullState:
    """Single passthrough node — delegates to run_rag_query with recursion guard."""
    # Imported lazily so ``rag_core`` never sees this module at import
    # time unless ``BIDMATE_ORCHESTRATOR=langgraph`` is set.
    from rag_core import run_rag_query

    result = run_rag_query(
        state["index"],
        state["query"],
        _skip_graph=True,
        **state["pipeline_kwargs"],
    )
    return {"result": result}


def _build_graph() -> Any:
    """Construct the (cached) StateGraph instance."""
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(AgenticFullState)
    builder.add_node("agentic_full", _agentic_full_node)
    builder.add_edge(START, "agentic_full")
    builder.add_edge("agentic_full", END)
    return builder.compile()


_GRAPH_CACHE: Any = None


def _graph() -> Any:
    """Return a process-cached compiled graph."""
    global _GRAPH_CACHE
    if _GRAPH_CACHE is None:
        _GRAPH_CACHE = _build_graph()
    return _GRAPH_CACHE


def run_via_langgraph(
    index: dict[str, Any],
    query: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """LangGraph entry point with the same return shape as :func:`run_rag_query`.

    All kwargs are forwarded to the passthrough node, which calls
    ``run_rag_query`` with ``_skip_graph=True`` to bypass the env-var
    dispatch. The compiled graph is process-cached so successive calls
    avoid the LangGraph builder overhead.

    Raises:
        ModuleNotFoundError: if ``langgraph`` is not installed. Install
            with ``pip install -r requirements-graph.txt``.
    """
    state: AgenticFullState = {
        "index": index,
        "query": query,
        "pipeline_kwargs": dict(kwargs),
    }
    result_state = _graph().invoke(state)
    return result_state["result"]
