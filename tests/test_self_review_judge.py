#!/usr/bin/env python3
"""Regression tests for eval/judges/self_review_judge.py (ADR 0064).

Covers the deterministic stub backend, the ✓/△/✗ ↔ JUDGE_STATUSES mapping,
agreement aggregation against operator verdicts, and the three self-pass
guards (time separation, hook-fire silence, low sample).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_HOOKS = ROOT / "scripts" / "claude-hooks"
if str(SCRIPTS_HOOKS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_HOOKS))

from eval.judges.self_review_judge import (  # noqa: E402
    AXIS_KEYS,
    VERDICT_TO_STATUS,
    _weighted_kappa,
    judge_self_review,
    stub_verdicts,
)
from _self_review import (  # noqa: E402
    assemble_stats,
    compute_evidence_age_days,
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
        # Time-separated evidence by default (≥1 day) so the baseline grades
        # to ✓; guard tests override this. A missing key is exercised
        # separately (test_missing_evidence_age_downgrades_all_passes).
        "evidence_age_days": 2.0,
    }
    stats.update(overrides)
    return stats


def test_stub_backend_deterministic():
    """Same stats → identical verdicts across calls (ADR 0064 reproducibility)."""
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
    # ordinal weighted κ is also reported and = 1.0 on perfect agreement
    assert agreement["weighted_kappa_linear"] == 1.0
    assert agreement["weighted_kappa_quadratic"] == 1.0


def test_weighted_kappa_ordinal_distance():
    """Weighted κ penalises adjacent (✓↔△) less than opposite (✓↔✗) disagreement.

    Three anchors (statuses, not verdicts):
    - perfect agreement → 1.0 both modes;
    - pure opposite inversion (all ✓↔✗) → -1.0 both (weighting is irrelevant
      at the extremes, so it equals the unweighted κ);
    - a mixed case where unweighted κ = 0 but weighted κ is negative — i.e.
      the ordinal distance changes the verdict, which is the whole point.
    """
    sup, par, ins = "supported", "partial", "insufficient"
    # perfect (with marginal spread so expected disagreement > 0)
    perfect = [sup, par, ins]
    assert _weighted_kappa(perfect, perfect, mode="linear") == 1.0
    assert _weighted_kappa(perfect, perfect, mode="quadratic") == 1.0
    # pure opposite inversion → both weighted κ = unweighted = -1.0
    inv_j, inv_h = [sup, sup, ins, ins], [ins, ins, sup, sup]
    assert _weighted_kappa(inv_j, inv_h, mode="linear") == pytest.approx(-1.0)
    assert _weighted_kappa(inv_j, inv_h, mode="quadratic") == pytest.approx(-1.0)
    # mixed: unweighted κ = 0, but linear = -1/7, quadratic = -1/3
    mix_j, mix_h = [sup, par, ins, sup], [par, par, par, ins]
    assert _weighted_kappa(mix_j, mix_h, mode="linear") == pytest.approx(-1 / 7)
    assert _weighted_kappa(mix_j, mix_h, mode="quadratic") == pytest.approx(-1 / 3)


def test_agreement_absent_without_operator():
    """No operator verdicts → no agreement block (cross-rating only)."""
    _, aggregate = judge_self_review(_base_stats(), None, backend="stub")
    assert "agreement" not in aggregate
    assert aggregate["backend"] == "stub"


def test_evidence_age_under_24h_forces_partial():
    """ADR 0064 guard: evidence_age < 1.0 day downgrades every ✓ → △."""
    guarded = stub_verdicts(_base_stats(evidence_age_days=0.5))
    assert all(v == "△" for v in guarded.values()), guarded
    # the same stats with age ≥ 1.0 stay ✓ (guard is the only difference)
    ungated = stub_verdicts(_base_stats(evidence_age_days=2.0))
    assert all(v == "✓" for v in ungated.values()), ungated


def test_hook_fires_zero_forces_fail():
    """ADR 0064 guard: axis #3 fires=0 → ✗ (silence is not a pass)."""
    stats = _base_stats(
        governance_hooks={
            "pretooluse_loadbearing_fires": 0,
            "fires_by_action": {},
        }
    )
    assert stub_verdicts(stats)["axis_3_governance_roi"] == "✗"


def test_axis_2_low_sample_forces_partial():
    """ADR 0064 guard: axis #2 prs_evaluated < 10 → △ (sample too small)."""
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


def _gov_with_memory_lines(aware: int, blocked: int) -> dict:
    """governance_hooks block keeping axis #3 ✓ + a 5-A memory_lines signal."""
    return {
        "pretooluse_loadbearing_fires": 20,
        "fires_by_action": {"aware": 18, "ok": 2},
        "memory_lines": {"aware": aware, "blocked": blocked},
    }


