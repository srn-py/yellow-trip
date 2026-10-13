#!/usr/bin/env bash
# deploy/prod.sh - run docker compose with the production file and settings.
# Examples:  ./deploy/prod.sh up -d      ./deploy/prod.sh ps      ./deploy/prod.sh logs caddy --tail=50
# On Windows run it from Git Bash:  bash deploy/prod.sh ps
set -euo pipefail
export MSYS_NO_PATHCONV=1                 # stop Git Bash from rewriting paths like /tmp/x
cd "$(dirname "$0")/.."

if [ ! -f .env.prod ]; then
  echo "No .env.prod found. Create it with: python scripts/make_prod_env.py --help" >&2
  exit 1
fi

mkdir -p backups data/dropzone            # so Docker does not create them as root

exec docker compose --env-file .env.prod -f docker-compose.prod.yml "$@"
