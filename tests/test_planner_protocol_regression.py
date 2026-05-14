"""Regression tests for rag_planner — Planner Protocol + StaticPlanner (#659).

Verifies:
1. Protocol structural conformance (isinstance checks).
2. StaticPlanner happy path — next_action / meta structure.
3. StaticPlanner never-raise contract — bad preset_kwargs yields abstain.
4. StaticPlanner preset_kwargs passthrough — args land in make_plan.
5. default_planner() factory returns a Planner instance.

No real index or LLM calls; all paths are deterministic.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_planner import (  # noqa: E402
    Planner,
    StaticPlanner,
    _REQUIRED_META_KEYS,
    default_planner,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _analysis(query_type: str = "single_doc") -> dict[str, Any]:
    """Minimal analysis dict accepted by make_plan."""
    return {
        "query_type": query_type,
        "entities": [],
        "metadata_filters_by_stage": {},
    }


def _budget() -> dict[str, Any]:
    return {"iterations_left": 5, "tokens_left": 4096, "ms_left": 8000}


# ---------------------------------------------------------------------------
# 1. Protocol conformance
# ---------------------------------------------------------------------------

def test_static_planner_is_planner():
    assert isinstance(StaticPlanner(), Planner)


def test_default_planner_is_planner():
    assert isinstance(default_planner(), Planner)


# ---------------------------------------------------------------------------
# 2. StaticPlanner happy path
# ---------------------------------------------------------------------------

def test_static_planner_returns_retrieve_action():
    planner = StaticPlanner()
    next_action, meta = planner.plan_next(
        analysis=_analysis(),
        history=[],
        budget=_budget(),
    )
    assert next_action["tool"] == "retrieve_evidence", next_action
    assert "args" in next_action
    assert isinstance(next_action["args"], dict)


def test_static_planner_meta_structure():
    planner = StaticPlanner()
    _, meta = planner.plan_next(
        analysis=_analysis(),
        history=[],
        budget=_budget(),
    )
    missing = _REQUIRED_META_KEYS - meta.keys()
    assert not missing, f"meta is missing keys: {missing}"
    assert meta["backend"] == "static"
    assert meta["model"] is None
    assert meta["fell_back"] is False
    assert meta["fallback_reason"] is None
    assert isinstance(meta["latency_ms"], float)


def test_static_planner_history_and_budget_ignored():
    planner = StaticPlanner()
    # Non-empty history / budget must not raise or change next_action.tool
    next_action, meta = planner.plan_next(
        analysis=_analysis(),
        history=[{"attempt": 1, "verifier_feedback": "topic_not_grounded"}],
        budget={"iterations_left": 0, "tokens_left": 0, "ms_left": 0},
    )
    assert next_action["tool"] == "retrieve_evidence"
    assert meta["fell_back"] is False


# ---------------------------------------------------------------------------
# 3. Never-raise contract — bad preset_kwargs → abstain
# ---------------------------------------------------------------------------

def test_static_planner_invalid_retrieval_mode_abstains():
    planner = StaticPlanner(preset_kwargs={"retrieval_mode": "INVALID_MODE"})
    next_action, meta = planner.plan_next(
        analysis=_analysis(),
        history=[],
        budget=_budget(),
    )
    assert next_action["tool"] == "abstain", next_action
    assert meta["fell_back"] is True
    assert meta["fallback_reason"] is not None


def test_static_planner_never_raises():
    planner = StaticPlanner(preset_kwargs={"rrf_k": -999})
    try:
        next_action, meta = planner.plan_next(
            analysis=_analysis(),
            history=[],
            budget=_budget(),
        )
    except Exception as exc:  # pragma: no cover
        raise AssertionError(f"plan_next raised unexpectedly: {exc}") from exc
    assert next_action["tool"] == "abstain"
    assert meta["fell_back"] is True


# ---------------------------------------------------------------------------
# 4. preset_kwargs passthrough — lands in plan dict
# ---------------------------------------------------------------------------

def test_static_planner_preset_kwargs_passthrough():
    planner = StaticPlanner(preset_kwargs={"rerank": False, "top_k": 3})
    next_action, _ = planner.plan_next(
        analysis=_analysis(),
        history=[],
        budget=_budget(),
    )
    plan_dict = next_action["args"]
    assert plan_dict.get("rerank") is False
    assert plan_dict.get("top_k") == 3


# ---------------------------------------------------------------------------
# 5. default_planner factory
# ---------------------------------------------------------------------------

def test_default_planner_factory_returns_fresh_instances():
    p1 = default_planner()
    p2 = default_planner()
    assert p1 is not p2


def test_default_planner_preset_kwargs_forwarded():
    planner = default_planner(preset_kwargs={"rerank": False})
    next_action, _ = planner.plan_next(
        analysis=_analysis(),
        history=[],
        budget=_budget(),
    )
    assert next_action["args"]["rerank"] is False
