#!/usr/bin/env bash
set -euo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/srv/keoni-local/local-stack}"
ENV_FILE="${ENV_FILE:-.env.prod}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-$DEPLOY_PATH/backups/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

cd "$DEPLOY_PATH"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $DEPLOY_PATH/$ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

mkdir -p "$BACKUP_DIR"

stamp="$(date +%F_%H%M%S)"
out_file="$BACKUP_DIR/${POSTGRES_DB}_${stamp}.sql.gz"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db \
  pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip -9 > "$out_file"

find "$BACKUP_DIR" -type f -name '*.sql.gz' -mtime "+$RETENTION_DAYS" -delete

echo "Backup created: $out_file"
