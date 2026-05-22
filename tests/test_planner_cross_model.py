"""Phase 1.5 cross-model unit tests (issue #1291).

Pure-function tests for tier classification, the fallback action table, and the
strict-Jaccard secondary metric. No network — semantic_set_match (ko-sroberta)
is exercised in the live re-score path, not here.
"""
from __future__ import annotations

from eval.planner_phase1_cross_model import _FALLBACK, _jaccard_strict, classify_tier


def test_classify_tier_high():
    tier, action = classify_tier(0.10)
    assert tier == "high"
    assert action == _FALLBACK["high"]


def test_classify_tier_boundary_15_is_high():
    assert classify_tier(0.15)[0] == "high"


def test_classify_tier_medium():
    tier, action = classify_tier(0.27)
    assert tier == "medium"
    assert action == _FALLBACK["medium"]


def test_classify_tier_boundary_30_is_low():
    assert classify_tier(0.30)[0] == "low"


def test_classify_tier_low():
    assert classify_tier(0.45)[0] == "low"


def test_fallback_keys():
    assert set(_FALLBACK) == {"high", "medium", "low"}
    for v in _FALLBACK.values():
        assert isinstance(v, str) and v


def test_jaccard_identical():
    assert _jaccard_strict(["a", "b"], ["a", "b"]) == 1.0


def test_jaccard_partial():
    assert _jaccard_strict(["a", "b"], ["a", "c"]) == 1 / 3


def test_jaccard_disjoint_and_empty():
    assert _jaccard_strict(["a"], ["b"]) == 0.0
    assert _jaccard_strict([], []) == 1.0
    assert _jaccard_strict(["a"], []) == 0.0
