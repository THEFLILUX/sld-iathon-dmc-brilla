#!/usr/bin/env bash
# First installation, run as root with the directory uploaded over SSH as its argument.
set -euo pipefail
umask 077
upload_dir=${1:?Indica la carpeta con los archivos de despliegue}
test -f /opt/cuadrilla/.bootstrap-ready
tar -xzf "$upload_dir/source.tar.gz" -C /opt/cuadrilla
deployment_dir=/opt/cuadrilla/deploy/gcp
install -m 0600 "$upload_dir/runtime.env" "$deployment_dir/runtime.env"
install -m 0400 -o 10001 -g 10001 "$upload_dir/account-passwords.json" "$deployment_dir/account-passwords.json"
install -d -m 0755 "$deployment_dir/data"
tar -xzf "$upload_dir/uploads.tar.gz" -C "$deployment_dir/data"
chown -R 10001:10001 "$deployment_dir/data/uploads"
chmod 0755 "$deployment_dir/data/uploads"
cd "$deployment_dir"
docker compose --env-file runtime.env config --quiet
echo 'Descargando PostgreSQL y el proxy HTTPS.'
if ! docker compose --env-file runtime.env pull database proxy > /opt/cuadrilla/pull.log 2>&1; then
    tail -n 50 /opt/cuadrilla/pull.log
    exit 1
fi
echo 'Construyendo la aplicación con las dependencias del proyecto.'
if ! docker compose --env-file runtime.env build app > /opt/cuadrilla/build.log 2>&1; then
    tail -n 70 /opt/cuadrilla/build.log
    exit 1
fi
docker compose --env-file runtime.env up -d database
ready=false
for attempt in $(seq 1 30); do
    if docker compose --env-file runtime.env exec -T database pg_isready -U cuadrilla -d cuadrilla < /dev/null > /dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 2
done
test "$ready" = true
exists=$(docker compose --env-file runtime.env exec -T database psql -U cuadrilla -d cuadrilla -Atqc "SELECT to_regclass('public.usuarios') IS NOT NULL" < /dev/null)
if [ "$exists" = f ]; then
    echo 'Restaurando la copia de la base local.'
    docker compose --env-file runtime.env exec -T database pg_restore -U cuadrilla -d cuadrilla --no-owner --no-acl --single-transaction < "$upload_dir/local-database.dump"
fi
if [ ! -f /opt/cuadrilla/.accounts-prepared ]; then
    docker compose --env-file runtime.env run --rm --no-deps -T \
        -v "$deployment_dir/account-passwords.json:/run/cloud-accounts.json:ro" \
        app python - < prepare_accounts.py
    touch /opt/cuadrilla/.accounts-prepared
fi
echo 'Iniciando la web y el proxy HTTPS.'
docker compose --env-file runtime.env up -d app proxy
install -m 0700 backup.sh /opt/cuadrilla/backup.sh
cat > /etc/cron.d/cuadrilla-backup <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
0 8 * * * root /opt/cuadrilla/backup.sh >> /opt/cuadrilla/backups/backup.log 2>&1
EOF
chmod 0644 /etc/cron.d/cuadrilla-backup
/opt/cuadrilla/backup.sh
docker compose --env-file runtime.env ps --format 'table {{.Service}}\t{{.State}}\t{{.Health}}'
rm -f "$deployment_dir/account-passwords.json"
echo 'Instalación terminada; copia diaria de base y archivos configurada.'