def test_axis_5_absent_memory_lines_falls_back_to_5b():
    """5-A field absent (old collector) → grade on 5-B alone (✓ here)."""
    # _base_stats has no governance_hooks.memory_lines key.
    assert stub_verdicts(_base_stats())["axis_5_memory_hygiene"] == "✓"


def test_axis_5_blocked_forces_fail():
    """5-A: blocked ≥1 (index edit refused) → ✗, dominates a ✓ 5-B."""
    stats = _base_stats(governance_hooks=_gov_with_memory_lines(aware=0, blocked=1))
    assert stub_verdicts(stats)["axis_5_memory_hygiene"] == "✗"


def test_axis_5_zero_count_is_partial():
    """5-A: present but count=0 → △ (측정 부재), combined with ✓ 5-B → △."""
    stats = _base_stats(governance_hooks=_gov_with_memory_lines(aware=0, blocked=0))
    assert stub_verdicts(stats)["axis_5_memory_hygiene"] == "△"


def test_axis_5_high_aware_is_partial():
    """5-A: blocked=0 + aware≥3 → △, combined with ✓ 5-B → △."""
    stats = _base_stats(governance_hooks=_gov_with_memory_lines(aware=3, blocked=0))
    assert stub_verdicts(stats)["axis_5_memory_hygiene"] == "△"


def test_axis_5_both_subsignals_pass():
    """5-A ✓ (blocked=0 + aware≤2) AND 5-B ✓ → combined ✓."""
    stats = _base_stats(governance_hooks=_gov_with_memory_lines(aware=2, blocked=0))
    assert stub_verdicts(stats)["axis_5_memory_hygiene"] == "✓"


def test_openai_backend_applies_time_separation_guard(monkeypatch):
    """ADR 0064 backend symmetry: the openai backend's raw verdicts pass
    through _guard_downgrade too (evidence_age_days < 1.0 → ✓→△), matching
    the stub path.

    Regression for the asymmetry deferred out of PR #1187: _guard_downgrade
    was applied only inside stub_verdicts, so an all-✓ openai verdict on
    same-day evidence stayed ✓ while stub forced it to △. We monkeypatch
    openai_verdicts to a fixed all-✓ dict so the assertion isolates the
    guard, not the (unmocked) LLM call.
    """
    all_pass = {
        "axis_1_context_efficiency": "✓",
        "axis_2_agent_delegation": "✓",
        "axis_3_governance_roi": "✓",
        "axis_4_cycle_time": "✓",
        "axis_5_memory_hygiene": "✓",
    }
    monkeypatch.setattr(
        "eval.judges.self_review_judge.openai_verdicts",
        lambda *_: dict(all_pass),
    )
    # same-day evidence (< 1.0 day) → the guard must fire on the openai path.
    _, agg = judge_self_review(
        _base_stats(evidence_age_days=0.5), backend="openai_compatible"
    )
    assert agg["judge_verdicts"] == {k: "△" for k in all_pass}, agg
    # control: age ≥ 1.0 leaves the verdicts untouched, proving the downgrade
    # is the time-separation guard and not an unconditional rewrite.
    _, agg_old = judge_self_review(
        _base_stats(evidence_age_days=2.0), backend="openai_compatible"
    )
    assert agg_old["judge_verdicts"] == all_pass, agg_old


def test_unknown_backend_raises():
    """Unknown backend → ValueError."""
    with pytest.raises(ValueError):
        judge_self_review(_base_stats(), backend="bogus")


# --- Bug 1: incomplete/invalid operator verdicts no longer pass the gate ---

_OPERATOR_FULL = {key: "✓" for key in AXIS_KEYS}


def test_agreement_spans_all_axes():
    """A complete operator file → agreement over all 5 axes (n == len(AXIS_KEYS))."""
    _, aggregate = judge_self_review(
        _base_stats(), dict(_OPERATOR_FULL), backend="stub"
    )
    assert aggregate["agreement"]["n"] == len(AXIS_KEYS)


def test_partial_operator_raises():
    """1-of-5 operator file raises, not a silent n=1 / κ=1.0 / passes=True.

    This is the core Bug-1 regression: before the fix, a single valid axis
    survived the filter and hit compute_agreement's perfect-agreement special
    case, passing the gate with 4 axes unverified.
    """
    partial = {"axis_1_context_efficiency": "✓"}
    with pytest.raises(ValueError):
        judge_self_review(_base_stats(), partial, backend="stub")


def test_typoed_operator_value_raises():
    """An out-of-vocabulary verdict raises rather than being silently dropped."""
    bad = dict(_OPERATOR_FULL)
    bad["axis_3_governance_roi"] = "yes"  # not one of ✓/△/✗
    with pytest.raises(ValueError):
        judge_self_review(_base_stats(), bad, backend="stub")


