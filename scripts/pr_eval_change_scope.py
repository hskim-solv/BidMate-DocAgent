#!/usr/bin/env python3
"""Classify PR changed files for the PR Eval Delta workflow.

The workflow has two different costs:

* pytest should run for code, tests, hooks, workflow, or tooling changes.
* fixture smoke eval should only run for paths that can affect runtime/eval
  behavior or the eval-delta workflow itself.

Docs/report-only changes intentionally skip both, while baseline provenance and
branch/issue checks remain handled by separate always-on workflows/jobs.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


RUNTIME_FILES = {
    "ingestion.py",
    "visual_ingestion.py",
    "text_normalize.py",
    "korean_lexicon.py",
    "scripts/build_index.py",
    "scripts/_eval_delta.py",
    "scripts/check_latency_slo.py",
    "scripts/compare_eval.py",
    "scripts/validate_claim.py",
    ".github/workflows/pr-eval.yml",
}

RUNTIME_PREFIXES = (
    "eval/",
    "api/",
    ".github/actions/run-eval/",
)

PYTEST_PREFIXES = (
    "tests/",
    "scripts/",
    ".githooks/",
    ".github/workflows/",
    ".github/actions/",
    ".claude/commands/",
)

PYTEST_FILES = {
    "Makefile",
    "pyproject.toml",
    "pytest.ini",
    "setup.cfg",
    "requirements.txt",
    "requirements-dev.txt",
}

REPORT_PREFIXES = (
    "reports/",
    "artifacts/",
)

DOC_PREFIXES = (
    "docs/",
)

DOC_SUFFIXES = (
    ".md",
    ".txt",
    ".rst",
)


@dataclass(frozen=True)
class ChangeScope:
    runtime: bool
    pytest: bool
    runtime_reasons: tuple[str, ...]
    pytest_reasons: tuple[str, ...]


def _normalize(path: str) -> str:
    path = path.strip()
    while path.startswith("./"):
        path = path[2:]
    return path


def _is_rag_module(path: str) -> bool:
    name = Path(path).name
    return "/" not in path and name.startswith("rag_") and name.endswith(".py")


def _is_requirements(path: str) -> bool:
    name = Path(path).name
    return name.startswith("requirements") and name.endswith(".txt")


def _is_runtime_path(path: str) -> bool:
    if path in RUNTIME_FILES or _is_rag_module(path) or _is_requirements(path):
        return True
    return any(path.startswith(prefix) for prefix in RUNTIME_PREFIXES)


def _is_docs_or_reports_only_path(path: str) -> bool:
    if path.startswith(DOC_PREFIXES):
        return True
    if path.startswith(REPORT_PREFIXES):
        return True
    return path.endswith(DOC_SUFFIXES)


def _is_pytest_path(path: str) -> bool:
    if _is_runtime_path(path):
        return True
    if path.endswith(".py"):
        return True
    if path in PYTEST_FILES or _is_requirements(path):
        return True
    # ADR 0100: any agent-evals/ change except the README must run the index-aware privacy
    # guard (tests/test_agent_evals_gitignore.py). A force-added raw .md/.txt would otherwise
    # be classified docs-only and skip the pytest job, leaving the guard toothless in CI.
    if path.startswith("agent-evals/") and path != "agent-evals/README.md":
        return True
    return any(path.startswith(prefix) for prefix in PYTEST_PREFIXES)


def classify(paths: Iterable[str]) -> ChangeScope:
    raw_paths = list(paths)
    changed = tuple(path for path in (_normalize(p) for p in raw_paths) if path)
    runtime_reasons: list[str] = []
    pytest_reasons: list[str] = []

    # Fail closed on leading/trailing whitespace: a path like "agent-evals/README.md " is a
    # DIFFERENT git file than the exact README exception, but _normalize() would strip it to
    # the README and skip the agent-evals/ privacy guard. Any surrounding-whitespace path
    # forces pytest so the index-aware guard runs (ADR 0100; do not trim meaningful path
    # characters before the policy check).
    for raw in raw_paths:
        stripped = raw.strip()
        if stripped and stripped != raw:
            pytest_reasons.append(raw)

    for path in changed:
        if _is_runtime_path(path):
            runtime_reasons.append(path)
        if _is_pytest_path(path):
            pytest_reasons.append(path)

    if changed and not pytest_reasons:
        non_docs_report = [path for path in changed if not _is_docs_or_reports_only_path(path)]
        if non_docs_report:
            pytest_reasons.extend(non_docs_report)

    return ChangeScope(
        runtime=bool(runtime_reasons),
        pytest=bool(pytest_reasons),
        runtime_reasons=tuple(runtime_reasons),
        pytest_reasons=tuple(pytest_reasons),
    )


def _read_changed_files(path: str) -> list[str]:
    if path == "-":
        import sys

        return sys.stdin.read().splitlines()
    return Path(path).read_text(encoding="utf-8").splitlines()


def _read_changed_files_jsonl(path: str) -> list[str]:
    """Read a JSONL changed-file list: one ``@json``-encoded filename per line.

    Each line is a complete JSON string, so a filename containing a newline (or other control
    character) survives intact instead of being split apart by ``splitlines()`` — ``classify``'s
    whitespace fail-closed rule can then flag it and force the agent-evals/ privacy guard.
    Use this transport (not ``--changed-files``) for untrusted PR file lists, fed from
    ``gh api .../files --jq '.[].filename | @json'`` (Codex pre-commit review, issue #1844).
    """
    if path == "-":
        import sys

        raw = sys.stdin.read()
    else:
        raw = Path(path).read_text(encoding="utf-8")
    names: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        names.append(str(json.loads(line)))
    return names


def _bool(value: bool) -> str:
    return "true" if value else "false"


def render(scope: ChangeScope) -> str:
    runtime_reason = ", ".join(scope.runtime_reasons) if scope.runtime_reasons else "none"
    pytest_reason = ", ".join(scope.pytest_reasons) if scope.pytest_reasons else "none"
    return "\n".join(
        [
            f"runtime={_bool(scope.runtime)}",
            f"pytest={_bool(scope.pytest)}",
            f"runtime_reason={runtime_reason}",
            f"pytest_reason={pytest_reason}",
        ]
    )


def write_github_output(path: str, scope: ChangeScope) -> None:
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(f"runtime={_bool(scope.runtime)}\n")
        f.write(f"pytest={_bool(scope.pytest)}\n")
        f.write(
            "runtime_reason="
            f"{'; '.join(scope.runtime_reasons) if scope.runtime_reasons else 'none'}\n"
        )
        f.write(
            "pytest_reason="
            f"{'; '.join(scope.pytest_reasons) if scope.pytest_reasons else 'none'}\n"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--changed-files",
        help="Path to newline-delimited changed file list, or '-' for stdin. "
        "Use --changed-files-jsonl for untrusted PR lists (newline-safe).",
    )
    src.add_argument(
        "--changed-files-jsonl",
        help="Path to a JSONL list (one @json-encoded filename per line), or '-' for stdin. "
        "Newline-safe transport for untrusted PR file lists.",
    )
    parser.add_argument(
        "--github-output",
        help="Optional GitHub Actions output file path. Usually $GITHUB_OUTPUT.",
    )
    args = parser.parse_args(argv)

    if args.changed_files_jsonl is not None:
        paths = _read_changed_files_jsonl(args.changed_files_jsonl)
    else:
        paths = _read_changed_files(args.changed_files)
    scope = classify(paths)
    if args.github_output:
        write_github_output(args.github_output, scope)
    print(render(scope))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
