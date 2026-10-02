#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  printf 'Usage: %s <variant> <deploy-dir> <package-dir> <base-url> <release-build:0|1>\n' "$0" >&2
  exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# package_image.py validate_manifest() benötigt jsonschema (venv-
# Abhängigkeit, siehe tests/requirements.txt) -- Default auf die venv-
# Python-Binary, die der Makefile-"venv"-Target anlegt (make package
# hängt davon ab); PACKAGE_PYTHON erlaubt einen expliziten Override (z. B.
# für einen Aufruf außerhalb von make).
PYTHON=${PACKAGE_PYTHON:-"$SCRIPT_DIR/../.venv/bin/python"}
exec "$PYTHON" "$SCRIPT_DIR/package_image.py" "$@"
