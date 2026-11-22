#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh into a Docker install (replaces the current data).
#
#   scripts/restore.sh backups/workflowos-<time>.dump [backups/workflowos-<time>.secret.key]
#
# Stops the API and worker, restores the database, puts the key file back (if given), migrates
# the schema to the running version, and starts everything again.
set -euo pipefail

COMPOSE=${COMPOSE:-docker compose}
DUMP=${1:?usage: scripts/restore.sh <dump> [secret.key]}
KEY=${2:-}

read -r -p "This replaces all WorkFlowOS data with $DUMP. Type 'restore' to continue: " answer
[ "$answer" = "restore" ] || { echo "cancelled"; exit 1; }

$COMPOSE stop api worker
$COMPOSE exec -T postgres pg_restore -U workflowos -d workflowos --clean --if-exists --no-owner < "$DUMP"
if [ -n "$KEY" ]; then
  $COMPOSE run --rm -T --no-deps --entrypoint sh api -c 'cat > /data/workflowos.secret.key && chmod 600 /data/workflowos.secret.key' < "$KEY"
fi
$COMPOSE run --rm -T --no-deps api python -m app.cli db upgrade
$COMPOSE up -d api worker
echo "restored $DUMP"
