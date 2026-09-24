#!/usr/bin/env bash
#
# backup_postgres.sh — dumps the bot's database to a compressed, timestamped
# file and deletes backups older than $KEEP_DAYS.
#
# Usage:
#   sudo ./backup_postgres.sh
#
# Typical cron entry (as root, daily at 03:15):
#   15 3 * * * /path/to/money_manager_bot/deploy/backup_postgres.sh >> /var/log/money_manager_backup.log 2>&1
#
# Restore:
#   gunzip -c /var/backups/money_manager_bot/money_manager_YYYYMMDD_HHMMSS.sql.gz \
#     | sudo -u postgres psql -d money_manager

set -euo pipefail

DB_NAME="${DB_NAME:-money_manager}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/money_manager_bot}"
KEEP_DAYS="${KEEP_DAYS:-14}"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo $0" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUT_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"

sudo -u postgres pg_dump --format=plain --no-owner --dbname="$DB_NAME" | gzip > "$OUT_FILE"
chmod 600 "$OUT_FILE"
echo "==> Backup written to ${OUT_FILE}"

DELETED="$(find "$BACKUP_DIR" -maxdepth 1 -name "${DB_NAME}_*.sql.gz" -mtime "+${KEEP_DAYS}" -print -delete)"
if [[ -n "$DELETED" ]]; then
  echo "==> Removed backups older than ${KEEP_DAYS} days:"
  echo "$DELETED"
fi
