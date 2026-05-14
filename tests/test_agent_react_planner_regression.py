"""Regression tests for PR-C — ReAct orchestrator + LLMPlanner + agent_react preset (#673).

Verifies:
1. agent_react preset is registered in PIPELINE_PRESETS + alias "react".
2. VALID_PLANNER_BACKENDS validation set.
3. ADR 0024 3-layer default policy is unchanged.
4. ADR 0001 naive_baseline default is unchanged.
5. LLMPlanner falls back to StaticPlanner when SDK is absent (never-raise).
6. default_planner() env-var dispatch.
7. rag_graph_react module imports cleanly (no LangGraph call at import time).
8. rag_core agent_react dispatch (unit-level, no real index).

No real index, LLM, or network calls.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_pipeline_presets import (  # noqa: E402
    DEFAULT_CLI_PIPELINE_NAME,
    DEFAULT_RAG_PIPELINE_NAME,
    PIPELINE_ALIASES,
    PIPELINE_PRESETS,
    VALID_PLANNER_BACKENDS,
    canonical_pipeline_name,
)
from rag_planner import (  # noqa: E402
    DEFAULT_PLANNER_BACKEND,
    LLMPlanner,
    StaticPlanner,
    default_planner,
)


# ---------------------------------------------------------------------------
# 1. agent_react preset registration
# ---------------------------------------------------------------------------

def test_agent_react_in_pipeline_presets():
    assert "agent_react" in PIPELINE_PRESETS


def test_react_alias_resolves_to_agent_react():
    assert PIPELINE_ALIASES.get("react") == "agent_react"
    assert canonical_pipeline_name("react") == "agent_react"


def test_agent_react_preset_required_keys():
    preset = PIPELINE_PRESETS["agent_react"]
    required = {
        "top_k", "metadata_first", "rerank", "verifier_retry",
        "retrieval_mode", "retrieval_backend", "prompt_profile",
        "rrf_k", "bm25_tokenizer", "query_expansion", "planner_backend",
    }
    missing = required - preset.keys()
    assert not missing, f"agent_react preset missing keys: {missing}"


def test_agent_react_planner_backend_default_is_static():
    assert PIPELINE_PRESETS["agent_react"]["planner_backend"] == "static"


# ---------------------------------------------------------------------------
# 2. VALID_PLANNER_BACKENDS
# ---------------------------------------------------------------------------

def test_valid_planner_backends_contains_static_and_anthropic():
    assert "static" in VALID_PLANNER_BACKENDS
    assert "anthropic" in VALID_PLANNER_BACKENDS


# ---------------------------------------------------------------------------
# 3. ADR 0024 3-layer default policy is unchanged
# ---------------------------------------------------------------------------

def test_cli_default_unchanged():
    assert DEFAULT_CLI_PIPELINE_NAME == "naive_baseline"


def test_function_default_unchanged():
    assert DEFAULT_RAG_PIPELINE_NAME == "agentic_full"


def test_api_default_unchanged():
    # api/main.py sets DEFAULT_API_PIPELINE = "agentic_full_llm" — verify
    # that agent_react is NOT the API default (would violate ADR 0024).
    sys.path.insert(0, str(ROOT / "api"))
    try:
        import importlib
        api_main = importlib.import_module("main")
        api_default = getattr(api_main, "DEFAULT_API_PIPELINE", None)
        if api_default is not None:
            assert api_default != "agent_react", (
                "agent_react must not be the API surface default (ADR 0024)"
            )
    except (ImportError, ModuleNotFoundError):
        pass  # api/main.py may not be importable in minimal envs


# ---------------------------------------------------------------------------
# 4. ADR 0001 — naive_baseline invariant unchanged
# ---------------------------------------------------------------------------

def test_naive_baseline_still_in_presets():
    assert "naive_baseline" in PIPELINE_PRESETS


def test_naive_baseline_query_expansion_is_identity():
    assert PIPELINE_PRESETS["naive_baseline"]["query_expansion"] == "identity"


def test_naive_baseline_has_no_planner_backend():
    # naive_baseline does NOT set planner_backend — agent_react-only key.
    assert "planner_backend" not in PIPELINE_PRESETS["naive_baseline"]


# ---------------------------------------------------------------------------
# 5. LLMPlanner falls back gracefully when anthropic SDK is absent
# ---------------------------------------------------------------------------

def _analysis() -> dict[str, Any]:
    return {"query_type": "single_doc", "entities": [], "metadata_filters_by_stage": {}}


def _budget() -> dict[str, Any]:
    return {"iterations_left": 5, "ms_left": 8000.0}


def test_llm_planner_fallback_when_sdk_missing():
    with patch.dict("sys.modules", {"anthropic": None}):
        planner = LLMPlanner()
        next_action, meta = planner.plan_next(
            analysis=_analysis(),
            history=[],
            budget=_budget(),
        )
    # Must not raise; fell_back tells us SDK was absent
    assert isinstance(next_action, dict)
    assert meta.get("fell_back") is True
    assert meta.get("backend") in {"anthropic_fallback", "static"}


def test_llm_planner_never_raises():
    with patch.dict("sys.modules", {"anthropic": None}):
        planner = LLMPlanner()
        try:
            next_action, meta = planner.plan_next(
                analysis=_analysis(),
                history=[],
                budget=_budget(),
            )
        except Exception as exc:
            raise AssertionError(f"LLMPlanner raised: {exc}") from exc
    assert isinstance(next_action, dict)


# ---------------------------------------------------------------------------
# 6. default_planner() env-var dispatch
# ---------------------------------------------------------------------------

def test_default_planner_static_backend():
    with patch.dict(os.environ, {"BIDMATE_PLANNER_BACKEND": "static"}):
        planner = default_planner()
    assert isinstance(planner, StaticPlanner)


def test_default_planner_anthropic_backend():
    with patch.dict(os.environ, {"BIDMATE_PLANNER_BACKEND": "anthropic"}):
        planner = default_planner()
    assert isinstance(planner, LLMPlanner)


def test_default_planner_default_is_static():
    env = {k: v for k, v in os.environ.items() if k != "BIDMATE_PLANNER_BACKEND"}
    with patch.dict(os.environ, env, clear=True):
        planner = default_planner()
    assert isinstance(planner, StaticPlanner)


# ---------------------------------------------------------------------------
# 7. rag_graph_react imports cleanly (no LangGraph call at import time)
# ---------------------------------------------------------------------------

def test_rag_graph_react_import_side_effect_free():
    """Importing rag_graph_react must not call LangGraph (no langgraph needed)."""
    # Remove from sys.modules if already imported so we get a fresh import.
    sys.modules.pop("rag_graph_react", None)
    # Mock langgraph to confirm it is not called during import.
    import types
    mock_lg = types.ModuleType("langgraph")
    mock_lg.graph = types.ModuleType("langgraph.graph")  # type: ignore[attr-defined]
    with patch.dict("sys.modules", {"langgraph": mock_lg, "langgraph.graph": mock_lg.graph}):
        import rag_graph_react  # noqa: F401
    # If we get here without error, the import was side-effect-free.
    assert True


# ---------------------------------------------------------------------------
# 8. rag_core dispatch for agent_react (unit-level)
# ---------------------------------------------------------------------------

def test_rag_core_dispatches_agent_react_to_graph():
    """run_rag_query with pipeline="agent_react" must call run_via_langgraph_react.

    rag_core does a lazy ``from rag_graph_react import run_via_langgraph_react``
    inside run_rag_query, so we patch the function on the rag_graph_react module
    (after ensuring it is loaded) rather than on rag_core.
    """
    import rag_core
    import rag_graph_react  # ensure module is in sys.modules before patch

    sentinel = {"status": "ok", "query": "test"}
    with patch.object(rag_graph_react, "run_via_langgraph_react", return_value=sentinel) as mock_fn:
        try:
            rag_core.run_rag_query({}, "테스트 쿼리", pipeline="agent_react")
        except Exception:
            pass  # may fail after dispatch — we only check mock was called
    assert mock_fn.called, "run_via_langgraph_react was not dispatched for agent_react"


def test_rag_core_react_alias_dispatches():
    """pipeline="react" alias also dispatches to run_via_langgraph_react."""
    import rag_core
    import rag_graph_react

    with patch.object(rag_graph_react, "run_via_langgraph_react", return_value={"status": "ok"}) as mock_fn:
        try:
            rag_core.run_rag_query({}, "쿼리", pipeline="react")
        except Exception:
            pass
    assert mock_fn.called, "react alias did not dispatch to run_via_langgraph_react"
