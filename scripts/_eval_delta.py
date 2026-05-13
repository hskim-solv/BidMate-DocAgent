"""Shared eval_summary.json delta helpers.

Used by scripts/compare_eval.py (PR eval comment) and scripts/harness_compare.py
(harness matrix compare). Keep the metric list aligned across both so synthetic
matrix runs and PR delta tables surface the same surface.
"""
from __future__ import annotations

from typing import Any


# (dotted_path, label, higher_is_better, gated)
# - higher_is_better: direction-of-improvement for the metric.
# - gated: whether a regression on this metric trips the PR CI gate.
#   Latency is shown in the delta table but excluded from the gate
#   because CI runners have high host variance — gating on it would
#   produce noisy failures unrelated to pipeline quality.
METRICS: list[tuple[str, str, bool, bool]] = [
    ("accuracy", "accuracy", True, True),
    ("groundedness", "groundedness", True, True),
    ("citation_precision", "citation_precision", True, True),
    ("citation_grounding", "citation_grounding", True, True),
    ("claim_citation_alignment", "claim_citation_alignment", True, True),
    ("answer_format_compliance", "answer_format_compliance", True, True),
    ("abstention", "abstention (unanswerable cases)", True, True),
    ("retry", "retry_rate", False, False),
    ("latency.p50", "latency_p50_ms", False, False),
    ("latency.p95", "latency_p95_ms", False, False),
]


def detect_regressions(
    base: Any,
    head: Any,
    *,
    threshold: float,
) -> list[dict[str, Any]]:
    """Return the list of gated metrics that regressed by more than ``threshold``.

    A regression is a movement *away* from ``higher_is_better`` by more
    than the threshold. Non-numeric values are skipped silently. Only
    metrics with ``gated=True`` participate.
    """
    out: list[dict[str, Any]] = []
    for path, label, higher, gated in METRICS:
        if not gated:
            continue
        b = get_path(base, path)
        h = get_path(head, path)
        if not isinstance(b, (int, float)) or not isinstance(h, (int, float)):
            continue
        delta = float(h) - float(b)
        regressed = (delta < -threshold) if higher else (delta > threshold)
        if regressed:
            out.append(
                {
                    "metric": label,
                    "path": path,
                    "base": float(b),
                    "head": float(h),
                    "delta": round(delta, 4),
                    "threshold": threshold,
                }
            )
    return out


def get_path(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def fmt_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


# Abstention 3-bin composition threshold (issue #624).
# incorrect_answer / total_abstention_cases 비율 증가 ≥ this → regression.
# Equivalent: correct_refusal share drop ≥ this also fires.
ABSTENTION_OUTCOME_RATE_THRESHOLD = 0.10


def detect_abstention_outcome_regressions(
    base: Any,
    head: Any,
) -> list[dict[str, Any]]:
    """Detect silent drift in abstention 3-bin composition (CR/IA/BP).

    Top-level abstention rate can stay flat while incorrect_answer grows
    (correct_refusal shrinks). This gate catches that composition change.

    Regression fires when ia_rate = IA / (CR+IA+BP) increases by ≥
    ABSTENTION_OUTCOME_RATE_THRESHOLD, or cr_rate decreases by the same.
    Returns [] if abstention_outcomes is absent in either summary.
    """
    base_outcomes = (base or {}).get("abstention_outcomes") if isinstance(base, dict) else None
    head_outcomes = (head or {}).get("abstention_outcomes") if isinstance(head, dict) else None
    if not isinstance(base_outcomes, dict) or not isinstance(head_outcomes, dict):
        return []

    b_cr = int(base_outcomes.get("correct_refusal") or 0)
    b_ia = int(base_outcomes.get("incorrect_answer") or 0)
    b_bp = int(base_outcomes.get("boundary_partial") or 0)
    b_total = b_cr + b_ia + b_bp

    h_cr = int(head_outcomes.get("correct_refusal") or 0)
    h_ia = int(head_outcomes.get("incorrect_answer") or 0)
    h_bp = int(head_outcomes.get("boundary_partial") or 0)
    h_total = h_cr + h_ia + h_bp

    if b_total == 0 or h_total == 0:
        return []

    out: list[dict[str, Any]] = []
    checks = [
        ("abstention: incorrect_answer_rate", b_ia / b_total, h_ia / h_total, False),
        ("abstention: correct_refusal_rate", b_cr / b_total, h_cr / h_total, True),
    ]
    for label, b_val, h_val, higher in checks:
        delta = h_val - b_val
        regressed = (delta < -ABSTENTION_OUTCOME_RATE_THRESHOLD) if higher else (delta > ABSTENTION_OUTCOME_RATE_THRESHOLD)
        if regressed:
            out.append(
                {
                    "metric": label,
                    "path": label.split(": ")[1],
                    "base": round(b_val, 4),
                    "head": round(h_val, 4),
                    "delta": round(delta, 4),
                    "threshold": ABSTENTION_OUTCOME_RATE_THRESHOLD,
                }
            )
    return out


_ABS_SILENCE_FLOOR = 5e-4


def min_num_predictions(*summaries: Any) -> int | None:
    """Return the smallest positive ``num_predictions`` across summaries.

    Used to size the N-aware silence threshold. Non-int / missing /
    non-positive values are ignored; if no summary has a usable count
    the caller falls back to the absolute floor.
    """
    counts: list[int] = []
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        value = summary.get("num_predictions")
        if isinstance(value, int) and value > 0:
            counts.append(value)
    return min(counts) if counts else None


def silence_threshold(n_min: int | None) -> float:
    """Return the ``|delta| < threshold`` band that renders as ``·``.

    Issue #463: a fixed ``5e-4`` floor silences only sub-rounding noise,
    which is too tight for small N — on a real eval of N=21, a single
    case is ±4.76 pp, so any move under half a case (~0.024) is
    statistically indistinguishable from a tied state. Tying the band
    to ``0.5 / n_min`` makes the silence rule N-aware while still
    floored by the original rounding guard for large or unknown N.
    """
    if isinstance(n_min, int) and n_min > 0:
        return max(_ABS_SILENCE_FLOOR, 0.5 / n_min)
    return _ABS_SILENCE_FLOOR


def fmt_delta(
    base: Any,
    head: Any,
    higher_is_better: bool,
    *,
    n_min: int | None = None,
) -> str:
    if not isinstance(base, (int, float)) or not isinstance(head, (int, float)):
        return "—"
    delta = float(head) - float(base)
    if abs(delta) < silence_threshold(n_min):
        return "·"
    sign = "+" if delta > 0 else ""
    improved = (delta > 0) if higher_is_better else (delta < 0)
    flag = " ✅" if improved else " ⚠️"
    return f"{sign}{delta:.3f}{flag}"
