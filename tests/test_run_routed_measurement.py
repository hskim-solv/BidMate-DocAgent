"""Regression test for ``scripts/run_routed_measurement.py::compute_spread`` (issue #2023).

A spread / cross-validation verdict is only meaningful with >= 2 valid routed
accuracy means. With fewer than two, the ADR 0032 top-vs-bottom spread is
undefined and the runner must emit ``no_data`` (``spread_pp=None``) — NOT a
false-green ``saturation_cross_validated`` synthesized from a single point
(``spread = x - x = 0.0``).

The regression is realistic: requesting two models where one fails to build
(e.g. BGE-M3 OOM — a documented local blocker) leaves exactly one valid mean.
The downstream gate ``check_embedding_routed_spread.py`` already treats a
non-numeric ``spread_pp`` as a hard exit-2 "re-run" — so the producer emitting
``no_data`` for the 1-model case is the consistent, correct behavior (the same
shape the 0-model case has always produced). This locks both the buggy boundary
(fail-before for the single-mean case) and the unchanged >=2-model verdicts.

Import bootstrap: ``run_routed_measurement`` does ``from eval.bootstrap import
bootstrap_ci``, so both the repo root (for the ``eval`` namespace package) and
``scripts/`` (for the bare module name) go on ``sys.path``.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_routed_measurement import SPREAD_THRESHOLD_PP, compute_spread  # noqa: E402


def _row(mean):
    """Minimal row shape consumed by ``compute_spread`` (only ``routed.accuracy_mean``)."""
    return {"routed": {"accuracy_mean": mean}}


# ---------------------------------------------------------------------------
# Insufficient data: 0 or 1 valid means => no_data (never a real verdict)
# ---------------------------------------------------------------------------


def test_zero_valid_means_is_no_data():
    result = compute_spread([_row(None), _row(None)])
    assert result["verdict"] == "no_data"
    assert result["spread_pp"] is None


def test_single_valid_mean_is_no_data_not_false_saturation():
    # THE REGRESSION (fail-before / pass-after): exactly one valid mean — the
    # other model's build/eval failed (accuracy_mean=None). A 0.0 spread from a
    # single data point must NOT be reported as cross-validated saturation.
    result = compute_spread([_row(0.73), _row(None)])
    assert result["verdict"] != "saturation_cross_validated"
    assert result["verdict"] == "no_data"
    assert result["spread_pp"] is None


def test_single_row_only_is_no_data():
    result = compute_spread([_row(0.80)])
    assert result["verdict"] == "no_data"
    assert result["spread_pp"] is None


def test_insufficient_yields_nonnumeric_spread_pp_for_consumer_gate():
    # check_embedding_routed_spread.py treats a non-numeric spread_pp as a hard
    # exit-2 "re-run the routed measurement". Lock that <2 means hits that path.
    result = compute_spread([_row(0.73), _row(None)])
    assert not isinstance(result["spread_pp"], (int, float))


# ---------------------------------------------------------------------------
# Sufficient data: >= 2 valid means => real verdict (behavior unchanged)
# ---------------------------------------------------------------------------


def test_two_equal_means_small_spread_is_saturation():
    result = compute_spread([_row(0.70), _row(0.70)])
    assert result["verdict"] == "saturation_cross_validated"
    assert result["spread_pp"] == 0.0


def test_two_means_just_below_threshold_is_saturation():
    small = (SPREAD_THRESHOLD_PP - 1.0) / 100.0
    result = compute_spread([_row(0.70), _row(0.70 + small)])
    assert result["verdict"] == "saturation_cross_validated"
    assert result["spread_pp"] < SPREAD_THRESHOLD_PP


def test_two_means_large_spread_is_reopen_trigger():
    big = (SPREAD_THRESHOLD_PP + 2.0) / 100.0
    result = compute_spread([_row(0.60), _row(0.60 + big)])
    assert result["verdict"] == "adr0019_reopen_trigger"
    assert result["spread_pp"] >= SPREAD_THRESHOLD_PP


def test_extra_none_rows_do_not_lower_the_count_below_two():
    # Two valid means plus a failed (None) model still has >=2 valid points,
    # so the real verdict stands — None rows are filtered, not counted.
    result = compute_spread([_row(0.70), _row(0.71), _row(None)])
    assert result["verdict"] == "saturation_cross_validated"
    assert isinstance(result["spread_pp"], (int, float))
