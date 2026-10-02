#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s <release-package-dir> [--target omv|hetzner] [--dry-run] [--production-step image|manifests] | --read-only-check [--target omv|hetzner]\n' "$0" >&2
}

if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

MODE=$1
shift
DRY_RUN=0
TARGET=${S3_TARGET:-omv}
PRODUCTION_STEP=

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --target)
      TARGET=$2
      shift 2
      ;;
    --production-step)
      PRODUCTION_STEP=$2
      shift 2
      ;;
    *)
      printf 'Unbekannte Option: %s\n' "$1" >&2
      usage
      exit 2
      ;;
  esac
done

case "$TARGET" in
  omv)
    PROFILE=${S3_PROFILE:-s3-intern-admin}
    ENDPOINT=${S3_ENDPOINT:-https://s3-intern.kraeml-bayern.de}
    REGION=${S3_REGION:-eu-central-1}
    PUBLIC_BASE_URL=${S3_PUBLIC_BASE_URL:-https://s3-intern.kraeml-bayern.de/ros-pi-gen-images}
    ;;
  hetzner)
    PROFILE=${S3_PROFILE:-hetzner-prod}
    ENDPOINT=${S3_ENDPOINT:-https://hel1.your-objectstorage.com}
    REGION=${S3_REGION:-hel1}
    PUBLIC_BASE_URL=${S3_PUBLIC_BASE_URL:-https://hel1.your-objectstorage.com/ros-pi-gen-images}
    ;;
  *)
    printf 'Unbekanntes --target: %s (erlaubt: omv, hetzner)\n' "$TARGET" >&2
    exit 2
    ;;
esac

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

if [[ "$MODE" == "--read-only-check" ]]; then
  ARGS=(--read-only-check --profile "$PROFILE" --endpoint "$ENDPOINT" --region "$REGION" --public-base-url "$PUBLIC_BASE_URL")
else
  ARGS=("$MODE" --profile "$PROFILE" --endpoint "$ENDPOINT" --region "$REGION" --public-base-url "$PUBLIC_BASE_URL")
  if [[ "$DRY_RUN" == "1" ]]; then
    ARGS+=(--dry-run)
  fi
  if [[ -n "$PRODUCTION_STEP" ]]; then
    ARGS+=(--production-step "$PRODUCTION_STEP")
  fi
fi
exec python3 "$SCRIPT_DIR/publish_s3.py" "${ARGS[@]}"
