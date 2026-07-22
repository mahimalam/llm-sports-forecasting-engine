#!/bin/bash
# EAP-Sports: Hourly SQLite backup
# Add to cron: 0 * * * * /home/mahimalam2400/Fifa_project/ops/backup.sh
set -euo pipefail

APP_DIR="/home/mahimalam2400/Fifa_project"
DB_PATH="$APP_DIR/eap_sports.db"
BACKUP_DIR="$APP_DIR/backups"
RETENTION_DAYS=7
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Hot backup using sqlite3 .backup (safe with WAL mode)
sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/eap_sports_$TIMESTAMP.db'"

# Compress
gzip "$BACKUP_DIR/eap_sports_$TIMESTAMP.db"

# Prune old backups
find "$BACKUP_DIR" -name "*.db.gz" -mtime +$RETENTION_DAYS -delete

echo "[$(date)] Backup complete: eap_sports_$TIMESTAMP.db.gz"
