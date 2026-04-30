#!/usr/bin/env bash
set -euo pipefail

if command -v pytest >/dev/null 2>&1; then
  pytest -q
else
  echo "pytest not found. Install dev dependencies or add pytest to requirements." >&2
  exit 1
fi
