#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  printf 'Usage: %s <variant> <deploy-dir> <package-dir> <base-url> <release-build:0|1>\n' "$0" >&2
  exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$SCRIPT_DIR/package_image.py" "$@"
