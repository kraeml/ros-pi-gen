#!/usr/bin/env bash
# Bootstrap + Start der Testinfra (Gruppe Q des AccessPopup-Abnahmeprotokolls).
# Nutzt die venv am Workspace-Root (überschreibbar mit PIGEN_TEST_VENV).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_VENV="$(cd "$SCRIPT_DIR/../.." && pwd)/.venv"
VENV="${PIGEN_TEST_VENV:-$DEFAULT_VENV}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "venv nicht gefunden: $VENV (PIGEN_TEST_VENV=<pfad> setzen)" >&2
  exit 1
fi

"$VENV/bin/python" -m pip install -q -r "$SCRIPT_DIR/requirements.txt"
exec "$VENV/bin/python" -m pytest "$SCRIPT_DIR" "$@"
