#!/usr/bin/env python3
"""Fail closed when new private eval work drifts back to stale real100/v1 evidence."""
from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = (
    Path("CLAUDE.md"),
    Path("tasks/queue.md"),
    Path("docs/plans/T-2026-0028-refresh-private-coverage-semantic-baselines.md"),
    Path("docs/plans/T-2026-0029-real100-v2-retrieval-diagnostic-workbench.md"),
    Path("docs/plans/T-2026-0030-real100-v2-latency-cost-budget-envelope.md"),
    Path("docs/plans/T-2026-0032-reranker-candidate-budget-experiment.md"),
    Path("docs/plans/T-2026-0033-context-packing-citation-ordering-experiment.md"),
    Path("docs/evaluation/surface-map.md"),
    Path("docs/evaluation/private_real_eval_workflow.md"),
    Path("docs/evaluation/real100_v2-retrieval-diagnostics.md"),
    Path("docs/evaluation/real100_v2-latency-cost-budget.md"),
    Path("docs/evaluation/real100_v2-reranker-candidate-budget.md"),
    Path("reports/real100_v2/README.md"),
)

STALE_PATH_RE = re.compile(r"\b(?:data/index|reports|outputs)/real100(?!_v2)\b")
STALE_COMMAND_RE = re.compile(r"^\s*(?:REAL_EVAL_ROOT=\S+\s+)?make\s+real-eval(?:\s|$)")
STALE_COUNT_RE = re.compile(r"\b221\b")
BAN_CONTEXT_RE = re.compile(
    r"\b(?:archive-only|banned|block|blocks|disabled|do not|forbid|forbidden|"
    r"금지|쓰지|사용하지|legacy|or default|or old|prohibited|stale)\b",
    re.IGNORECASE,
)


def _task_block(text: str, task_id: str, next_task_id: str | None) -> str:
    marker = f"## {task_id}"
    start = text.find(marker)
    if start == -1:
        return ""
    next_task = -1
    if next_task_id:
        next_task = text.find(f"\n## {next_task_id}", start + len(marker))
    return text[start:] if next_task == -1 else text[start:next_task]


def _command_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            lines.append((lineno, line))
    return lines


def _is_ban_context(line: str) -> bool:
    return bool(BAN_CONTEXT_RE.search(line))


def check_path(path: Path) -> list[str]:
    full_path = ROOT / path
    text = full_path.read_text(encoding="utf-8")
    if path == Path("tasks/queue.md"):
        scoped = "\n".join(
            block
            for block in (
                _task_block(text, "T-2026-0028", "T-2026-0029"),
                _task_block(text, "T-2026-0029", "T-2026-0030"),
                _task_block(text, "T-2026-0030", "T-2026-0031"),
                _task_block(text, "T-2026-0031", "T-2026-0032"),
                _task_block(text, "T-2026-0032", "T-2026-0033"),
            )
            if block
        )
    else:
        scoped = text
    findings: list[str] = []

    if "real100_v2" not in scoped:
        findings.append(f"{path}: missing required real100_v2 reference")
    guard_required_paths = {
        Path("tasks/queue.md"),
        Path("docs/plans/T-2026-0028-refresh-private-coverage-semantic-baselines.md"),
        Path("docs/plans/T-2026-0029-real100-v2-retrieval-diagnostic-workbench.md"),
        Path("docs/plans/T-2026-0030-real100-v2-latency-cost-budget-envelope.md"),
        Path("docs/plans/T-2026-0032-reranker-candidate-budget-experiment.md"),
        Path("docs/plans/T-2026-0033-context-packing-citation-ordering-experiment.md"),
        Path("docs/evaluation/surface-map.md"),
        Path("docs/evaluation/private_real_eval_workflow.md"),
    }
    if "real-eval-v2" not in scoped and path in guard_required_paths:
        findings.append(f"{path}: missing required real-eval-v2 guard/check reference")

    if path == Path("CLAUDE.md"):
        required = (
            "legacy real100/v1/221/kordoc aggregate evidence is banned",
            "until the maintainer explicitly re-enables",
        )
        for phrase in required:
            if phrase not in scoped:
                findings.append(f"{path}: missing policy phrase: {phrase}")

    if path == Path("docs/evaluation/private_real_eval_workflow.md"):
        if "legacy real100/v1" not in scoped.lower():
            findings.append(f"{path}: missing legacy real100/v1 deprecation note")

    if path == Path("docs/evaluation/surface-map.md"):
        if "reports/real100_v2/" not in scoped:
            findings.append(f"{path}: private real-eval surface must point at reports/real100_v2/")

    if path in {
        Path("tasks/queue.md"),
        Path("docs/plans/T-2026-0028-refresh-private-coverage-semantic-baselines.md"),
        Path("docs/plans/T-2026-0029-real100-v2-retrieval-diagnostic-workbench.md"),
        Path("docs/plans/T-2026-0030-real100-v2-latency-cost-budget-envelope.md"),
        Path("docs/plans/T-2026-0032-reranker-candidate-budget-experiment.md"),
        Path("docs/plans/T-2026-0033-context-packing-citation-ordering-experiment.md"),
        Path("docs/evaluation/real100_v2-retrieval-diagnostics.md"),
        Path("docs/evaluation/real100_v2-latency-cost-budget.md"),
        Path("docs/evaluation/real100_v2-reranker-candidate-budget.md"),
    }:
        for lineno, line in enumerate(scoped.splitlines(), start=1):
            if _is_ban_context(line):
                continue
            if STALE_PATH_RE.search(line):
                findings.append(f"{path}:{lineno}: stale real100 path: {line.strip()}")
            if STALE_COUNT_RE.search(line):
                findings.append(f"{path}:{lineno}: stale 221-count reference: {line.strip()}")

        for lineno, line in _command_lines(scoped):
            stripped = line.strip()
            if STALE_COMMAND_RE.match(stripped) and not stripped.startswith("make real-eval-v2"):
                findings.append(f"{path}:{lineno}: stale make real-eval command: {stripped}")

    return findings


def main() -> int:
    findings: list[str] = []
    for path in DEFAULT_PATHS:
        findings.extend(check_path(path))

    if findings:
        print("real100_v2-only legacy guard failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("real100_v2-only legacy guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
