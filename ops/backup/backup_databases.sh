#!/usr/bin/env bash
# Sauvegarde quotidienne des bases Postgres des applications Bénin Digital.
# Couvre les 6 apps de Bénin Digital, y compris app2 (Keoni).
set -euo pipefail

BACKUP_ROOT="/srv/backups"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
LOG_FILE="/var/log/backup-databases.log"

# app_label:container_name
APPS=(
  "app1:app1_db"
  "app2:keoni_db_prod"
  "app3:airealtime-postgres"
  "app4:app4_db"
  "app5:app5_db"
  "app6:app6_db"
)

# Tables dont on exclut le CONTENU (le schema est conserve) : embeddings
# recalculables par le reindex complet (POST /admin/reindex-cvs). Sans cela, ces tables
# font ~1,7 Go sur 1,9 Go de base et ne se compressent presque pas.
#
# Important au restore : ces deux tables reviennent VIDES. Après restauration
# d'app2, relancer POST /admin/reindex-cvs sur matching-api pour les
# repeupler -- sinon le matching tourne silencieusement sans embeddings.
declare -A DUMP_EXTRA_ARGS=(
  [app2]="--exclude-table-data=cv_embedding_chunks --exclude-table-data=cv_embeddings"
)

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

stamp="$(date +%F_%H%M%S)"
fail=0

for entry in "${APPS[@]}"; do
  app="${entry%%:*}"
  container="${entry##*:}"
  out_dir="$BACKUP_ROOT/$app"
  mkdir -p "$out_dir"

  if ! docker inspect "$container" >/dev/null 2>&1; then
    log "ERREUR [$app] conteneur $container introuvable, ignoré."
    fail=1
    continue
  fi

  db_name="$(docker inspect "$container" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^POSTGRES_DB=' | cut -d= -f2-)"
  db_user="$(docker inspect "$container" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^POSTGRES_USER=' | cut -d= -f2-)"

  if [[ -z "$db_name" || -z "$db_user" ]]; then
    log "ERREUR [$app] impossible de lire POSTGRES_DB/POSTGRES_USER sur $container, ignoré."
    fail=1
    continue
  fi

  out_file="$out_dir/${db_name}_${stamp}.sql.gz"

  if docker exec -i "$container" pg_dump -U "$db_user" ${DUMP_EXTRA_ARGS[$app]:-} "$db_name" | gzip -9 > "$out_file"; then
    size="$(du -h "$out_file" | cut -f1)"
    log "OK [$app] $out_file ($size)"
  else
    log "ERREUR [$app] échec du pg_dump sur $container"
    rm -f "$out_file"
    fail=1
  fi

  find "$out_dir" -type f -name '*.sql.gz' -mtime "+$RETENTION_DAYS" -delete
done

if [[ "$fail" -ne 0 ]]; then
  log "Sauvegarde terminée avec au moins une erreur."
  exit 1
fi

log "Sauvegarde terminée sans erreur."
