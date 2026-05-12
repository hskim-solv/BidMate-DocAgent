#!/usr/bin/env bash
set -euo pipefail

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
