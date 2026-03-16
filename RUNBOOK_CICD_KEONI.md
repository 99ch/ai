# Runbook CI/CD Keoni (GitHub Actions)

Guide débutant detaille disponible dans `GUIDE_DEPLOIEMENT_STAGIAIRE_KEONI.md`.

## 1. Objectif
Ce runbook décrit la chaîne CI/CD pour déployer la brique IA Keoni (matching-api, n8n, db) sur staging puis production.

## 2. Fichiers ajoutes
- `.github/workflows/ci.yml`
- `.github/workflows/build.yml`
- `.github/workflows/deploy-prod.yml`
- `local-stack/.env.prod.example`
- `local-stack/docker-compose.staging.yml`
- `local-stack/docker-compose.prod.yml`
- `ops/smoke/smoke_e2e.sh`
- `ops/backup/backup_postgres.sh`
- `ops/monitoring/check_stack.sh`
- `ops/deploy/rollback.sh`

## 3. Secrets GitHub à configurer
### 3.1 Environment `staging`
- `STAGING_SSH_HOST`
- `STAGING_SSH_PORT`
- `STAGING_SSH_USER`
- `STAGING_SSH_KEY`
- `STAGING_DEPLOY_PATH` (ex: `/srv/keoni-local/local-stack`)
- `STAGING_API_URL` (ex: `https://api-staging.example.com`)
- `STAGING_N8N_URL` (ex: `https://n8n-staging.example.com`)
- `STAGING_WEBHOOK_URL` (ex: `https://n8n-staging.example.com/webhook/keoni/new-job`)
- `STAGING_WEBHOOK_SECRET`
- `STAGING_WP_URL` (ex: `https://wp-staging.example.com`)
- `STAGING_JOB_ID` (job de test)

### 3.2 Environment `production`
- `PROD_SSH_HOST`
- `PROD_SSH_PORT`
- `PROD_SSH_USER`
- `PROD_SSH_KEY`
- `PROD_DEPLOY_PATH`
- `PROD_API_URL`
- `PROD_N8N_URL`
- `PROD_WEBHOOK_URL`
- `PROD_WEBHOOK_SECRET`
- `PROD_WP_URL`
- `PROD_JOB_ID`

## 4. Preparation serveur
1. Copier `local-stack/.env.prod.example` vers `.env.prod` (prod) et `.env.staging` (staging).
2. Renseigner toutes les valeurs sensibles.
3. Vérifier `MATCHING_API_IMAGE` et `IMAGE_TAG` dans les fichiers env.
4. Positionner les fichiers compose dans le dossier cible (`local-stack`).

## 4.1 Cas réel: WordPress déjà en production
Dans ce cas, le CI/CD ne deploie pas WordPress. Il deploie uniquement `matching-api` + `n8n` + `db`.

Réglages a faire dans le backoffice WordPress (`Keoni Bridge > Parametres`):
- `Clé API`: cliquer sur `Régénérer la clé API`, copier la valeur et la stocker dans `WP_API_KEY` (env n8n/serveur).
- `Webhook n8n`: URL publique webhook n8n (ex: `https://n8n.example.com/webhook/keoni/new-job`).
- `Secret Webhook n8n`: même valeur que `N8N_WEBHOOK_SECRET` (serveur) et `PROD_WEBHOOK_SECRET` (GitHub secret).
- `URL matching API`: valeur informative, mettre `https://api.example.com/score`.

Règles de correspondance importantes:
- `WP_API_BASE_URL` doit pointer vers le WordPress de production (ex: `https://wp.example.com`).
- `WP_API_KEY` (n8n) = clé API Keoni Bridge regeneree dans le backoffice.
- `N8N_WEBHOOK_SECRET` (n8n) = `webhook_secret` du plugin Keoni Bridge.

## 5. Flux de déploiement
1. PR ou push sur `main` declenche `ci.yml` (lint, validation compose, garde-fou secrets).
2. Push sur `main` declenche `build.yml`:
   - build et push image GHCR tag `sha-<commit>` et `staging`
   - déploiement auto staging via SSH
   - smoke API/n8n + E2E
3. Production se fait via `deploy-prod.yml` (manuel + approval environment).

## 6. Rollback
Commande serveur:

```bash
cd /srv/keoni-local/local-stack
DEPLOY_PATH=/srv/keoni-local/local-stack ENV_FILE=.env.prod COMPOSE_FILE=docker-compose.prod.yml \
  /path/to/repo/ops/deploy/rollback.sh sha-<ancien-commit>
```

## 7. Backup et monitoring
### 7.1 Backup PostgreSQL
```bash
DEPLOY_PATH=/srv/keoni-local/local-stack ENV_FILE=.env.prod COMPOSE_FILE=docker-compose.prod.yml \
  /path/to/repo/ops/backup/backup_postgres.sh
```

### 7.2 Monitoring rapide
```bash
DEPLOY_PATH=/srv/keoni-local/local-stack ENV_FILE=.env.prod COMPOSE_FILE=docker-compose.prod.yml \
API_URL=https://api.example.com N8N_URL=https://n8n.example.com \
  /path/to/repo/ops/monitoring/check_stack.sh
```

## 8. Cron recommande (serveur)
- Backup DB toutes les nuits à 02:30
- Monitoring toutes les 5 minutes

Exemple:

```bash
30 2 * * * /srv/keoni-local/ai/ops/backup/backup_postgres.sh >> /var/log/keoni-backup.log 2>&1
*/5 * * * * API_URL=https://api.example.com N8N_URL=https://n8n.example.com /srv/keoni-local/ai/ops/monitoring/check_stack.sh >> /var/log/keoni-monitoring.log 2>&1
```
