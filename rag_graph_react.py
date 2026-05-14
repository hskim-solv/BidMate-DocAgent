"""LangGraph orchestrator for the agent_react preset — ReAct loop (#673).

ADR 0040 adds a fourth LangGraph node ``react_loop`` that runs between
``analyze`` and ``build_answer``.  When ``pipeline == "agent_react"``
the router in ``rag_core.run_rag_query`` calls
:func:`run_via_langgraph_react` instead of the standard direct or
``agentic_full`` paths.

Graph shape::

    START → analyze → [react_loop | retrieve_loop | end] → build_answer → END

* ``analyze`` — same node as ``rag_graph_agentic_full`` (calls
  ``rag_core._phase_analyze``).
* ``react_loop`` — NEW: runs the ``Planner.plan_next`` → executor →
  verifier cycle until evidence is grounded or the ADR 0041 budget cap
  is reached, then mutates ``ctx.evidence`` / ``ctx.plan`` so
  ``build_answer`` can read them.
* ``retrieve_loop`` — re-used from ``rag_graph_agentic_full`` as fallback
  when ``BIDMATE_PLANNER_BACKEND=static`` with ``analyze`` early-exit.
* ``build_answer`` — same node as ``rag_graph_agentic_full``.

Budget cap (ADR 0041):
  ``max_iterations`` (env ``BIDMATE_PLANNER_MAX_ITERATIONS``, default 5),
  ``max_latency_ms`` (env ``BIDMATE_PLANNER_MAX_LATENCY_MS``, default 8000).
  When the cap is reached the loop sets ``ctx.evidence`` to whatever was
  retrieved and ``build_answer`` emits ``status: insufficient`` via the
  existing ADR 0003 abstention path.

LangGraph is an opt-in dependency (``requirements-graph.txt``).
``BIDMATE_ORCHESTRATOR`` does not need to be set for ``agent_react`` —
``rag_core`` dispatches directly on pipeline name.
"""
from __future__ import annotations

import os
import time
from typing import Any, TypedDict

from rag_planner import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_LATENCY_MS,
    ENV_PLANNER_MAX_ITERATIONS,
    ENV_PLANNER_MAX_LATENCY_MS,
    default_planner,
)


class ReactState(TypedDict, total=False):
    """LangGraph state for the agent_react multi-node graph.

    ``ctx`` is a mutable :class:`rag_core._RunContext` threaded through
    every node exactly as in ``rag_graph_agentic_full.AgenticFullState``.
    ``result`` is set by ``analyze`` on early-exit or by ``build_answer``.
    """

    ctx: Any
    result: dict[str, Any]


# ---------------------------------------------------------------------------
# Shared nodes (delegate to same phase functions as agentic_full)
# ---------------------------------------------------------------------------


def _analyze_node(state: ReactState) -> ReactState:
    from rag_core import _phase_analyze

    early_result = _phase_analyze(state["ctx"])
    if early_result is not None:
        return {"result": early_result}
    return {}


def _build_answer_node(state: ReactState) -> ReactState:
    from rag_core import _phase_build_answer

    result = _phase_build_answer(state["ctx"])
    return {"result": result}


# ---------------------------------------------------------------------------
# react_loop node
# ---------------------------------------------------------------------------


