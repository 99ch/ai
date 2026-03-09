#!/usr/bin/env bash
set -euo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/srv/keoni-local/local-stack}"
ENV_FILE="${ENV_FILE:-.env.prod}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
API_URL="${API_URL:-http://127.0.0.1:8000}"
N8N_URL="${N8N_URL:-http://127.0.0.1:5678}"

cd "$DEPLOY_PATH"

echo "== Compose status =="
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps

echo "== API health =="
curl -fsS "$API_URL/health" | cat

echo "== n8n health =="
curl -fsS "$N8N_URL/healthz" | cat

echo "Stack check OK"
