#!/usr/bin/env python3
"""Sanitized task mining for the ADR 0100 BidMate operator-skill eval surface.

This adapter consumes already-summarized merge metadata.  It deliberately does
not read PR bodies, issue bodies, patches, filenames, or RFP text; generated
``task.yaml`` files contain only category-level contracts plus hidden-test gate
metadata.  The content scanner in ``agent-evals/core/report.py`` is the commit
boundary backstop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


DEFAULT_MINEABLE_FLOOR = 132
DEFAULT_HOLDOUT_TARGET = 46

_ALLOWED_CATEGORIES = {
    "hook_privacy",
    "eval_guard",
    "doc_contract",
    "workflow_guard",
    "test_contract",
}


@dataclass(frozen=True)
class MiningSummary:
    mineable_count: int
    holdout_target: int
    warnings: tuple[str, ...]

    def to_mapping(self) -> dict[str, int | list[str]]:
        return {
            "mineable_count": self.mineable_count,
            "holdout_target": self.holdout_target,
            "warnings": list(self.warnings),
        }


def _safe_task_id(number: int) -> str:
    return f"T-{number:04d}"


def is_mineable(record: Mapping[str, object]) -> bool:
    """True iff summarized merge metadata can become an aggregate-only task."""

    if not bool(record.get("merged")):
        return False
    if bool(record.get("contains_raw_payload")):
        return False
    category = str(record.get("category", ""))
    if category not in _ALLOWED_CATEGORIES:
        return False
    signals = record.get("signals", ())
    if not isinstance(signals, Sequence) or isinstance(signals, (str, bytes)):
        return False
    return bool(signals)


def mine_tasks(
    records: Iterable[Mapping[str, object]],
    *,
    mineable_floor: int = DEFAULT_MINEABLE_FLOOR,
    holdout_target: int = DEFAULT_HOLDOUT_TARGET,
) -> tuple[list[dict[str, object]], MiningSummary]:
    """Convert sanitized merge metadata into task contracts.

    The input may include stable PR numbers for deterministic task ids, but the
    output omits issue ids, PR titles, file names, paths, queries, answers, and
    evidence text.
    """

    tasks: list[dict[str, object]] = []
    for record in records:
        if not is_mineable(record):
            continue
        number = int(record["number"])
        category = str(record["category"])
        signals = tuple(str(item) for item in record.get("signals", ()))
        tasks.append(
            {
                "task_id": _safe_task_id(number),
                "source": "merged_pr_sanitized_metadata",
                "category": category,
                "train_hint": "derive behavior from governance contract, not copied task prose",
                "acceptance": [f"preserve {signal}" for signal in signals],
                "hidden_test_gate": "must pass an unseen regression derived from the same category",
                "aggregate_only_notes": ["no raw issue, PR, patch, filename, path, query, answer, or evidence text"],
            }
        )

    warnings: list[str] = []
    if len(tasks) < mineable_floor:
        warnings.append(f"mineable floor not met: {len(tasks)} < {mineable_floor}")
    if holdout_target > len(tasks):
        warnings.append(f"holdout target exceeds mineable count: {holdout_target} > {len(tasks)}")

    return tasks, MiningSummary(
        mineable_count=len(tasks),
        holdout_target=holdout_target,
        warnings=tuple(warnings),
    )


def render_task_yaml(task: Mapping[str, object]) -> str:
    """Render a scanner-friendly task.yaml fragment without external YAML deps."""

    lines: list[str] = []
    for key in (
        "task_id",
        "source",
        "category",
        "train_hint",
        "acceptance",
        "hidden_test_gate",
        "aggregate_only_notes",
    ):
        value = task.get(key)
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"
