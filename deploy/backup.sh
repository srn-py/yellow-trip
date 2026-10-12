#!/usr/bin/env bash
# deploy/backup.sh - back up everything that cannot be rebuilt from code.
#   warehouse + Airflow databases (pg_dump), the file registry, and the data lake (incremental copy).
# Run it by hand, or from cron:  0 3 * * *  cd /home/deploy/taxi-platform && ./deploy/backup.sh >> backups/backup.log 2>&1
# BACKUP_KEEP=7 (default) is how many database/registry backups to keep.
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

PROD="./deploy/prod.sh"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="backups/$STAMP"
KEEP="${BACKUP_KEEP:-7}"

mkdir -p "$DEST" backups/lake
chmod 777 "$DEST" backups/lake      # the containers write as user 1000, which may not be you

echo "==> warehouse database"
$PROD exec -T warehouse sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/warehouse.dump'
$PROD cp warehouse:/tmp/warehouse.dump "$DEST/warehouse.dump"
$PROD exec -T warehouse rm -f /tmp/warehouse.dump

echo "==> Airflow database"
$PROD exec -T airflow-db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/airflow.dump'
$PROD cp airflow-db:/tmp/airflow.dump "$DEST/airflow.dump"
$PROD exec -T airflow-db rm -f /tmp/airflow.dump

echo "==> file registry"
$PROD exec -T ingestion python -m shared.backup registry-backup "/backups/$STAMP/registry.db"

echo "==> data lake (incremental)"
$PROD exec -T ingestion python -m shared.backup lake-backup /backups/lake

for file in warehouse.dump airflow.dump registry.db; do
  test -s "$DEST/$file" || { echo "ERROR: $DEST/$file is missing or empty" >&2; exit 1; }
done
chmod -R go-rwx "$DEST" 2>/dev/null || true

echo "==> keeping the newest $KEEP backups"
# shellcheck disable=SC2012
ls -1dt backups/2* 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -rf

echo "Backup finished: $DEST"
du -sh "$DEST" backups/lake
