#!/usr/bin/env python3
"""Small schema helpers for the ADR 0100 operator-skill eval surface.

The top-level directory is named ``agent-evals`` for readability, so this file
is intentionally dependency-light and importable by path in tests/tools.  The
schema is aggregate-only: task definitions carry sanitized category/contract
metadata and never raw issue, PR, RFP, filename, path, query, answer, or evidence
text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


ALLOWED_TASK_KEYS = frozenset(
    {
        "task_id",
        "source",
        "category",
        "train_hint",
        "acceptance",
        "hidden_test_gate",
        "aggregate_only_notes",
    }
)

ALLOWED_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "surface",
        "report_id",
        "generated_by",
        "task_count",
        "playbooks",
        "metrics",
        "scanner",
        "notes",
    }
)


@dataclass(frozen=True)
class EvalTask:
    """Sanitized operator task contract.

    ``acceptance`` and ``hidden_test_gate`` are operator-authored aggregate
    criteria, not copied issue/PR/RFP text.  The content scanner in
    ``report.py`` enforces the same boundary before these files can be
    committed.
    """

    task_id: str
    source: str
    category: str
    train_hint: str
    acceptance: tuple[str, ...]
    hidden_test_gate: str
    aggregate_only_notes: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EvalTask":
        unknown = set(data) - ALLOWED_TASK_KEYS
        if unknown:
            raise ValueError(f"unknown task key(s): {sorted(unknown)}")
        required = {"task_id", "source", "category", "acceptance", "hidden_test_gate"}
        missing = required - set(data)
        if missing:
            raise ValueError(f"missing task key(s): {sorted(missing)}")
        return cls(
            task_id=str(data["task_id"]),
            source=str(data["source"]),
            category=str(data["category"]),
            train_hint=str(data.get("train_hint", "")),
            acceptance=tuple(str(item) for item in data["acceptance"]),
            hidden_test_gate=str(data["hidden_test_gate"]),
            aggregate_only_notes=tuple(str(item) for item in data.get("aggregate_only_notes", ())),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source": self.source,
            "category": self.category,
            "train_hint": self.train_hint,
            "acceptance": list(self.acceptance),
            "hidden_test_gate": self.hidden_test_gate,
            "aggregate_only_notes": list(self.aggregate_only_notes),
        }


@dataclass(frozen=True)
class Playbook:
    name: str
    version: str
    sha256: str

    def to_mapping(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version, "sha256": self.sha256}
