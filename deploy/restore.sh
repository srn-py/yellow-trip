#!/usr/bin/env bash
# deploy/restore.sh - restore a backup made by deploy/backup.sh.   Usage: ./deploy/restore.sh backups/<timestamp>
# It REPLACES the warehouse, Airflow's database, the file registry and re-uploads the data lake.
# It works on a brand-new server too: install, create .env.prod, copy the backups folder over, run this.
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

SRC="${1:?usage: deploy/restore.sh backups/<timestamp>}"
SRC="${SRC%/}"
STAMP="$(basename "$SRC")"
PROD="./deploy/prod.sh"

for file in warehouse.dump registry.db; do
  test -s "$SRC/$file" || { echo "ERROR: $SRC/$file not found. Is this a backup folder?" >&2; exit 1; }
done

if [ "${FORCE:-}" != "1" ]; then
  echo "This REPLACES the warehouse, the registry and the lake contents with the backup from $STAMP."
  read -r -p "Type 'restore' to continue: " answer
  [ "$answer" = "restore" ] || { echo "Cancelled."; exit 1; }
fi

echo "==> starting the databases and the object store"
$PROD up -d --wait warehouse airflow-db objectstore

echo "==> stopping everything that writes"
$PROD stop airflow etl cleaning ingestion analytics quality dashboard

echo "==> warehouse database"
$PROD cp "$SRC/warehouse.dump" warehouse:/tmp/restore.dump
set +e
$PROD exec -T warehouse sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner /tmp/restore.dump'
status=$?
set -e
[ "$status" -eq 0 ] || echo "WARNING: pg_restore reported problems (exit $status). Check the output above, then verify the data."
$PROD exec -T warehouse rm -f /tmp/restore.dump

if [ -s "$SRC/airflow.dump" ]; then
  echo "==> Airflow database"
  $PROD cp "$SRC/airflow.dump" airflow-db:/tmp/restore.dump
  set +e
  $PROD exec -T airflow-db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner /tmp/restore.dump'
  set -e
  $PROD exec -T airflow-db rm -f /tmp/restore.dump
fi

echo "==> file registry"
$PROD run --rm --no-deps -T ingestion python -m shared.backup registry-restore "/backups/$STAMP/registry.db"

echo "==> data lake"
$PROD run --rm --no-deps -T ingestion python -m shared.backup lake-restore /backups/lake

echo "==> starting everything"
$PROD up -d

echo "Restore finished. Verify it: see 'Restore drill' in docs/deployment.md."