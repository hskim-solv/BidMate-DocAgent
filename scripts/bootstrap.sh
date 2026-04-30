#!/usr/bin/env bash
set -euo pipefail

# Bootstrap development environment for Agentic-VLM.
# Run from the repository root:
#   bash scripts/bootstrap.sh
# Optional overrides:
#   PYTHON_BIN=python3.11 VENV_DIR=.venv CREATE_VENV=1 bash scripts/bootstrap.sh

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
CREATE_VENV="${CREATE_VENV:-1}"
UPGRADE_PIP="${UPGRADE_PIP:-1}"
REQUIREMENTS_FILE="${REQUIREMENTS_FILE:-requirements.txt}"
DEV_REQUIREMENTS_FILE="${DEV_REQUIREMENTS_FILE:-requirements-dev.txt}"

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$1"
}

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "Missing required file: $path" >&2
    exit 1
  fi
}

require_file "$REQUIREMENTS_FILE"

if [[ "$CREATE_VENV" == "1" ]]; then
  if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating virtual environment at $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  else
    log "Reusing existing virtual environment at $VENV_DIR"
  fi

  # shellcheck disable=SC1090
  source "$VENV_DIR/bin/activate"
  PYTHON_BIN="python"
fi

if [[ "$UPGRADE_PIP" == "1" ]]; then
  log "Upgrading pip"
  "$PYTHON_BIN" -m pip install --upgrade pip
fi

log "Installing runtime dependencies from $REQUIREMENTS_FILE"
"$PYTHON_BIN" -m pip install -r "$REQUIREMENTS_FILE"

if [[ -f "$DEV_REQUIREMENTS_FILE" ]]; then
  log "Installing development dependencies from $DEV_REQUIREMENTS_FILE"
  "$PYTHON_BIN" -m pip install -r "$DEV_REQUIREMENTS_FILE"
else
  log "No $DEV_REQUIREMENTS_FILE found; skipping development dependencies"
fi

log "Bootstrap completed successfully"
echo "Python executable: $(command -v "$PYTHON_BIN")"
if [[ "$CREATE_VENV" == "1" ]]; then
  echo "Virtual environment: $VENV_DIR"
fi
