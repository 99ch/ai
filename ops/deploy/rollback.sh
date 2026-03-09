#!/usr/bin/env bash
set -euo pipefail

TARGET_TAG="${1:-}"
if [[ -z "$TARGET_TAG" ]]; then
  echo "Usage: $0 <image-tag>" >&2
  exit 1
fi

DEPLOY_PATH="${DEPLOY_PATH:-/srv/keoni-local/local-stack}"
ENV_FILE="${ENV_FILE:-.env.prod}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

cd "$DEPLOY_PATH"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $DEPLOY_PATH/$ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ -z "${MATCHING_API_IMAGE:-}" ]]; then
  echo "MATCHING_API_IMAGE must be set in $ENV_FILE" >&2
  exit 1
fi

echo "Rolling back to ${MATCHING_API_IMAGE}:${TARGET_TAG}"
export IMAGE_TAG="$TARGET_TAG"

docker pull "${MATCHING_API_IMAGE}:${TARGET_TAG}"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --remove-orphans

echo "Rollback completed to tag: $TARGET_TAG"
