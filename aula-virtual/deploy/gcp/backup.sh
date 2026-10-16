#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/cuadrilla/deploy/gcp
backup_dir=/opt/cuadrilla/backups
mkdir -p "$backup_dir"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
docker compose --env-file runtime.env exec -T database pg_dump -U cuadrilla -d cuadrilla -Fc > "$backup_dir/database-$timestamp.dump"
tar -czf "$backup_dir/uploads-$timestamp.tar.gz" -C data uploads
find "$backup_dir" -type f \( -name 'database-*.dump' -o -name 'uploads-*.tar.gz' \) -mtime +14 -delete
