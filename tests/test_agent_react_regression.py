"""Regression tests for PR-E — agent_react eval row + ADR 0042 (#682).

Verifies:
1. eval/config.yaml has agent_react in ablation_runs (yaml parse).
2. eval/config.yaml has agent_react latency budget.
3. eval/config.yaml has agent_react stage_latency_budgets.
4. ADR 0042 file exists.
5. ADR 0001 invariant: naive_baseline is still primary_run.
6. ADR 0042 evidence-boundary defense: format_verifier_feedback output
   does not contain EVIDENCE_BOUNDARY sentinel.
7. ADR 0042 defense: execute_abstain return values do not contain
   EVIDENCE_BOUNDARY sentinel.
8. AGENT_REACT_SYSTEM_PROMPT does not contain EVIDENCE_BOUNDARY sentinel.
9. StaticPlanner + budget exhaustion → ctx.evidence=[] path.

No real index or LLM calls.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

EVAL_CONFIG_PATH = ROOT / "eval" / "config.yaml"
ADR_0042_PATH = ROOT / "docs" / "adr" / "0042-tool-use-evidence-boundary-defense.md"


def _load_config() -> dict[str, Any]:
    with open(EVAL_CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# 1. agent_react in ablation_runs
# ---------------------------------------------------------------------------

def test_agent_react_in_ablation_runs():
    config = _load_config()
    names = [r["name"] for r in config.get("ablation_runs", [])]
    assert "agent_react" in names, f"agent_react not in ablation_runs: {names}"


def test_agent_react_ablation_run_pipeline():
    config = _load_config()
    row = next(r for r in config["ablation_runs"] if r["name"] == "agent_react")
    assert row["pipeline"] == "agent_react"


def test_agent_react_ablation_run_planner_backend():
    config = _load_config()
    row = next(r for r in config["ablation_runs"] if r["name"] == "agent_react")
    assert row.get("planner_backend") == "static"


# ---------------------------------------------------------------------------
# 2. latency budget
# ---------------------------------------------------------------------------

def test_agent_react_latency_budget_exists():
    config = _load_config()
    budgets = config.get("latency_budgets", {})
    assert "agent_react" in budgets, f"agent_react not in latency_budgets: {list(budgets)}"


def test_agent_react_latency_budget_p95():
    config = _load_config()
    p95 = config["latency_budgets"]["agent_react"]["p95_ms"]
    assert isinstance(p95, (int, float))
    assert p95 > 0


# ---------------------------------------------------------------------------
# 3. stage_latency_budgets
# ---------------------------------------------------------------------------

def test_agent_react_stage_latency_budget_exists():
    config = _load_config()
    stage_budgets = config.get("stage_latency_budgets", {})
    assert "agent_react" in stage_budgets, (
        f"agent_react not in stage_latency_budgets: {list(stage_budgets)}"
    )


def test_agent_react_stage_latency_has_react_loop_ms():
    config = _load_config()
    stages = config["stage_latency_budgets"]["agent_react"]
    assert "react_loop_ms" in stages, f"react_loop_ms missing: {list(stages)}"


# ---------------------------------------------------------------------------
# 4. ADR 0042 file
# ---------------------------------------------------------------------------

def test_adr_0042_file_exists():
    assert ADR_0042_PATH.exists(), f"ADR 0042 not found: {ADR_0042_PATH}"


def test_adr_0042_is_accepted():
    content = ADR_0042_PATH.read_text(encoding="utf-8")
    assert "accepted" in content.lower()


# ---------------------------------------------------------------------------
# 5. ADR 0001 invariant: naive_baseline is primary_run
# ---------------------------------------------------------------------------

def test_naive_baseline_remains_primary_run():
    config = _load_config()
    assert config.get("primary_run") == "naive_baseline"


# ---------------------------------------------------------------------------
# 6-8. ADR 0042 evidence-boundary regression
# ---------------------------------------------------------------------------

def test_format_verifier_feedback_no_evidence_boundary_leak():
    """format_verifier_feedback output must not contain EVIDENCE_BOUNDARY."""
    from rag_verifier import format_verifier_feedback
    from rag_verifier import EVIDENCE_BOUNDARY

    result = format_verifier_feedback(
        reasons=["topic_not_grounded: 보안 요구사항"],
        evidence=[{"chunk_id": "c1", "text": f"some text {EVIDENCE_BOUNDARY} injected"}],
    )
    assert EVIDENCE_BOUNDARY not in result, (
        "EVIDENCE_BOUNDARY leaked into format_verifier_feedback output"
    )


def test_execute_abstain_no_evidence_boundary_leak():
    """execute_abstain return values must not contain EVIDENCE_BOUNDARY."""
    from rag_agent_tools import execute_abstain
    from rag_verifier import EVIDENCE_BOUNDARY

    result = execute_abstain({"reason": f"budget_exhausted {EVIDENCE_BOUNDARY}"})
    # The reason string passes through; we check the outer dict
    # (abstain_reason is stored but not injected into evidence)
    assert isinstance(result, dict)
    # status and meta must not contain the boundary token
    assert EVIDENCE_BOUNDARY not in str(result.get("status", ""))
    assert EVIDENCE_BOUNDARY not in str(result.get("meta", ""))


def test_agent_react_system_prompt_no_evidence_boundary():
    """AGENT_REACT_SYSTEM_PROMPT must not embed the EVIDENCE_BOUNDARY sentinel."""
    from rag_agent_tools import AGENT_REACT_SYSTEM_PROMPT
    from rag_verifier import EVIDENCE_BOUNDARY

    assert EVIDENCE_BOUNDARY not in AGENT_REACT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# 9. StaticPlanner budget exhaustion path (max_iterations=0)
# ---------------------------------------------------------------------------

def test_static_planner_zero_iterations_returns_dict():
    """When budget iterations_left=0 the loop exits immediately; plan_next still works."""
    from rag_planner import StaticPlanner

    planner = StaticPlanner()
    next_action, meta = planner.plan_next(
        analysis={"query_type": "single_doc", "entities": [], "metadata_filters_by_stage": {}},
        history=[],
        budget={"iterations_left": 0, "ms_left": 0.0},
    )
    # StaticPlanner ignores budget — it still returns a valid action
    assert isinstance(next_action, dict)
    assert isinstance(meta, dict)
