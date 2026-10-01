#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  printf 'Usage: %s <release-package-dir> [--dry-run] | --read-only-check\n' "$0" >&2
  exit 2
fi

if [[ "$1" != "--read-only-check" && $# -eq 2 && "$2" != "--dry-run" ]]; then
  printf 'Unbekannte Option: %s\n' "$2" >&2
  exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROFILE=${S3_PROFILE:-s3-intern-admin}
ENDPOINT=${S3_ENDPOINT:-https://s3-intern.kraeml-bayern.de}
REGION=${S3_REGION:-eu-central-1}
PUBLIC_BASE_URL=${S3_PUBLIC_BASE_URL:-https://s3-intern.kraeml-bayern.de/ros-pi-gen-images}
ARGS=("$1" --profile "$PROFILE" --endpoint "$ENDPOINT" --region "$REGION" --public-base-url "$PUBLIC_BASE_URL")
if [[ "$1" == "--read-only-check" ]]; then
  if [[ $# -ne 1 ]]; then
    printf 'Usage: %s --read-only-check\n' "$0" >&2
    exit 2
  fi
  ARGS=(--read-only-check --profile "$PROFILE" --endpoint "$ENDPOINT" --region "$REGION" --public-base-url "$PUBLIC_BASE_URL")
else
  ARGS=("$1" --profile "$PROFILE" --endpoint "$ENDPOINT" --region "$REGION" --public-base-url "$PUBLIC_BASE_URL")
  if [[ $# -eq 2 ]]; then
    ARGS+=(--dry-run)
  fi
fi
exec python3 "$SCRIPT_DIR/publish_s3.py" "${ARGS[@]}"
