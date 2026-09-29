#!/usr/bin/env bash
# Create or update the project's test environment in .venv (Python 3.14).
# Idempotent: dependencies are only reinstalled when requirements.txt changes.
# Usage: .claude/skills/setup-dev/scripts/setup_dev.sh [--force]
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

VENV=".venv"
STAMP="$VENV/.requirements.sha256"
EXTRA="pytest-cov"

PYTHON="${PYTHON:-$(command -v python3.14 || true)}"
if [[ -z "$PYTHON" ]]; then
  echo "ERROR: python3.14 not found. Install Python 3.14 or set PYTHON=/path/to/python3.14." >&2
  exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Creating $VENV with $("$PYTHON" --version)..."
  "$PYTHON" -m venv "$VENV"
fi

current_hash="$(shasum -a 256 requirements.txt | cut -d' ' -f1)"
if [[ "${1:-}" == "--force" || ! -f "$STAMP" || "$(cat "$STAMP")" != "$current_hash" ]]; then
  echo "Installing requirements.txt + $EXTRA..."
  "$VENV/bin/python" -m pip install -q --upgrade pip
  "$VENV/bin/python" -m pip install -q -r requirements.txt "$EXTRA"
  echo "$current_hash" > "$STAMP"
else
  echo "Dependencies up to date (requirements.txt unchanged)."
fi

echo
echo "Python:              $("$VENV/bin/python" --version)"
echo "pytest:              $VENV/bin/pytest"
echo "flake8:              $VENV/bin/flake8"
echo "homeassistant:       $("$VENV/bin/python" -c 'import homeassistant.const as c; print(c.__version__)')"
echo "python-frank-energie source: $("$VENV/bin/python" -c 'import python_frank_energie, os; print(os.path.dirname(python_frank_energie.__file__))')"
echo "homeassistant source: $("$VENV/bin/python" -c 'import homeassistant, os; print(os.path.dirname(homeassistant.__file__))')"
