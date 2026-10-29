#!/bin/sh
set -eu

: "${PGHOST:?PGHOST is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"
: "${BACKUP_FILE:?BACKUP_FILE is required}"

expected_confirmation="restore:$PGDATABASE"
if [ "${RESTORE_CONFIRMATION:-}" != "$expected_confirmation" ]; then
  echo "Restore refused. Set RESTORE_CONFIRMATION=$expected_confirmation to continue." >&2
  exit 2
fi
if [ ! -f "$BACKUP_FILE" ]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 2
fi

pg_restore \
  --host "$PGHOST" \
  --username "$PGUSER" \
  --dbname "$PGDATABASE" \
  --clean \
  --if-exists \
  --no-owner \
  --exit-on-error \
  --single-transaction \
  "$BACKUP_FILE"

echo "Restore completed from: $BACKUP_FILE"
