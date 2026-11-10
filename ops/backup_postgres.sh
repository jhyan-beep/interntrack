#!/bin/sh
set -eu

: "${PGHOST:?PGHOST is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"

backup_dir=${BACKUP_DIR:-/backups}
retention_days=${BACKUP_RETENTION_DAYS:-7}
case "$retention_days" in
  ''|*[!0-9]*) echo "BACKUP_RETENTION_DAYS must be a non-negative integer" >&2; exit 2 ;;
esac

mkdir -p "$backup_dir"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
final_path="$backup_dir/interntrack_${timestamp}.dump"
temporary_path="$final_path.tmp"
trap 'rm -f "$temporary_path"' EXIT HUP INT TERM

pg_dump \
  --host "$PGHOST" \
  --username "$PGUSER" \
  --dbname "$PGDATABASE" \
  --format custom \
  --no-owner \
  --file "$temporary_path"

mv "$temporary_path" "$final_path"
trap - EXIT HUP INT TERM
find "$backup_dir" -type f -name 'interntrack_*.dump' -mtime "+$retention_days" -delete
echo "Backup created: $final_path"
