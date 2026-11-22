#!/usr/bin/env bash
# Back up a Docker install: the Postgres database and the credential encryption key.
#
#   scripts/backup.sh [backup-dir]            (default: ./backups)
#   COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml" scripts/backup.sh
#
# Writes <dir>/workflowos-<UTC time>.dump (pg_dump custom format) and, if no WORKFLOWOS_SECRET_KEY
# is set, <dir>/workflowos-<UTC time>.secret.key. Keep the key apart from the dump: together
# they let anyone read the saved integration credentials. Restore with scripts/restore.sh.
set -euo pipefail

COMPOSE=${COMPOSE:-docker compose}
DIR=${1:-./backups}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$DIR"
umask 077

$COMPOSE exec -T postgres pg_dump -U workflowos -d workflowos --format=custom --no-owner > "$DIR/workflowos-$STAMP.dump"
echo "database -> $DIR/workflowos-$STAMP.dump ($(wc -c < "$DIR/workflowos-$STAMP.dump") bytes)"

if $COMPOSE exec -T api test -f /data/workflowos.secret.key; then
  $COMPOSE exec -T api cat /data/workflowos.secret.key > "$DIR/workflowos-$STAMP.secret.key"
  echo "encryption key -> $DIR/workflowos-$STAMP.secret.key (store it separately from the dump)"
else
  echo "no key file: the key comes from WORKFLOWOS_SECRET_KEY in .env (back that up instead)"
fi
