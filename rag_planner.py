"""Planner Protocol — pluggable next-action planning stage (#659, #673).

The ``Planner`` Protocol decouples the ReAct agent loop from the specific
planning backend, so future strategies (LLM-based multi-turn planning,
tool-use orchestration) can plug in without modifying the orchestration
graph.  Mirrors the ``QueryExpander`` / ``Reranker`` / ``VectorStore``
pattern (ADR 0020 four-property pluggability).

``StaticPlanner`` is the default; it delegates to ``rag_query.make_plan``
so the existing deterministic plan construction is preserved unchanged.
History and budget are accepted but ignored — ``StaticPlanner`` makes a
single-pass decision exactly as the current pipeline does.

``LLMPlanner`` (PR-C) is the first opt-in implementation: multi-turn
Anthropic SDK ``tools`` call that selects the next action from a
registered tool set based on analysis + history + remaining budget.

Critical contract:
- ``plan_next`` must NEVER raise; on any failure the implementation must
  return ``{"tool": "abstain", "args": {"reason": "planner_error"}}`` with
  ``meta["fell_back"] = True``.
- ``next_action["tool"]`` must be one of the registered tool names or
  ``"abstain"``.
- ``meta`` must include the keys defined in ``_REQUIRED_META_KEYS``.

Convention: follows ADR 0020 Protocol-based pluggability.  New planners
implement ``Planner`` and register via ``default_planner()`` — the agent
loop is untouched.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Protocol, runtime_checkable

# Env-var contract (mirrors rag_query_expansion.py / rag_synthesis.py).
ENV_PLANNER_BACKEND = "BIDMATE_PLANNER_BACKEND"
ENV_PLANNER_MODEL = "BIDMATE_PLANNER_MODEL"
ENV_PLANNER_MAX_TOKENS = "BIDMATE_PLANNER_MAX_TOKENS"
ENV_PLANNER_MAX_ITERATIONS = "BIDMATE_PLANNER_MAX_ITERATIONS"
ENV_PLANNER_MAX_LATENCY_MS = "BIDMATE_PLANNER_MAX_LATENCY_MS"

DEFAULT_PLANNER_BACKEND = "static"
# Sonnet is the right cost/quality point for single-step planning decisions.
DEFAULT_PLANNER_MODEL = "claude-sonnet-4-6"
DEFAULT_PLANNER_MAX_TOKENS = 1024
# ADR 0041 budget cap defaults
DEFAULT_MAX_ITERATIONS = 5
DEFAULT_MAX_LATENCY_MS = 8000

_REQUIRED_META_KEYS = frozenset(
    {"backend", "model", "fell_back", "fallback_reason", "latency_ms"}
)

_ABSTAIN_ACTION: dict[str, Any] = {"tool": "abstain", "args": {"reason": "planner_error"}}


@runtime_checkable
class Planner(Protocol):
    """Pluggable next-action planning stage for the ReAct agent loop.

    Given the current query analysis, prior attempt history, and the
    remaining compute budget, ``plan_next`` returns the action the
    orchestration loop should execute next.

    Implementations must NEVER raise; on backend failure they must return
    an abstain action with ``meta["fell_back"]`` set, preserving the ADR
    0003 answer contract (``status: insufficient``) as the fallback path.
    """

    def plan_next(
        self,
        *,
        analysis: dict[str, Any],
        history: list[dict[str, Any]],
        budget: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return ``(next_action, meta)``.

        ``next_action`` — ``{"tool": <name>, "args": {...}}`` where
        ``<name>`` is one of the registered tool names or ``"abstain"``.
        ``args`` for ``retrieve_evidence`` is the plan dict produced by
        ``rag_query.make_plan``; ``args`` for ``abstain`` carries a
        ``reason`` string.

        ``meta`` — ``{"backend": str, "model": str | None,
        "fell_back": bool, "fallback_reason": str | None,
        "latency_ms": float}``.
        """
        ...


class StaticPlanner:
    """Default ``Planner`` — delegates to ``rag_query.make_plan``.

    Deterministic, no LLM call, no env-var read.  ``history`` and
    ``budget`` are accepted but ignored so the Protocol contract is
    satisfied; ``StaticPlanner`` makes a single-pass decision identical
    to the current pipeline.

    ``preset_kwargs`` pre-seeds the ``make_plan`` keyword arguments
    (e.g. ``rerank=True``, ``metadata_first=True``) so PR-C can
    instantiate ``StaticPlanner`` with preset-specific defaults and still
    reach the same code path as the existing pipeline does today.

    Never-raise: ``make_plan`` validation errors (bad retrieval_mode,
    invalid rrf_k, etc.) are caught and an abstain action is returned
    with ``meta["fell_back"] = True``.  Programming errors — wrong type
    for ``analysis`` — are allowed to propagate to surface bugs early.
    """

    def __init__(self, *, preset_kwargs: dict[str, Any] | None = None) -> None:
        self._preset_kwargs: dict[str, Any] = preset_kwargs or {}

    def plan_next(
        self,
        *,
        analysis: dict[str, Any],
        history: list[dict[str, Any]],
        budget: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        t0 = time.perf_counter()
        try:
            from rag_query import make_plan as _make_plan

            plan_dict = _make_plan(analysis, **self._preset_kwargs)
            next_action: dict[str, Any] = {"tool": "retrieve_evidence", "args": plan_dict}
            fell_back = False
            fallback_reason = None
        except Exception as exc:
            next_action = {
                "tool": "abstain",
                "args": {"reason": f"planner_error: {type(exc).__name__}: {exc}"},
            }
            fell_back = True
            fallback_reason = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - t0) * 1000.0
        meta: dict[str, Any] = {
            "backend": "static",
            "model": None,
            "fell_back": fell_back,
            "fallback_reason": fallback_reason,
            "latency_ms": latency_ms,
        }
        return next_action, meta


