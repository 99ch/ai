#!/usr/bin/env bash
set -euo pipefail

# VPS partagé par plusieurs apps (keoni, app1, app3-6, ai-realtime) : on ne
# touche qu'au cache de build (jamais utilisé par un conteneur en cours,
# donc sans risque) et aux images "dangling" (sans tag, orphelines après un
# rebuild). On NE fait jamais de `docker image prune -a` ici -- ça
# supprimerait aussi des images taguées mais temporairement sans conteneur
# (ex: pendant un redéploiement d'une autre app), ce qui n'est pas notre
# appel à faire sur les apps des autres.
KEEP_CACHE_HOURS="${KEEP_CACHE_HOURS:-72}"

echo "== Disk before =="
df -h / | tail -n1

echo "== Build cache older than ${KEEP_CACHE_HOURS}h =="
docker builder prune -af --filter "until=${KEEP_CACHE_HOURS}h"

echo "== Dangling images =="
docker image prune -f

echo "== Disk after =="
df -h / | tail -n1
