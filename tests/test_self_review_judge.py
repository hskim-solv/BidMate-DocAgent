#!/usr/bin/env python3
"""Regression tests for eval/judges/self_review_judge.py (ADR 0060).

Covers the deterministic stub backend, the ✓/△/✗ ↔ JUDGE_STATUSES mapping,
agreement aggregation against operator verdicts, and the three self-pass
guards (time separation, hook-fire silence, low sample).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.judges.self_review_judge import (  # noqa: E402
    VERDICT_TO_STATUS,
    judge_self_review,
    stub_verdicts,
)


def _base_stats(**overrides):
    """Minimal stats dict with every signal at a passing (✓) default."""
    stats = {
        "sessions": {
            "count": 10,
            "tool_call_distribution": {"Read": 50},  # 5/session ≤ 10
            "agent_delegations": {"Explore": 5},  # ≥ 2
        },
        "governance_hooks": {
            "pretooluse_loadbearing_fires": 20,
            "fires_by_action": {"aware": 18, "ok": 2},  # 2 distinct actions
        },
        "axis_2_plan_subagent_skip_rate": {
            "skip_rate": 0.1,
            "prs_evaluated": 30,
        },
        "axis_4_cycle_time": {
            "adr_lag_days": {"mean": 3.0},
            "pr_turnaround_hours": {"mean": 24.0},
        },
        "axis_5_memory_hygiene": {"content_freshness": {"fresh_rate": 0.8}},
    }
    stats.update(overrides)
    return stats


def test_stub_backend_deterministic():
    """Same stats → identical verdicts across calls (ADR 0060 reproducibility)."""
    stats = _base_stats()
    v1 = stub_verdicts(stats)
    v2 = stub_verdicts(stats)
    assert v1 == v2
    # all-passing baseline → every axis ✓
    assert all(v == "✓" for v in v1.values()), v1


def test_verdict_status_mapping():
    """✓/△/✗ map onto JUDGE_STATUSES so judge_agreement is reusable."""
    assert VERDICT_TO_STATUS == {
        "✓": "supported",
        "△": "partial",
        "✗": "insufficient",
    }


def test_agreement_against_operator():
    """judge_self_review emits a compute_agreement block when operator given."""
    stats = _base_stats()
    operator = {key: "✓" for key in (
        "axis_1_context_efficiency",
        "axis_2_agent_delegation",
        "axis_3_governance_roi",
        "axis_4_cycle_time",
        "axis_5_memory_hygiene",
    )}
    local, aggregate = judge_self_review(stats, operator, backend="stub")
    assert set(local) == set(operator)
    assert "agreement" in aggregate
    agreement = aggregate["agreement"]
    assert agreement["n"] == 5
    # all-✓ stub vs all-✓ operator → perfect agreement
    assert agreement["cohens_kappa"] == 1.0
    assert agreement["passes"] is True


def test_agreement_absent_without_operator():
    """No operator verdicts → no agreement block (cross-rating only)."""
    _, aggregate = judge_self_review(_base_stats(), None, backend="stub")
    assert "agreement" not in aggregate
    assert aggregate["backend"] == "stub"


def test_evidence_age_under_24h_forces_partial():
    """ADR 0060 guard: evidence_age < 1.0 day downgrades every ✓ → △."""
    guarded = stub_verdicts(_base_stats(evidence_age_days=0.5))
    assert all(v == "△" for v in guarded.values()), guarded
    # the same stats with age ≥ 1.0 stay ✓ (guard is the only difference)
    ungated = stub_verdicts(_base_stats(evidence_age_days=2.0))
    assert all(v == "✓" for v in ungated.values()), ungated


def test_hook_fires_zero_forces_fail():
    """ADR 0060 guard: axis #3 fires=0 → ✗ (silence is not a pass)."""
    stats = _base_stats(
        governance_hooks={
            "pretooluse_loadbearing_fires": 0,
            "fires_by_action": {},
        }
    )
    assert stub_verdicts(stats)["axis_3_governance_roi"] == "✗"


def test_axis_2_low_sample_forces_partial():
    """ADR 0060 guard: axis #2 prs_evaluated < 10 → △ (sample too small)."""
    stats = _base_stats(
        axis_2_plan_subagent_skip_rate={"skip_rate": 0.0, "prs_evaluated": 3}
    )
    # skip_rate 0.0 alone would be ✓, but n<10 forces △
    assert stub_verdicts(stats)["axis_2_agent_delegation"] == "△"


def test_axis_3_single_action_is_partial():
    """axis #3: fires>0 but only 1 distinct action → △ (not ✓)."""
    stats = _base_stats(
        governance_hooks={
            "pretooluse_loadbearing_fires": 9,
            "fires_by_action": {"aware": 9},  # 1 distinct action
        }
    )
    assert stub_verdicts(stats)["axis_3_governance_roi"] == "△"


def test_axis_5_null_freshness_is_fail():
    """axis #5: null content_fresh_rate → ✗ (measurement absent)."""
    stats = _base_stats(
        axis_5_memory_hygiene={"content_freshness": {"fresh_rate": None}}
    )
    assert stub_verdicts(stats)["axis_5_memory_hygiene"] == "✗"


def test_unknown_backend_raises():
    """Unknown backend → ValueError."""
    with pytest.raises(ValueError):
        judge_self_review(_base_stats(), backend="bogus")
