"""LangGraph orchestrator path for the agentic_full / agentic_full_llm presets.

ADR 0022 stage 2 (issue #401 follow-up) splits the stage-1 single-node
passthrough into three nodes that mirror the phases inside the legacy
``run_rag_query`` body:

* ``analyze``      — calls :func:`rag_core._phase_analyze` (query
  analysis, conversation-context resolution, metadata-ambiguity check).
  A conditional edge routes directly to ``END`` when the phase
  short-circuits with a context-clarification or metadata-ambiguity
  reply.
* ``retrieve_loop`` — calls :func:`rag_core._phase_retrieve_loop` (the
  metadata-stage strict → reduced → relaxed retry loop with verifier
  feedback).
* ``build_answer`` — calls :func:`rag_core._phase_build_answer`
  (extractive answer + optional LLM synthesis + result-dict assembly).

The three nodes share a mutable :class:`rag_core._RunContext` instance
that they thread through the graph state. Because each phase function
is the same code the direct path runs (extracted from the original
``run_rag_query`` body in this stage-2 ADR), the JSON-identity contract
pinned by ``tests/test_langgraph_orchestrator_regression.py`` holds by
construction — no re-implementation of the orchestration in the graph
module.

LangGraph is an opt-in dependency (``requirements-graph.txt``); when
not installed, ``BIDMATE_ORCHESTRATOR=direct`` (the default) keeps the
existing call path and this module is never imported.
"""

from __future__ import annotations

from typing import Any, TypedDict

# Lazy import inside ``run_via_langgraph`` / node bodies so a missing
# langgraph dependency only surfaces when the env var actually requests
# it. The module-level import would block ``import rag_core`` on plain
# installs.


class AgenticFullState(TypedDict, total=False):
    """LangGraph state shape for the agentic_full multi-node graph.

    The ``ctx`` field is a mutable :class:`rag_core._RunContext`
    threaded through every node — the nodes update it in place and
    return ``{}`` so the merged state keeps the same object. The
    ``result`` field is set by ``analyze`` when the phase short-circuits
    (context-clarification or metadata-ambiguity) and by
    ``build_answer`` on the normal path; the entry point returns
    whichever was set.
    """

    ctx: Any
    result: dict[str, Any]


def _analyze_node(state: AgenticFullState) -> AgenticFullState:
    """Call :func:`rag_core._phase_analyze` and route the result.

    If the analyze phase returns a final dict (early return), we set
    ``state["result"]`` so the conditional edge after this node sends
    control to ``END``. Otherwise we return ``{}`` — the ctx has been
    mutated in place and the next node reads from it.
    """
    from rag_core import _phase_analyze

    early_result = _phase_analyze(state["ctx"])
    if early_result is not None:
        return {"result": early_result}
    return {}


def _retrieve_loop_node(state: AgenticFullState) -> AgenticFullState:
    """Call :func:`rag_core._phase_retrieve_loop`; mutates ctx in place."""
    from rag_core import _phase_retrieve_loop

    _phase_retrieve_loop(state["ctx"])
    return {}


def _build_answer_node(state: AgenticFullState) -> AgenticFullState:
    """Call :func:`rag_core._phase_build_answer` and set the final result."""
    from rag_core import _phase_build_answer

    result = _phase_build_answer(state["ctx"])
    return {"result": result}


def _route_after_analyze(state: AgenticFullState) -> str:
    """Conditional-edge router: short-circuit to END if analyze emitted a result."""
    return "end" if state.get("result") is not None else "retrieve_loop"


def _build_graph() -> Any:
    """Construct the (cached) StateGraph instance for stage 2."""
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(AgenticFullState)
    builder.add_node("analyze", _analyze_node)
    builder.add_node("retrieve_loop", _retrieve_loop_node)
    builder.add_node("build_answer", _build_answer_node)
    builder.add_edge(START, "analyze")
    builder.add_conditional_edges(
        "analyze",
        _route_after_analyze,
        {"end": END, "retrieve_loop": "retrieve_loop"},
    )
    builder.add_edge("retrieve_loop", "build_answer")
    builder.add_edge("build_answer", END)
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
    """LangGraph entry point with the same return shape as :func:`rag_core.run_rag_query`.

    Builds the per-query :class:`rag_core._RunContext` up front (handles
    ``params=`` bundle normalization, pipeline-preset resolution,
    cold-start flag, query hashing, trace setup) and threads it through
    the three-node graph. The compiled graph is process-cached so
    successive calls avoid the LangGraph builder overhead.

    Raises:
        ModuleNotFoundError: if ``langgraph`` is not installed. Install
            with ``pip install -r requirements-graph.txt``.
    """
    from rag_core import _build_run_context

    ctx = _build_run_context(
        index,
        query,
        top_k=kwargs.get("top_k"),
        context_entities=kwargs.get("context_entities"),
        metadata_first=kwargs.get("metadata_first"),
        rerank=kwargs.get("rerank"),
        verifier_retry=kwargs.get("verifier_retry"),
        retrieval_mode=kwargs.get("retrieval_mode"),
        retrieval_backend=kwargs.get("retrieval_backend"),
        pipeline=kwargs.get("pipeline"),
        prompt_profile=kwargs.get("prompt_profile"),
        conversation_state=kwargs.get("conversation_state"),
        comparison_balance=kwargs.get("comparison_balance"),
        rrf_k=kwargs.get("rrf_k"),
        bm25_stopword_profile=kwargs.get("bm25_stopword_profile"),
        params=kwargs.get("params"),
    )

    state: AgenticFullState = {"ctx": ctx}
    result_state = _graph().invoke(state)
    return result_state["result"]