def _react_loop_node(state: ReactState) -> ReactState:
    """Run the ReAct planning loop and populate ctx.evidence / ctx.plan.

    Calls ``Planner.plan_next`` in a loop.  Each iteration dispatches the
    chosen tool via ``rag_agent_tools.execute_*``, appends to history,
    and checks budget.  Loop exits when the planner selects ``abstain``
    or when the ADR 0041 cap is hit; ``ctx.evidence`` and ``ctx.plan``
    are set so ``_phase_build_answer`` can read them.
    """
    from rag_agent_tools import (
        execute_abstain,
        execute_expand_query_hyde,
        execute_retrieve_evidence,
        execute_verify_grounding,
    )
    from rag_verifier import verification_topics

    ctx = state["ctx"]
    analysis = ctx.analysis or {}

    max_iterations = int(
        os.environ.get(ENV_PLANNER_MAX_ITERATIONS, DEFAULT_MAX_ITERATIONS)
    )
    max_latency_ms = float(
        os.environ.get(ENV_PLANNER_MAX_LATENCY_MS, DEFAULT_MAX_LATENCY_MS)
    )

    # Build preset_kwargs from ctx so StaticPlanner / LLMPlanner produce
    # a plan consistent with the preset configuration.
    preset_kwargs: dict[str, Any] = {
        "rerank": ctx.rerank,
        "metadata_first": ctx.metadata_first,
        "verifier_retry": ctx.verifier_retry,
        "retrieval_mode": ctx.retrieval_mode,
        "retrieval_backend": ctx.retrieval_backend,
        "rrf_k": ctx.rrf_k,
        "bm25_stopword_profile": ctx.bm25_stopword_profile,
        "bm25_tokenizer": ctx.bm25_tokenizer,
        "pipeline": ctx.pipeline_name,
        "prompt_profile": ctx.prompt_profile,
    }
    planner = default_planner(preset_kwargs=preset_kwargs)

    history: list[dict[str, Any]] = []
    loop_started = time.perf_counter()
    topics = verification_topics(analysis)
    evidence: list[dict[str, Any]] = []
    last_plan: dict[str, Any] = {}

    for iteration in range(max_iterations):
        elapsed_ms = (time.perf_counter() - loop_started) * 1000.0
        if elapsed_ms >= max_latency_ms:
            history.append(
                {
                    "iteration": iteration,
                    "tool": "budget_exhausted",
                    "reason": f"max_latency_ms={max_latency_ms} exceeded",
                }
            )
            break

        budget: dict[str, Any] = {
            "iterations_left": max_iterations - iteration,
            "ms_left": max(0.0, max_latency_ms - elapsed_ms),
        }

        next_action, planner_meta = planner.plan_next(
            analysis=analysis,
            history=history,
            budget=budget,
        )

        tool = next_action.get("tool", "abstain")
        tool_input = next_action.get("args", {})

        attempt: dict[str, Any] = {
            "iteration": iteration,
            "tool": tool,
            "planner_meta": planner_meta,
        }

        if tool == "retrieve_evidence":
            tool_result = execute_retrieve_evidence(
                tool_input,
                index=ctx.index,
                analysis=analysis,
                plan_kwargs=preset_kwargs,
            )
            new_chunks = tool_result.get("chunks") or []
            evidence = new_chunks  # replace (not extend) for clean grounding
            last_plan = tool_input.get("args", tool_input)
            attempt["result"] = {
                "chunk_count": len(new_chunks),
                "meta": tool_result.get("meta", {}),
            }

        elif tool == "expand_query_hyde":
            tool_result = execute_expand_query_hyde(tool_input, plan=last_plan)
            expanded_query = tool_result.get("expanded_query", ctx.retrieval_query)
            ctx.retrieval_query = expanded_query
            attempt["result"] = {
                "expanded_query": expanded_query,
                "meta": tool_result.get("meta", {}),
            }

        elif tool == "verify_grounding":
            chunk_ids = [str(c.get("chunk_id", "")) for c in evidence]
            tool_result = execute_verify_grounding(
                {"evidence_ids": chunk_ids},
                query=ctx.query,
                topics=topics,
                evidence_pool=evidence,
                plan=last_plan,
            )
            attempt["result"] = tool_result
            if tool_result.get("verdict") == "grounded":
                history.append(attempt)
                break  # Grounded — exit loop

        elif tool == "abstain":
            execute_abstain(tool_input)
            attempt["result"] = {"reason": tool_input.get("reason", "agent_abstain")}
            history.append(attempt)
            evidence = []
            break

        else:
            attempt["result"] = {"error": f"unknown tool: {tool}"}

        history.append(attempt)

    # Populate ctx so build_answer can consume without modification.
    ctx.evidence = evidence if evidence else []
    ctx.plan = last_plan
    # Expose react_loop history as a stage attempt so telemetry captures it.
    ctx.stage_attempts = history
    return {}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def _route_after_analyze(state: ReactState) -> str:
    """Route to react_loop normally; short-circuit to end on early analyze exit."""
    return "end" if state.get("result") is not None else "react_loop"


# ---------------------------------------------------------------------------
# Graph construction (process-cached)
# ---------------------------------------------------------------------------


def _build_react_graph() -> Any:
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(ReactState)
    builder.add_node("analyze", _analyze_node)
    builder.add_node("react_loop", _react_loop_node)
    builder.add_node("build_answer", _build_answer_node)
    builder.add_edge(START, "analyze")
    builder.add_conditional_edges(
        "analyze",
        _route_after_analyze,
        {"end": END, "react_loop": "react_loop"},
    )
    builder.add_edge("react_loop", "build_answer")
    builder.add_edge("build_answer", END)
    return builder.compile()


_REACT_GRAPH_CACHE: Any = None


def _react_graph() -> Any:
    global _REACT_GRAPH_CACHE
    if _REACT_GRAPH_CACHE is None:
        _REACT_GRAPH_CACHE = _build_react_graph()
    return _REACT_GRAPH_CACHE


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_via_langgraph_react(
    index: dict[str, Any],
    query: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Entry point with the same return shape as :func:`rag_core.run_rag_query`.

    Called by ``rag_core.run_rag_query`` when ``pipeline == "agent_react"``.
    Builds a :class:`rag_core._RunContext`, feeds it into the react graph,
    and returns the assembled answer dict.

    Raises:
        ModuleNotFoundError: if ``langgraph`` is not installed.
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
        bm25_tokenizer=kwargs.get("bm25_tokenizer"),
        params=kwargs.get("params"),
    )

    state: ReactState = {"ctx": ctx}
    result_state = _react_graph().invoke(state)
    return result_state["result"]
