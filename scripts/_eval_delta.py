"""Shared eval_summary.json delta helpers.

Used by scripts/compare_eval.py (PR eval comment) and scripts/harness_compare.py
(harness matrix compare). Keep the metric list aligned across both so synthetic
matrix runs and PR delta tables surface the same surface.
"""
from __future__ import annotations

from typing import Any


# (dotted_path, label, higher_is_better)
METRICS: list[tuple[str, str, bool]] = [
    ("accuracy", "accuracy", True),
    ("groundedness", "groundedness", True),
    ("citation_precision", "citation_precision", True),
    ("citation_grounding", "citation_grounding", True),
    ("claim_citation_alignment", "claim_citation_alignment", True),
    ("answer_format_compliance", "answer_format_compliance", True),
    ("abstention", "abstention (unanswerable cases)", True),
    ("retry", "retry_rate", False),
    ("latency.p50", "latency_p50_ms", False),
    ("latency.p95", "latency_p95_ms", False),
]


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
