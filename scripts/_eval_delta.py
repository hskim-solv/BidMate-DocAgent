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


def fmt_delta(base: Any, head: Any, higher_is_better: bool) -> str:
    if not isinstance(base, (int, float)) or not isinstance(head, (int, float)):
        return "—"
    delta = float(head) - float(base)
    if abs(delta) < 5e-4:
        return "·"
    sign = "+" if delta > 0 else ""
    improved = (delta > 0) if higher_is_better else (delta < 0)
    flag = " ✅" if improved else " ⚠️"
    return f"{sign}{delta:.3f}{flag}"
