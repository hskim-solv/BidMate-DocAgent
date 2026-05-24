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

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
  else
    echo "python not found. Install dev dependencies or add Python to PATH." >&2
    exit 1
  fi
fi

PYTEST_CMD=()
if command -v pytest >/dev/null 2>&1; then
  PYTEST_CMD=(pytest)
elif "${PYTHON_BIN}" -c "import pytest" >/dev/null 2>&1; then
  PYTEST_CMD=("${PYTHON_BIN}" -m pytest)
else
  echo "pytest not found. Install dev dependencies or add pytest to requirements." >&2
  exit 1
fi

# Default local/PR behavior is the deterministic fast suite. The slow suite is
# selected explicitly by `.github/workflows/slow-tests.yml` via PYTEST_ADDOPTS
# (`-m slow`) so public fixture smoke CI never pulls private/local-heavy paths.
MARK_FLAGS=()
if [[ -z "${PYTEST_ADDOPTS:-}" && "${BIDMATE_PYTEST_DEFAULT_NOT_SLOW:-1}" == "1" ]]; then
  MARK_FLAGS=(-m "not slow")
fi

# Coverage flags emit coverage.xml for CI artifact + Codecov upload (issue #323).
# pytest-cov is an opt-in dev dependency: gracefully fall back to plain pytest
# if it is not installed (e.g. minimal envs that only run a smoke subset).
COV_FLAGS=()
ENABLE_COV="${BIDMATE_PYTEST_COV:-}"
if [[ -z "${ENABLE_COV}" && "${CI:-}" == "true" ]]; then
  ENABLE_COV=1
fi
if [[ "${ENABLE_COV}" == "1" ]] && "${PYTHON_BIN}" -c "import pytest_cov" >/dev/null 2>&1; then
  COV_FLAGS=(--cov --cov-report=term-missing --cov-report=xml)
fi

# Issue #915: pytest-xdist parallelism via `-n auto` is available as an opt-in
# (`BIDMATE_PYTEST_XDIST=1`). The default is serial because subprocess-heavy
# hook/governance tests are more stable locally without worker fan-out.
#
# Issue #931: CI matrix shard via pytest-split. When `BIDMATE_PYTEST_SPLITS`
# AND `BIDMATE_PYTEST_SHARD` are both set AND pytest-split is importable,
# pytest receives `--splits N --group K` to run only this shard's slice of
# the suite. Used by `.github/workflows/pr-eval.yml`'s matrix.shard fan-out.
# Local runs without the env vars (default) skip --splits entirely — same
# behavior as before the matrix shard landed. The fallback chain (no env
# vars OR pytest-split missing) keeps fresh-clone / minimal-env paths intact.
XDIST_FLAGS=()
if [[ "${BIDMATE_PYTEST_XDIST:-0}" == "1" ]]; then
  if "${PYTHON_BIN}" -c "import xdist" >/dev/null 2>&1; then
    XDIST_FLAGS=(-n "${BIDMATE_PYTEST_WORKERS:-auto}" --dist loadfile)
  else
    echo "pytest-xdist not importable; ignoring BIDMATE_PYTEST_XDIST." >&2
  fi
fi
SPLIT_FLAGS=()
if [[ -n "${BIDMATE_PYTEST_SPLITS:-}" && -n "${BIDMATE_PYTEST_SHARD:-}" ]]; then
  if "${PYTHON_BIN}" -c "import pytest_split" >/dev/null 2>&1; then
    # No `.test_durations` is committed (issue #1281): the heavy real-model
    # suite is `slow`-marked and isolated into pr-eval.yml's `slow-tests`
    # job, leaving this sharded matrix to run only `-m "not slow"`. With no
    # durations file pytest-split splits by test count — the right model for
    # the now-homogeneous fast suite (serial per-test durations mis-modelled
    # the per-shard BGE-M3 download, see #1281 / reverted #1298).
    SPLIT_FLAGS=(--splits "${BIDMATE_PYTEST_SPLITS}" --group "${BIDMATE_PYTEST_SHARD}")
  else
    echo "pytest-split not importable; ignoring BIDMATE_PYTEST_SPLITS/SHARD." >&2
  fi
fi
# Issue #978 — opt-in `--store-durations` for refreshing the
# `.test_durations` baseline that pytest-split consults for balanced
# shard partitioning. Off by default (CI runs leave `.test_durations`
# untouched). To refresh locally: run the FULL suite (unset
# BIDMATE_PYTEST_SPLITS/SHARD so the resulting file isn't partial),
# then commit the updated `.test_durations`:
#   BIDMATE_PYTEST_STORE_DURATIONS=1 bash scripts/test.sh
STORE_DURATIONS_FLAGS=()
if [[ "${BIDMATE_PYTEST_STORE_DURATIONS:-}" == "1" ]]; then
  if "${PYTHON_BIN}" -c "import pytest_split" >/dev/null 2>&1; then
    STORE_DURATIONS_FLAGS=(--store-durations)
  else
    echo "pytest-split not importable; ignoring BIDMATE_PYTEST_STORE_DURATIONS." >&2
  fi
fi
# macOS system bash (3.2.57) treats an empty array expanded as "${ARR[@]}"
# under `set -u` as an unbound-variable error and aborts. All four flag groups
# can legitimately reach this line empty (xdist/cov/split not installed, or
# BIDMATE_PYTEST_SPLITS/SHARD/STORE_DURATIONS unset on a normal local run), so
# the plain "${ARR[@]}" form crashes before pytest ever runs (#1179). The
# "${ARR[@]+"${ARR[@]}"}" form expands to nothing for an empty array and to the
# quoted elements otherwise — safe on bash 3.2 AND 4.4+. Do NOT simplify back
# to "${ARR[@]}"; that reintroduces the macOS-bash-3.2 crash. (bash 4.4+ /
# Linux CI never hit this, which is why it slipped past the sharded CI gate.)
"${PYTEST_CMD[@]}" -q \
  "${MARK_FLAGS[@]+"${MARK_FLAGS[@]}"}" \
  "${XDIST_FLAGS[@]+"${XDIST_FLAGS[@]}"}" \
  "${COV_FLAGS[@]+"${COV_FLAGS[@]}"}" \
  "${SPLIT_FLAGS[@]+"${SPLIT_FLAGS[@]}"}" \
  "${STORE_DURATIONS_FLAGS[@]+"${STORE_DURATIONS_FLAGS[@]}"}"
