"""Planner Protocol — pluggable next-action planning stage (#659).

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

import time
from typing import Any, Protocol, runtime_checkable

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


def default_planner(*, preset_kwargs: dict[str, Any] | None = None) -> Planner:
    """The planner the agent loop uses unless a future plan-level override
    is wired in.  Returns a fresh ``StaticPlanner`` instance so callers
    can swap implementations in tests without module-level state.

    When ``LLMPlanner`` lands (PR-C), this function gains a
    ``BIDMATE_PLANNER_BACKEND`` env-var read — identical to the
    ``BIDMATE_QUERY_EXPANSION_BACKEND`` dispatch in
    ``rag_query_expansion.py``.
    """
    return StaticPlanner(preset_kwargs=preset_kwargs)
