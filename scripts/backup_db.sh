#!/bin/bash
# ============================================================================
# Grapic Database Backup Script
# ============================================================================
# Backs up PostgreSQL database with pg_dump
# Run this script via cron or manually

set -e  # Exit on error

# ============================================================================
# CONFIGURATION
# ============================================================================

# Load environment variables
if [ -f /mnt/SSD/Codespace/Grapic/.env ]; then
    export $(cat /mnt/SSD/Codespace/Grapic/.env | grep -v '^#' | xargs)
fi

# Database connection (override with env vars or use defaults)
DB_HOST=${DB_HOST:-postgres}
DB_PORT=${DB_PORT:-5432}
DB_NAME=${DB_NAME:-grapic}
DB_USER=${DB_USER:-postgres}
DB_PASSWORD=${POSTGRES_PASSWORD:-changeme}

# Backup directory
BACKUP_DIR=${BACKUP_DIR:-/mnt/SSD/Codespace/Grapic/backups}
mkdir -p "$BACKUP_DIR"

# Retention settings
RETENTION_DAYS=${RETENTION_DAYS:-7}  # Keep backups for 7 days

# ============================================================================
# FUNCTIONS
# ============================================================================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

error() {
    log "ERROR: $1" >&2
    exit 1
}

# ============================================================================
# BACKUP PROCESS
# ============================================================================

log "Starting database backup..."

# Create backup filename with timestamp
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
BACKUP_FILE="$BACKUP_DIR/grapic_backup_$TIMESTAMP.sql.gz"

# Run pg_dump and compress
log "Backing up database: $DB_NAME"
PGPASSWORD=$DB_PASSWORD pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --no-owner \
    --no-acl \
    --format=plain \
    | gzip > "$BACKUP_FILE" || error "Backup failed"

# Check backup file was created
if [ ! -f "$BACKUP_FILE" ]; then
    error "Backup file was not created"
fi

# Get file size
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
log "Backup completed: $BACKUP_FILE ($BACKUP_SIZE)"

# ============================================================================
# CLEANUP OLD BACKUPS
# ============================================================================

log "Cleaning up backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -name "grapic_backup_*.sql.gz" -mtime +$RETENTION_DAYS -delete

# List remaining backups
log "Current backups:"
ls -lh "$BACKUP_DIR"/grapic_backup_*.sql.gz || log "No backups found"

log "Backup process completed successfully"

# ============================================================================
# RESTORE INSTRUCTIONS
# ============================================================================

cat << 'EOF'

To restore from backup:
    gunzip -c /path/to/backup.sql.gz | PGPASSWORD=your_password psql \
        -h postgres -U postgres -d grapic

EOF
