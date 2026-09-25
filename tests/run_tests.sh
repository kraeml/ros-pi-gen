#!/usr/bin/env bash
# Bootstrap + Start der Testinfra (Gruppe Q des AccessPopup-Abnahmeprotokolls).
# Nutzt die venv im Repo-Root (ros-pi-gen/.venv), überschreibbar mit PIGEN_TEST_VENV.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_VENV="$(cd "$SCRIPT_DIR/.." && pwd)/.venv"
VENV="${PIGEN_TEST_VENV:-$DEFAULT_VENV}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "venv nicht gefunden: $VENV (python3 -m venv .venv im Repo-Root anlegen oder PIGEN_TEST_VENV=<pfad> setzen)" >&2
  exit 1
fi

"$VENV/bin/python" -m pip install -q -r "$SCRIPT_DIR/requirements.txt"

# --clean-cache abziehen (pytest kennt das Flag nicht): setzt intern
# PIGEN_TEST_CLEAN=1 (conftest pytest_configure leert dann tests/.work).
clean=0
args=()
for a in "$@"; do
	if [ "$a" = "--clean-cache" ]; then
		clean=1
	else
		args+=("$a")
	fi
done
[ "$clean" -eq 1 ] && export PIGEN_TEST_CLEAN=1

exec "$VENV/bin/python" -m pytest "$SCRIPT_DIR" "${args[@]}"