def test_extra_key_operator_raises():
    """An unexpected extra axis key raises (strict exactly-5-axes contract)."""
    extra = dict(_OPERATOR_FULL)
    extra["axis_6_made_up"] = "✓"
    with pytest.raises(ValueError):
        judge_self_review(_base_stats(), extra, backend="stub")


def test_empty_operator_dict_raises():
    """An explicit empty operator object raises (missing all axes), not a skip.

    None still means 'no operator provided' (no agreement block); {} is a
    parse mistake and must fail loudly.
    """
    with pytest.raises(ValueError):
        judge_self_review(_base_stats(), {}, backend="stub")


# --- Bug 2: missing evidence_age_days is treated conservatively (downgrade) ---


def test_missing_evidence_age_downgrades_all_passes():
    """A stats dict with no evidence_age_days downgrades every ✓ → △.

    Regression for the dead-guard path: when the producer emits no datable
    evidence age, the guard must default to the conservative (cannot-confirm)
    branch rather than no-op and let same-day evidence promote to ✓.
    """
    stats = _base_stats()
    del stats["evidence_age_days"]
    verdicts = stub_verdicts(stats)
    assert all(v == "△" for v in verdicts.values()), verdicts


def test_compute_evidence_age_days_uses_freshest_timestamp():
    """Age is measured from the newest datable evidence across all sources."""
    now = datetime(2026, 5, 21, tzinfo=timezone.utc)
    stats = {
        "git": {"prs_merged": [{"date": "2026-05-01"}, {"date": "2026-05-20"}]},
        "memory": {"files": [{"mtime": "2026-05-10"}]},
        "governance_hooks": {
            "rule_to_automation_lag_days": [{"accepted_date": "2026-04-15"}]
        },
        "pr_diff_stats": [],
    }
    # freshest = 2026-05-20 → exactly 1 day before now
    assert compute_evidence_age_days(stats, now=now) == pytest.approx(1.0)


def test_compute_evidence_age_days_handles_iso_merged_at():
    """gh merged_at (full ISO with Z) is parsed alongside date-only fields."""
    now = datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)
    stats = {
        "git": {"prs_merged": [{"date": "2026-05-01"}]},
        "pr_diff_stats": [{"merged_at": "2026-05-21T00:00:00Z"}],
    }
    # freshest = 2026-05-21T00:00Z, now = +12h → 0.5 day
    assert compute_evidence_age_days(stats, now=now) == pytest.approx(0.5)


def test_compute_evidence_age_days_none_when_no_dates():
    """No datable evidence → None (the judge then downgrades conservatively)."""
    now = datetime(2026, 5, 21, tzinfo=timezone.utc)
    assert compute_evidence_age_days({}, now=now) is None
    assert (
        compute_evidence_age_days(
            {"git": {"prs_merged": []}, "memory": {"files": []}}, now=now
        )
        is None
    )


def test_compute_evidence_age_days_floors_at_zero():
    """A future timestamp (clock skew) floors to 0.0, never negative."""
    now = datetime(2026, 5, 21, tzinfo=timezone.utc)
    stats = {"git": {"prs_merged": [{"date": "2026-05-25"}]}}
    assert compute_evidence_age_days(stats, now=now) == 0.0


def test_compute_evidence_age_days_same_day_under_one():
    """Same-day evidence → age < 1.0 so the time-separation guard fires."""
    now = datetime(2026, 5, 21, 18, 0, tzinfo=timezone.utc)
    stats = {"git": {"prs_merged": [{"date": "2026-05-21"}]}}
    assert compute_evidence_age_days(stats, now=now) < 1.0


def test_assemble_stats_emits_evidence_age_and_judge_consumes_it(tmp_path):
    """Real assemble_stats() shape carries evidence_age_days through the judge.

    Integration regression for the missing producer (Bug 2): before the fix,
    assemble_stats never emitted the key, so ``"evidence_age_days" in stats``
    would have been False and this test would have failed. Empty
    transcripts/memory globs isolate the git-only path (gh fails soft to []).
    """
    stats = assemble_stats(
        quarter="Q2-2026",
        transcripts_glob=str(tmp_path / "none" / "*.jsonl"),
        memory_dir=str(tmp_path / "no-memory"),
        repo=str(ROOT),
    )
    assert "evidence_age_days" in stats
    assert stats["evidence_age_days"] is None or isinstance(
        stats["evidence_age_days"], float
    )
    operator = {key: "△" for key in AXIS_KEYS}
    _, aggregate = judge_self_review(stats, operator, backend="stub")
    assert aggregate["agreement"]["n"] == len(AXIS_KEYS)
