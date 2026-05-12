#!/usr/bin/env bash
set -euo pipefail

# Issue #334 (G8 of #284): opt-in ruff lint gate.
# Ruff is treated as an optional dev dependency — if it is not on PATH we
# print a one-line install hint and continue, so minimal envs (smoke runs,
# fresh worktrees) keep working. When ruff IS installed, `ruff check` is a
# hard gate (rule selection is narrowed in pyproject.toml to fatal pyflakes
# only — see the [tool.ruff.lint] block). `ruff format --check` runs in
# warn-only mode until the codebase is `ruff format`-clean (separate PR).
if command -v ruff >/dev/null 2>&1; then
  ruff check .
  if ! ruff format --check . >/dev/null 2>&1; then
    echo "ruff format --check: formatting drift detected (warn-only; see issue #334)." >&2
  fi
else
  echo "ruff not installed -- skipping lint; install via 'pip install ruff'." >&2
fi

# Coverage flags emit coverage.xml for CI artifact + Codecov upload (issue #323).
# pytest-cov is an opt-in dev dependency: gracefully fall back to plain pytest
# if it is not installed (e.g. minimal envs that only run a smoke subset).
COV_FLAGS=()
if python -c "import pytest_cov" >/dev/null 2>&1; then
  COV_FLAGS=(--cov --cov-report=term-missing --cov-report=xml)
fi

if command -v pytest >/dev/null 2>&1; then
  pytest -q "${COV_FLAGS[@]}"
else
  echo "pytest not found. Install dev dependencies or add pytest to requirements." >&2
  exit 1
fi