class LLMPlanner:
    """Opt-in ``Planner`` — Anthropic SDK multi-turn planning (ADR 0040).

    On each ``plan_next`` call the LLM receives the current analysis,
    prior attempt history, and remaining budget, then chooses the next
    action from the registered tool set (``AGENT_REACT_TOOLS``).

    Activation: set ``BIDMATE_PLANNER_BACKEND=anthropic``.  The default
    is ``"static"`` so CI and smoke runs are LLM-free and deterministic.

    Never-raise: every failure path (missing SDK, missing API key, parse
    error, API error) falls back to ``StaticPlanner`` with
    ``meta["fell_back"] = True``.  This preserves ADR 0003 answer
    contract reachability — the agent loop always gets a valid action.

    ADR 0041 budget cap: callers (react_loop node) are responsible for
    passing ``budget`` with ``iterations_left``, ``tokens_left``, and
    ``ms_left`` populated; ``LLMPlanner`` does not enforce caps itself
    but reads them for the user prompt so the LLM can self-regulate.
    """

    def __init__(
        self,
        *,
        preset_kwargs: dict[str, Any] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self._preset_kwargs: dict[str, Any] = preset_kwargs or {}
        self._model = model or os.environ.get(ENV_PLANNER_MODEL, DEFAULT_PLANNER_MODEL)
        self._max_tokens = max_tokens or int(
            os.environ.get(ENV_PLANNER_MAX_TOKENS, DEFAULT_PLANNER_MAX_TOKENS)
        )
        self._static_fallback = StaticPlanner(preset_kwargs=preset_kwargs)

    def plan_next(
        self,
        *,
        analysis: dict[str, Any],
        history: list[dict[str, Any]],
        budget: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        t0 = time.perf_counter()
        try:
            import anthropic  # type: ignore[import-not-found]
            from rag_agent_tools import AGENT_REACT_SYSTEM_PROMPT, AGENT_REACT_TOOLS

            client = anthropic.Anthropic()
            user_content = (
                f"Query analysis:\n{json.dumps(analysis, ensure_ascii=False, indent=2)}\n\n"
                f"Previous attempts ({len(history)}):\n"
                f"{json.dumps(history, ensure_ascii=False, indent=2)}\n\n"
                f"Budget remaining: {json.dumps(budget, ensure_ascii=False)}\n\n"
                "Select the next action to retrieve grounded evidence for the query."
            )
            response = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=AGENT_REACT_SYSTEM_PROMPT,
                tools=AGENT_REACT_TOOLS,
                tool_choice={"type": "any"},
                messages=[{"role": "user", "content": user_content}],
            )
            # Extract the first tool_use block.
            tool_block = next(
                (b for b in response.content if getattr(b, "type", None) == "tool_use"),
                None,
            )
            if tool_block is None:
                raise ValueError("LLM returned no tool_use block")
            next_action: dict[str, Any] = {
                "tool": tool_block.name,
                "args": dict(tool_block.input or {}),
            }
            latency_ms = (time.perf_counter() - t0) * 1000.0
            meta: dict[str, Any] = {
                "backend": "anthropic",
                "model": self._model,
                "fell_back": False,
                "fallback_reason": None,
                "latency_ms": latency_ms,
                "input_tokens": getattr(response.usage, "input_tokens", None),
                "output_tokens": getattr(response.usage, "output_tokens", None),
            }
            return next_action, meta
        except Exception as exc:
            # Fall back to StaticPlanner — never-raise contract.
            fallback_action, fallback_meta = self._static_fallback.plan_next(
                analysis=analysis, history=history, budget=budget
            )
            latency_ms = (time.perf_counter() - t0) * 1000.0
            fallback_meta.update(
                {
                    "backend": "anthropic_fallback",
                    "fell_back": True,
                    "fallback_reason": f"{type(exc).__name__}: {exc}",
                    "latency_ms": latency_ms,
                }
            )
            return fallback_action, fallback_meta


def default_planner(*, preset_kwargs: dict[str, Any] | None = None) -> Planner:
    """Factory for the planner the agent loop uses.

    Dispatches on ``BIDMATE_PLANNER_BACKEND`` (mirrors
    ``BIDMATE_QUERY_EXPANSION_BACKEND`` in ``rag_query_expansion.py``):

    - ``"static"`` (default) → :class:`StaticPlanner` — deterministic,
      no LLM call, CI-safe.
    - ``"anthropic"`` → :class:`LLMPlanner` — Anthropic SDK multi-turn
      planning (ADR 0040/0041).

    Returns a fresh instance each call so test code can swap
    implementations without module-level state side effects.
    """
    backend = os.environ.get(ENV_PLANNER_BACKEND, DEFAULT_PLANNER_BACKEND).strip().lower()
    if backend == "anthropic":
        return LLMPlanner(preset_kwargs=preset_kwargs)
    return StaticPlanner(preset_kwargs=preset_kwargs)
